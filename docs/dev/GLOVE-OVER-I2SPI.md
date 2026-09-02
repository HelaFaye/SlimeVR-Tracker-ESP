# Glove / hand tracking over I2SPI — feasibility note

> **Resolved: Reading A.** The requirement is palm rotation and position, no fingers. That
> is a back-of-hand tracker on `LEFT_HAND` / `RIGHT_HAND`, attaching as node 2 on the
> existing arm chains. **No firmware change, no server change, no glove.** The rest of this
> document is kept for the day per-finger tracking comes up again.
>
> Note on "position": SlimeVR IMU trackers are rotation-only (`Tracker.hasPosition` is
> `false`). Palm *position* is solved, not measured — the server's `human://LEFT_HAND`
> computed tracker is built with `hasPosition = true, hasRotation = true`, taking rotation
> from your IMU and position by forward kinematics down the arm chain. With upper arm,
> lower arm and hand all measured, that chain is fully constrained, which is the best case
> the solver gets. Downstream (SteamVR, OSC, VMC) sees a full 6-DoF palm pose.

Written after "wrist" was corrected to "hand/glove". Conclusions first, because one of them
argues against using I2SPI for part of this.

---

## What "15 points" probably means, and why it matters

Two readings, and they differ by an order of magnitude in effort:

**Reading A — 15 IMU sites on the body.** The 13 from `EXAMPLE-18POINT-BUILD.md` plus a
tracker on the back of each hand. Those map to `LEFT_HAND` / `RIGHT_HAND`, exactly as the
wrist version did, and **nothing changes**: they hang off the arm chains as node 2, no
firmware change, no server change.

**Reading B — a real glove with per-finger sensors.** Here 15 is a suspiciously exact
number: `TrackerPosition` defines precisely **15 finger bones per hand** —

```
thumb:  metacarpal, proximal, distal          (3)
index:  proximal, intermediate, distal        (3)
middle: proximal, intermediate, distal        (3)
ring:   proximal, intermediate, distal        (3)
little: proximal, intermediate, distal        (3)
```

ids 21–35 for the left hand, 36–50 for the right. If that is the 15 you meant, the rest of
this document applies.

---

## Server side: fully supported

`HumanSkeleton` has a bone and a tracker slot for every one of the 30 finger positions,
`hasLeftFingerTracker` / `hasRightFingerTracker` detection, and `updateFingerTransforms()`
driving them. `SkeletonConfigManager` even divides total finger length over anatomical
ratios, so proportions are handled. `FirmwareConstants` already knows
`GLOVE_IMU_SLIMEVR_DEV`.

No server patch needed for the tracking itself.

**One practical gap:** board type arrives in the handshake but is informational — position
assignment is manual. Assigning 15 sensors per hand by hand in the UI, twice, is unpleasant
and error-prone in a way that will produce mysteriously wrong fingers. Some form of
per-board default assignment is worth wanting. That is a server feature request, not a
blocker.

---

## Firmware side: the existing glove already does 10

`src/boards/glove_default.h` is a working 10-sensor glove: two IMUs on a direct I2C wire
plus eight more behind a PCA9547 mux, with MCP23X17 pins for interrupts, and
`MAX_SENSORS_COUNT 10`. Two sensors per finger, not three.

That is not a limitation, it is a reasonable design choice. The distal joint is strongly
coupled to the intermediate one — the human hand cannot flex them independently without
effort — so the third segment is usually derived rather than measured. **Ten sensors buys
most of the fidelity of fifteen.** Worth deciding deliberately rather than defaulting to
"one per bone because the enum has one per bone".

I have raised the board-defaults schema ceiling from 8 to 16 sensors so a full
15-plus-palm config is at least expressible.

---

## Where I2SPI helps, and where it does not

**Honest assessment: I2SPI is the right answer for getting *to* the glove, and a
questionable one for inside it.**

The RJ45 chain was designed for a specific problem — several sensors, metres apart, on a
body, where one host GPIO per chip select is impossible and cable length limits SPI. On a
glove none of that holds. Runs are 20 cm, and the existing I2C mux approach already solves
fan-out with parts that are cheaper and smaller than an ATtiny per node.

What I2SPI would buy inside a glove:

- **SPI data rate.** Sixteen sensors on 400 kHz I2C is a real constraint; on 4 MHz SPI it
  is not. If you want 15 sensors per hand at a decent ODR, the bus matters.
- **Fewer parts than one node per sensor**, using protocol v2 channels: one ATtiny per
  finger, three channels each, five nodes for fifteen sensors.

What it costs, stated plainly so the channel feature is not oversold:

- **Channels reduce nodes, not bus traffic.** Every sensor still needs its own chip select
  and therefore its own arm write. Five nodes × three channels costs exactly the same
  fifteen arm writes per cycle as fifteen single-channel nodes. The saving is board area,
  parts and power — not time.
- **Multi-channel requires `EXTERNAL_CS_GATE`**, so three OR gates per finger node. On a
  finger. That is fifteen extra parts per glove.

### The bus arithmetic

Sixteen sensors on one chain, per poll cycle:

| | at 400 kHz I2C | at 1 MHz I2C |
|---|---|---|
| 16 arm writes (~3 bytes each) | 1.2 ms | 0.48 ms |
| 16 FIFO reads over 4 MHz SPI | 0.64 ms | 0.64 ms |
| **Total per cycle** | **~1.85 ms** | **~1.1 ms** |
| As a fraction of a 200 Hz (5 ms) cycle | 37% | 22% |
| As a fraction of a 100 Hz (10 ms) cycle | 18% | 11% |

Two conclusions. Run the glove chain at **Fast-mode Plus** — the wiring is short and
low-capacitance, so 1 MHz is far easier here than on the 85 cm body cable. And run fingers
at **100 Hz**, not 200: fingers do not move fast enough to need more, and it halves the
cost.

---

## The part that actually decides it: mechanical

An RJ45 jack does not go on a finger, and flat patch cable does not survive a knuckle. The
*protocol* travels into a glove; the *connector and cable standard* do not.

A plausible split:

1. **Forearm hub → glove**: one RJ45, exactly as specified today. This is a normal I2SPI
   link over ~30 cm and needs nothing new.
2. **Inside the glove**: a flex PCB fanning the same eight signals to each finger, with the
   node boards as small flex-mounted islands. Six signals plus power to every finger
   segment, flexing at every joint, thousands of times per session.

That flex harness is the hardest engineering problem in this entire project — harder than
the C5 bring-up, harder than the CCL gating, harder than the cable EMC. It is also the
part with the least prior art in this repo.

---

## Recommendation

- If you meant **Reading A**, stop here: back-of-hand trackers on the arm chains, done, no
  changes at all.
- If you meant **Reading B**, use I2SPI for the forearm-to-glove link, and treat the
  in-glove topology as a separate design exercise. Start from the existing 10-sensor I2C
  glove rather than from this chain design — it is proven, and two-per-finger is probably
  the right fidelity anyway.
- Either way, resolve the manual-assignment problem before building two gloves. Thirty
  hand-assigned finger trackers is where this stops being fun.

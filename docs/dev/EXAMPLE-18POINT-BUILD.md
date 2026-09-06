# Example build: 18-point tracking, 5 hubs + 8 I2SPI extensions

A worked end-to-end example of the RJ45 chain design: five battery-powered hub trackers,
each carrying its own IMU and hosting one or two remote extensions over flat RJ45.

Protocol reference: `ATTINY-CS-PROTOCOL.md`. Cable and electrical limits:
`HARDWARE-RJ45-SPI-BUS.md`. Board specifications: `../hardware/BOARD-SPECS.md`.

---

## Sensor inventory

| Hub | Worn on | Extension node 1 | Extension node 2 |
|---|---|---|---|
| H1 | Chest | Waist | Hip |
| H2 | Left upper thigh | Left lower leg | Left foot |
| H3 | Right upper thigh | Right lower leg | Right foot |
| H4 | Left upper arm | Left lower arm | — |
| H5 | Right upper arm | Right lower arm | — |

Five hub IMUs, eight extension IMUs, **13 IMU sites**. Every site is an ICM-45686 with a
QMC6309 magnetometer on the IMU's own AUX1 bus (DEC-008), so the magnetometer costs
nothing on the chain.

### The point count, resolved

The gap I flagged earlier closes with the wrists: **15 IMU sites** (13 above plus two
wrists) plus HMD and two controllers is **18 tracked points**. Both of your numbers refer
to the same build — 15 counts sensors, 18 counts tracked points.

The wrists go on the arm chains as node 2, which are currently empty:

| Hub | Node 1 | Node 2 |
|---|---|---|
| H4 left upper arm | Left lower arm | **Left palm** (back of hand) |
| H5 right upper arm | Right lower arm | **Right palm** (back of hand) |

This needs **no firmware change and no server change**. The hub config already declares
three sensors with 1 and 2 optional, and the arm hubs simply find node 2 where they
previously found nothing. Two more extension boards and two more cables.

### Palm trackers on the server side

There is no `WRIST` or `PALM` position in SlimeVR and there does not need to be. From
`TrackerPosition.kt`, the enum runs to 50 entries and includes `LEFT_HAND` (id 17) and
`RIGHT_HAND` (id 18), each with a full `TrackerRole`, its own bone, its own tracker bone
and a `COMPLETE` constraint in `HumanSkeleton`. A tracker on the back of the hand is
assigned to the hand position — that is the standard practice and what the skeleton is
built for. Rotation comes from the IMU; position is solved by forward kinematics down the
arm chain and published by the `human://LEFT_HAND` computed tracker, which is constructed
with `hasPosition = true, hasRotation = true`. With upper arm, lower arm and hand all
measured the chain is fully constrained, so the solved palm position is as good as this
gets without an optical reference. "Wrist" appears in the server only as an internal Unity/VMC armature node and
as VRChat's OSC input paths, neither of which is a tracker position.

**The arm FK setting, and how to switch it.** `SkeletonConfigToggles.FORCE_ARMS_FROM_HMD`
defaults to `true`, and **true is the mode this build wants** — leave it alone.

The name is misleading. "Force arms from HMD" does not mean the HMD drives your arm
rotations; it means the arm chain is *assembled downward* from the shoulder, anchored to
the HMD-referenced body, so each arm bone comes from the tracker on it. From
`HumanSkeleton.assembleSkeletonArms()`:

```kotlin
if (isTrackingLeftArmFromController) {          // false by default
    leftHandTrackerBone.attachChild(leftHandBone)     // built UP from the hand
    leftHandBone.attachChild(leftLowerArmBone)
    leftLowerArmBone.attachChild(leftElbowTrackerBone)
} else {                                        // this is the default path
    leftUpperArmBone.attachChild(leftLowerArmBone)    // built DOWN from the shoulder
    leftUpperArmBone.attachChild(leftElbowTrackerBone)
    leftLowerArmBone.attachChild(leftHandBone)
    leftHandBone.attachChild(leftHandTrackerBone)
}
```

The condition is:

```kotlin
val isTrackingLeftArmFromController: Boolean
    get() = leftHandTracker != null && leftHandTracker!!.hasPosition && !forceArmsFromHMD
```

Two things follow. First, the default (`forceArmsFromHMD = true`) always takes the
tracker-driven branch. Second — and this is the part that makes it a non-issue here —
`Tracker.hasPosition` defaults to `false` and SlimeVR IMU trackers are rotation-only. A
wrist IMU assigned to `LEFT_HAND` therefore **cannot** trigger controller mode no matter
how the toggle is set. Controller-driven arms need a positional hand tracker, which in
practice means a SteamVR controller fed in through the bridge.

**Switching between them** is a live runtime toggle, no restart:

- GUI: Settings → General → FK settings → Arm FK → "Force arms from HMD".
- RPC: `RPCSettingsHandler` exposes the same toggle, so it is scriptable.

`updateToggleState()` calls `assembleSkeletonArms(true)` and `computeDependentArmOffsets()`,
which re-parent the bone tree and recompute offsets on the spot. So you can flip it while
wearing the suit and watch the difference.

The switch is only meaningful if you hold controllers *and* want them to drive the
forearm. With this build — upper arm, lower arm and wrist all on IMUs — the tracker branch
is what you want, and it is already the default.

---

## Chain assignment and node ids

Node ids are **per chain**, not global. Every chain uses node 1 and, where present, node 2.

That means the whole build needs exactly **two** node firmware images (`node1`, `node2`)
rather than eight, and any node-1 extension is a drop-in spare for any other node-1
position. The cost is that a lower leg plugged into the chest chain will work and report
as "waist" — the extension has no idea where on the body it is.

That is the right trade here, because **position is assigned server-side anyway**. The
firmware's job is to say "hub 2, sensor 1"; SlimeVR's tracker assignment says which body
part that is. Making extensions carry body identity would duplicate that mapping in a
place that is harder to change.

Label the physical boards anyway. `node1` and `node2` differ only in one `#define`, and
telling them apart at the bench is worth a sticker.

```
                 ┌──────────┐
                 │  H1 chest│ IMU + chain
                 └────┬─────┘
                RJ45  │  25 cm
                 ┌────▼─────┐
                 │ N1 waist │
                 └────┬─────┘
                RJ45  │  15 cm
                 ┌────▼─────┐
                 │ N2 hip   │
                 └──────────┘

  ┌────────────┐              ┌────────────┐
  │ H2 L thigh │              │ H4 L u.arm │
  └─────┬──────┘              └─────┬──────┘
  45 cm │ (crosses knee)      30 cm │ (crosses elbow)
  ┌─────▼──────┐              ┌─────▼──────┐
  │ N1 L lower │              │ N1 L lower │
  │    leg     │              │    arm     │
  └─────┬──────┘              └────────────┘
  40 cm │ (crosses ankle)      (N2 free - shoulder option)
  ┌─────▼──────┐
  │ N2 L foot  │
  └────────────┘

  H3 / H5 mirror H2 / H4 on the right.
```

Longest chain is a leg at **85 cm** of cable. That sits inside the conservative envelope:
at ~60 pF/m per conductor the I2C bus sees roughly 50 pF of cable plus node input
capacitance, well under the 400 pF Fast-mode budget, and 4 MHz SPI over 85 cm of
source-terminated flat cable should be comfortable.

---

## Firmware images

**One hub image for all five hubs.** `BOARD_SLIMEVR_C5_CHAIN_HUB` declares three sensors:
a local IMU on a direct chip select, plus nodes 1 and 2 on I2SPI. Because the generator
marks sensor 0 mandatory and the rest optional, the arm hubs — which have no node 2 —
simply find nothing there and register an `EmptySensor`. No separate arm build.

The IMU rotation in the descriptor is the IMU's orientation *on the PCB*, not on the body,
so identical boards share it. Body mounting orientation is solved by the server's mounting
calibration.

Generated flags:

```
-DMAX_SENSORS_COUNT=3
-DREMOTE_CS_SCL=4 -DREMOTE_CS_SDA=5 -DREMOTE_CS_BASE_ADDR=48 -DREMOTE_CS_STROBE=6
-DSENSOR_DESC_LIST='
  SENSOR_DESC_ENTRY(IMU_ICM45686, DIRECT_PIN(3), DEG_0, SPI_BUS(4000000,MSBFIRST,SPI_MODE3,10,11,12), false, DIRECT_PIN(9), 0)
  SENSOR_DESC_ENTRY(IMU_ICM45686, ATTINY_CS(1),  DEG_0, SPI_BUS(4000000,MSBFIRST,SPI_MODE3,10,11,12), true,  DIRECT_PIN(255), 0)
  SENSOR_DESC_ENTRY(IMU_ICM45686, ATTINY_CS(2),  DEG_0, SPI_BUS(4000000,MSBFIRST,SPI_MODE3,10,11,12), true,  DIRECT_PIN(255), 0)'
```

Note the local IMU and the remote ones share **one SPI bus**. The local sensor's chip
select is an ordinary GPIO; the remote ones are I2SPI. `SPIImpl` cannot tell the
difference, which is the whole point of routing remote CS through `PinInterface`.

**Two node images**, `node1` and `node2`, from `extras/attiny-cs-node/`.

**Total: three images across thirteen boards.**

---

## What happens on the wire

Per hub, one poll cycle over three sensors:

1. **Local IMU.** `ATTinyCSBus` is not involved. GPIO 3 goes low, FIFO burst, high.
   But note: the previously armed node is still armed, and the shared strobe is idle
   high, so no remote CS is asserted. The local and remote sensors coexist on the bus
   because only one chip select is ever low.
2. **Node 1.** `select(1, 0)` — one 3-byte I2C write to `0x30`, about 70 µs at 400 kHz.
   Node 1 enables its gating; every other node forces CS high. Then each SPI transaction
   is framed by toggling GPIO 6.
3. **Node 2.** Same, one more arm write.

So a full cycle costs **two arm writes**, not two per register access. At a 200 Hz sample
rate that is roughly 140 µs of I2C per 5 ms cycle — under 3% of the budget. Raising the
chain I2C to Fast-mode Plus halves it again if you need the headroom.

The failure mode worth understanding: if an arm write is NAKed, `ATTinyCSBus` clears its
cached target, logs, and **does not touch the strobe** — because some other node may still
be armed, and pulsing the strobe would assert *its* chip select. The affected sensor reads
nothing for that cycle and re-arms on the next.

---

## Power budget

Estimates, to be measured rather than trusted:

| Item | Current |
|---|---|
| ICM-45686, 6-axis low-noise mode | 0.42 mA (datasheet) |
| QMC6309, 200 Hz continuous | ~0.5 mA |
| ATtiny412 at 5 MHz / 3.3 V | ~3 mA |
| **Per extension node** | **~4 mA** |
| ESP32-C5 hub, Wi-Fi connected average | ~100 mA (highly variable) |

A two-node chain adds ~8 mA to a ~104 mA hub, so roughly **8% off runtime** for the chest
and leg hubs, ~4% for the arm hubs. (The IMU figure is now the datasheet's 0.42 mA for
6-axis low-noise mode; an earlier revision of this table guessed 2.5 mA and overstated the
cost by half.) Not free, but the alternative is eight more
batteries and eight more Wi-Fi radios.

Drop the ATtiny clock as far as the TWI slave tolerates — it is the largest single draw at
a node and it does almost nothing. 5 MHz is a reasonable starting point; at 1 MHz the
slave may struggle to keep up with 400 kHz I2C.

Voltage drop is a non-issue at these currents: 26 AWG at 0.1339 Ω/m carrying 7.8 mA over
0.85 m gives **1.8 mV**, counting both conductors — the supply out and the ground return
each drop the same amount, which the first version of this figure forgot.

---

## Bring-up order

Do not build all thirteen and then power on. The failure modes here (a chain that
half-works at 8 MHz, a node flashed with the wrong id) are much easier to find one
variable at a time.

1. **One hub, no chain.** Confirm the local IMU is detected and the tracker connects.
   This validates the C5 board support with nothing remote in play.
2. **One hub, one node, 30 cm cable, software CS.** Omit `strobe` from `REMOTE_CS` so
   CS is driven over I2C. Slow, but it removes the CCL and the strobe conductor from the
   equation entirely.
3. **Same, strobe mode.** Scope CS at the extension IMU: the strobe edge should reach it
   in tens of nanoseconds. If it doesn't, the gating is not doing what you think.
4. **Add node 2.** Check node 1 still works after adding it — this is where address and
   arming bugs surface.
5. **Full cable length**, then walk the SPI clock up until detection fails and back off by
   half.
6. **Replicate to the other four hubs.**

At step 1 the boot log should list the chain enumeration. `ATTinyCSBus::init()` probes all
15 possible node ids and reports what answered, including magic mismatches, protocol
version mismatches, and — the one that saves an afternoon — a node answering at one
address while reporting a different id, which means the wrong image got flashed.

---

## Server side

Thirteen IMUs arrive as five trackers with three, three, three, two and two sensors. Each
hub's sensors are numbered 0 (local), 1 (node 1), 2 (node 2), and body assignment happens
in the SlimeVR server as usual.

Worth checking before committing to this topology: the server's handling of more than two
sensors per tracker. `MAX_SENSORS_COUNT` defaults to 2 in `boards_default.h` and the glove
board already raises it to 10, so the firmware side is proven — but the assignment UI is
the part I have not verified. It is on the open list in `PLAN.md`.

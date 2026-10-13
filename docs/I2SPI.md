# I2SPI specification

**SPI data, I2C selection.** A way to run many sensors over one flat 8-conductor cable. An
addressed microcontroller at each sensor ("node") owns that sensor's chip select (SPI) or
its clock (I2C). A host arms exactly one node at a time with a short I2C broadcast, and then
talks to the armed sensor at full bus speed.

| | |
|---|---|
| Protocol version | **3** (`ATTinyCS::ProtocolVersion = 0x03`) |
| Status | Reference implementation complete and tested in simulation; **not yet proven on hardware** (§14.6) |
| Normative source | This document. Where it and the code disagree, one of them is a bug: report it |
| Constants | `src/sensorinterface/ATTinyCSProtocol.h`, shared verbatim by host and node firmware |
| Rationale | `docs/dev/DECISIONS.md`, referenced inline as DEC-nnn |

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT** and **MAY** are used as in
RFC 2119. Anything not marked with one is explanation.

---

## Contents

1. [Scope and model](#1-scope-and-model)
2. [Physical layer: cable and connector](#2-physical-layer-cable-and-connector)
3. [Electrical requirements](#3-electrical-requirements)
4. [Node hardware](#4-node-hardware)
5. [Addressing](#5-addressing)
6. [Frames and commands](#6-frames-and-commands)
7. [Reads and identity](#7-reads-and-identity)
8. [Node behaviour](#8-node-behaviour)
9. [Host behaviour](#9-host-behaviour)
10. [Timing](#10-timing)
11. [Several chains](#11-several-chains)
12. [Versioning and extension](#12-versioning-and-extension)
13. [Conformance](#13-conformance)
14. [Limits, scaling and open questions](#14-limits-scaling-and-open-questions)
15. [Design checklist for new hardware](#15-design-checklist-for-new-hardware)
16. [Reference implementation map](#16-reference-implementation-map)

---

## 1. Scope and model

SPI has no addressing: *n* sensors need *n* chip selects, which means *n* host GPIOs and *n*
conductors. On a body-worn tracker with sensors a metre apart, an 8-conductor cable runs out
after three. I2SPI keeps SPI for data and adds an I2C **control plane for selection only**.
One host GPIO frames every SPI transaction, and an I2C broadcast decides which sensor that
GPIO reaches. Sensor count is then bounded by addressing, not conductors.

Since v3, a node can also host **I2C sensors**. It gates their SCL so that only the armed
one can hear the bus (DEC-016). This means chained I2C sensors consume no bus addresses, and
identical parts at identical addresses can share a chain.

**Roles.**

| Term | Meaning |
|---|---|
| **Host** | The tracker MCU. Bus master for both SPI and the chain I2C. Exactly one per chain |
| **Chain** | One cable run: one I2C address, one CS_STROBE conductor, up to 15 nodes daisy-chained |
| **Node** | An addressed MCU at a sensor site. Owns 1–16 channels |
| **Channel** | One gated signal on a node: an SPI sensor's CS, or an I2C sensor's SCL |
| **Target** | `(nodeId << 4) \| channel`, one byte. Identifies one channel on one node |
| **Armed** | The one target currently allowed to reach its sensor |

**Invariant (one-hot).** At any instant, at most one channel on a chain is armed. With
several chains on one I2C bus, at most one channel across all of them is armed (§11). Every
safety property in this document follows from that invariant.

**The name.** It reads as I²S to most people and suggests a merged bus. Say "I2SPI (SPI
data, I2C selection)" on first use (DEC-013).

---

## 2. Physical layer: cable and connector

### 2.1 Connector and pinout

Off-the-shelf **flat** 8P8C (RJ45) patch cable, **straight-through**, T568B at both ends.
Flat cable is a ribbon: no twisted pairs, so treat it as eight parallel single-ended wires
with significant pin-to-pin capacitance and **one** ground return.

| Pin | T568B colour | Signal | Direction | Requirement |
|---:|---|---|---|---|
| 1 | white/orange | **VBUS** (3V3) | host → nodes | Powers node MCUs. Sensor rails are gated at each node (§4.3) |
| 2 | orange | **GND** | — | The only return path for all seven signals |
| 3 | white/green | **SPI_SCK** | host → nodes | Series termination at the host (§3.2) |
| 4 | blue | **SPI_MOSI** | host → nodes | Series termination at the host |
| 5 | white/blue | **SPI_MISO** | nodes → host | Driven only by the armed sensor |
| 6 | green | **CS_STROBE** | host → nodes | Idle HIGH. Series termination at the host |
| 7 | white/brown | **CHAIN_SDA** | bidirectional | Pull-up **at the host only** |
| 8 | brown | **CHAIN_SCL** | host → nodes | Pull-up **at the host only** |

- Cables **MUST** be straight-through, so every node is wired identically and cables are
  interchangeable.
- GND on pin 2 sits between VBUS and SCK, the best place for the worst aggressor given a
  fixed straight-through assignment. There is no second ground to give.
- There is deliberately **no interrupt conductor**. Pin 6 carries the strobe instead,
  which is the central design decision (DEC-004, §2.2).

### 2.2 Why pin 6 is a strobe

Most target IMUs (ICM-45686, BMI270, LSM6DSx) require CS to **rise between register
transactions**, because their SPI state machine resets on that edge. If each CS edge cost
an I2C write (~95 µs at 400 kHz), one framed transaction would cost ~190 µs, and a FIFO
poll is several transactions.

So the frame is made free and only selection costs anything. The host arms a node with one
I2C write. That node routes CS_STROBE straight to its sensor's CS **in hardware**
(combinational, tens of nanoseconds, no CPU in the path), and every other node holds its CS
high. The host then frames each transaction by toggling one GPIO. I2C traffic scales with
**sensor switches**, not SPI transactions.

### 2.3 Topology

- Daisy chain. Each node has **two jacks wired pin-for-pin in parallel**, so a mid-chain
  node is a zero-length stub.
- No end terminator: the reflection is tolerable at these rates, and a parallel
  terminator costs standing current a battery tracker does not have.
- **No hot-plug.** Hosts **MUST** be powered down to re-cable. Powering a node while the bus
  is live can latch up the sensor through its I/O pins.

---

## 3. Electrical requirements

### 3.1 Levels and pull-ups

- All signals are 3.3 V CMOS.
- CHAIN_SDA and CHAIN_SCL **MUST** be pulled up at the host, and **MUST NOT** be pulled up
  at nodes. Default 2.2 kΩ. Six nodes at 4.7 kΩ each parallel down to ~780 Ω, below what
  many parts can pull low.
- 2.2 kΩ drives ~160 pF at 400 kHz, enough for a few nodes and ~2 m of cable. A long or
  full chain needs stronger pull-ups, down to ~970 Ω. See §14.2 for the arithmetic.
- I2C cable capacitance: flat cable runs ~50–70 pF/m per conductor against I2C's 400 pF
  Fast-mode budget. The longest reference chain (0.85 m) is ~51 pF. Beyond ~2 m, hosts
  **SHOULD** drop to 100 kHz or add an active terminator.

### 3.2 Signal integrity

- Hosts **MUST** fit 33–47 Ω series resistors on SCK, MOSI and CS_STROBE, at the host end
  (source termination). This is the highest-value SI measure on ribbon cable, and costs
  three resistors.
- MISO **SHOULD NOT** be terminated at the host. If terminated, terminate at each node's
  driver.
- SPI clock: start at **4 MHz** on cable, prove the chain end to end, then raise it. Expect
  8–12 MHz to work at ~1 m. Board defaults **MUST NOT** carry PCB-trace clock rates
  (24 MHz) onto a cable.

### 3.3 Power

- VBUS carries 3.3 V to node MCUs. Each sensor rail **MUST** be switched at its node
  (§4.3).
- Budget per reference node: ~5.4 mA (ICM-45686 0.42 mA + QMC6309 2.0 mA at the ODR/OSR the
  firmware selects + ATtiny412 ~3 mA). Current traverses two conductors (VBUS out, GND
  back).
- **Conductor gauge.** Flat patch cable is commonly **32 AWG** (~1.08 Ω/m round trip);
  round patch cable is 24–26 AWG (26 AWG: ~0.27 Ω/m). Design for 32 AWG unless the cable is
  specified. A two-node chain at 0.85 m then drops ~9.9 mV, which is negligible. How many
  nodes a longer chain can feed is in §14.2.
- Nodes that add LEDs or other loads **SHOULD** regulate locally.

---

## 4. Node hardware

### 4.1 MCU requirements

A node MCU:

- **MUST** have a **hardware** I2C slave peripheral. A bit-banged slave caps near 100 kHz
  and forces the chain into the bring-up performance tier.
- **MUST** listen on one 7-bit address (v3 needs only one: DEC-015).
- **MUST** have, per channel, one output for the gating signal, plus SDA and SCL. On-chip
  gating additionally needs CS_STROBE as an input.
- **MUST** come out of reset with every channel idle (§8.1) **before** enabling its I2C
  slave.
- **SHOULD** be programmable in-circuit through a pad (UPDI on the reference node).

Not viable: ATtiny4/5/9/10 (no serial peripheral at all, DEC-009). ATtiny85 works only with
external gates (USI, no CCL).

| Part | Gating | Notes |
|---|---|---|
| **ATtiny412 / 402 / 212 / 202** | CCL (one usable output on 8 pins) | Reference. Pin map is fixed (§4.4) |
| ATtiny414 / 814 / 1614 | CCL | Spare pins for multi-channel or extra loads |
| PIC16F18313 / 18323 | CLC + PPS | Gated output routes to any pin. Second toolchain |
| CH32V003 | external gates | Cheap RISC-V; `Wire` slave support patchy |
| STM32C011 | external gates | Mature HAL |
| Any MCU with a hardware I2C slave | external gates | v3 needs nothing more |

### 4.2 Gating logic

Each channel's gated signal **MUST** follow the rules below, implemented combinationally:
either in on-chip logic (CCL, CLC) or with one external single-gate part per channel. No
CPU may sit in the path. The host cannot tell the variants apart (DEC-010).

**SPI channel: gate the chip select.** CS idles HIGH.

```
CS = CS_STROBE OR ARMED_N          74LVC1G32 (SOT-353), or CCL LUT
```

| ARMED_N | CS_STROBE | CS | Meaning |
|---|---|---|---|
| 1 (not armed) | x | 1 | Deselected whatever the strobe does |
| 0 (armed) | 1 | 1 | Armed, between transactions |
| 0 (armed) | 0 | 0 | Armed, transaction in progress |

Software-CS fallback falls out for free. With the host parking CS_STROBE low, `CS ==
ARMED_N`, so driving ARMED_N over I2C *is* driving CS.

**I2C channel: gate the sensor's SCL.** SCL idles LOW when gated (DEC-016).

```
SCL_sensor = CHAIN_SCL AND ARMED   74LVC1G08 (SOT-353)
```

- Gated SCL **MUST** be held LOW, not high. A slave detects START as SDA falling while SCL
  is high, so a sensor whose clock is held low cannot see a START at all and is
  electrically absent.
- SDA **MUST NOT** be gated. It is bidirectional, and gating it would break ACK.
- The sensor's rail **MUST NOT** be used as the gate. Cutting power loses its configuration
  on every deselect.

### 4.3 Sensor power gating

- Each node **MUST** switch its sensors' supply through a **P-channel high-side pass
  MOSFET**, gate driven by the node MCU.
- A pull-up (100 kΩ reference) **MUST** hold the gate high (FET off) whenever the MCU is
  not driving it: unprogrammed, in reset, or before `setup()`. A node that fails to boot
  then degrades to "sensor absent", never to a bus fight.
- Low-side switching **MUST NOT** be used. It floats the sensor's ground while its I/O
  remains tied to a live bus, back-powering it through ESD diodes.
- Sensors **MUST** power up **off** (`SensorPowerDefaultOn = false`).
- The gated rail **SHOULD** have local bulk capacitance (1 µF reference), which sets the
  ramp the host's settle delay waits for.

### 4.4 Reference node (ATtiny412, SOIC-8)

The pin map is **not** a free choice. On an 8-pin tinyAVR, PA4/PA5 do not exist, so
`LUT0-OUT` is unavailable and **PA7 carries LUT1-OUT**. LUT1's direct pin inputs are on
PORTC, also absent, so the strobe reaches LUT1 through the event system from PA6. TWI has
no alternate position, so SDA/SCL are fixed at PA1/PA2 (DS40001911B, Table 5-1).

| SOIC-8 pin | Port | Net | Notes |
|---:|---|---|---|
| 1 | VCC | VBUS | |
| 2 | PA6 | CS_STROBE | Input, via event system to CCL LUT1 |
| 3 | PA7 | CS_IMU | LUT1 output; port drives HIGH when disarmed |
| 4 | PA1 | CHAIN_SDA | TWI0 SDA. No pull-up on the node |
| 5 | PA2 | CHAIN_SCL | TWI0 SCL. No pull-up on the node |
| 6 | PA0 | UPDI | 4.7 kΩ to VBUS, test pad |
| 7 | PA3 | SENSOR_PWR_G | Pass-FET gate; 100 kΩ pull-up to VBUS |
| 8 | GND | GND | |

Pin numbers are checked against KiCad's symbol, and the board's wiring against the node
firmware's ports, by `gen/check_node_pins.py` in the hardware repository.

Also on the reference node: ICM-45686 IMU on the cable's SPI lines; QMC6309 magnetometer on
the **IMU's AUX1 I2C master**, never the chain I2C (§4.5); 100 nF at every supply pin, 10 µF
bulk on VBUS; two RJ45 jacks in parallel.

### 4.5 Magnetometers

A magnetometer **MUST NOT** sit on the chain's I2C. The QMC6309 has a fixed address (`0x7c`,
no strap), and other parts have one or two, so several nodes' mags would collide. A node
has two ways to carry one; the host fuses either with the IMU it is configured against.

**A. Behind the IMU's auxiliary I2C master** (reference, DEC-008). The mag sits on a
private two-wire bus behind its own IMU, so it costs no chain traffic and no extra
channel. Only IMUs whose driver implements the aux master qualify: today the ICM-456xx.
(BMI160/270 and the LSM6DS family have aux masters in hardware; the firmware does not
drive them.) Supported: QMC6309, IST8306, MMC5983MA, LIS3MDL. Each sample costs the host
one aux burst read through the IMU: about 20 SPI register transactions and a wait of
roughly 0.25 ms (estimate) while the IMU runs the I2C read.

**B. On its own SPI channel** (DEC-017). The mag shares the cable's SCK, MOSI and MISO and
takes a **second gated SPI channel** on the node, exactly like a second IMU would. Works
with every SoftFusion IMU, aux master or not. The reference ATtiny412 node has one channel
(§4.1), so this needs a 414-class node or an external-gate node with a second
74LVC1G32. Supported: MMC5983MA, LIS3MDL.

- The mag channel **MUST** be gated like any SPI channel (§4.2). The mag's MISO **MUST**
  be tri-stated whenever its CS is high. Both supported parts are SPI-mode slaves that
  drive SDO only while selected (MMC5983MA datasheet Rev A, SPI timing; LIS3MDL datasheet,
  SPI interface). Confirm on the scope at bring-up.
- The host runs the mag **MSB first, at most 10 MHz** (both parts' limit), and never
  faster than its bus. The SPI mode follows the bus unless the board config overrides it
  (`"mag": {"cs": ..., "clock": ..., "mode": ...}`). Both datasheets specify mode 3, but
  SparkFun reports the MMC5983MA working only in mode 0, so bring it up at ~2 MHz and try
  both. `SPISettings` are applied per transaction, so the IMU keeps its own.
- With the CS high, both parts also listen as I2C slaves on SCK/MOSI (MMC5983MA at `0x30`,
  LIS3MDL at `0x1C`/`0x1E`). IMU traffic would have to form an I2C START and address by
  chance for one to answer. Unlikely, but a reason not to share their SCK with an
  unrelated fast bus.
- Each mag read costs **two** chain arms when the mag and IMU are on different targets
  (one to the mag, and one back to the IMU at its next transaction), plus a 7-byte SPI
  transfer. At 400 kHz that adds ~102 µs per sensor per 5 ms cycle (§14.2).

In both cases the host polls the mag at the IMU driver's `MagTs` (100 Hz on the
ICM-45686, 120 Hz on the LSM6DSO/DSR/DSV), because VQF assumes a fixed period. Samples are
not taken from the IMU FIFO.

**Orientation.** The fusion works in the IMU chip's frame, so the mag's axes must be mapped
into it. Read both chips' axis diagrams and give the mapping as IMU X, Y, Z:
`"mag": {"cs": ..., "axes": "+Y-X+Z"}` means IMU X = +mag Y, IMU Y = −mag X, IMU Z = +mag Z.
The default is `+X+Y+Z`, so a mag laid out parallel to its IMU needs nothing. For a mag
behind the IMU's aux port (A), give `"axes"` without a `cs`. The generator refuses a
mapping that is a mirror image rather than a rotation: both chips are right-handed, so one
means a sign is wrong. Check it at bring-up: rotate the tracker about each IMU axis in
turn, and the field should turn the same way the gyro does.

**Calibration.** There is no hard-iron or soft-iron calibration for SoftFusion mags yet, so
keep them away from the battery, speakers and ferrous parts.

### 4.6 What bypasses the node

SCK, MOSI and MISO **MUST** run from the cable straight to the sensor. The node MCU gates
one signal per channel and nothing else. A hung node can fail to select; it **cannot**
corrupt data.

---

## 5. Addressing

### 5.1 The chain address

- **Every node on a chain listens on one 7-bit address** (v3, DEC-015). Nodes are told
  apart by the target byte inside each frame, not by address.
- Default: **`0x13`** (`DefaultBaseAddress`).
- The chain address **MUST** be one of `AddressWhitelist`:

| Address | Distance to nearest occupied address |
|---:|---|
| **0x13** (default) | 6 |
| 0x12, 0x14 | 5 |
| 0x11, 0x15 | 4 |
| 0x34, 0x35 | 4 |

The whitelist is **derived, not maintained by hand**. `sim/i2c_address_map.py` parses every
sensor driver for the addresses it uses, unions them with parts common on hobbyist buses and
the ranges the I2C specification reserves, and ranks the gaps. Regenerate after adding a
driver. There is no window of 16 consecutive free addresses, which is why v2's
address-per-node scheme had to go. **Avoid `0x30`**: it is the MMC5983MA.

- The host's address and the node's address **MUST** come from the same constant. In the
  reference implementation, `globals.h`, the node firmware and the board generator all read
  `ATTinyCS::DefaultBaseAddress`. Copies of this value diverged once and silently produced
  a chain with no nodes.
- A node build **MAY** override the address (`-DBASE_ADDRESS`) only for a second chain on a
  shared bus (§11), and then **MUST** use a whitelisted address.

### 5.2 Node ids, channels, targets

- `nodeId`: **1..15**. `0` means "no node" and is the defined idle state.
- `channel`: **0..15**.
- Target byte: `(nodeId << 4) | channel`. `packTarget()` / `unpackNodeId()` /
  `unpackChannel()`.
- Node ids are **compiled in**, one image per id (no straps, no jumpers). Ids are **per
  chain**, so any node-1 board is a drop-in spare for any other chain's node 1.
- Capacity: 15 nodes × 16 channels = **240 targets per chain**.

---

## 6. Frames and commands

### 6.1 Frame format

Every write to the chain address is **exactly three bytes**:

```
 byte 0      byte 1               byte 2
 opcode      target               value
             (nodeId<<4)|channel
```

- Hosts **MUST** send exactly three bytes.
- Nodes **MUST** discard any write whose length is not three, without changing state.
- Nodes **MUST** ignore unknown opcodes, without changing state.
- Every node on the chain receives every frame. All nodes ACK at the I2C level (they share
  the address); the ACK says the chain is present, not that a particular node exists.

### 6.2 Command set

**Chain-wide.** Every node acts.

| Opcode | Name | Target | Value | Effect at each node |
|---|---|---|---|---|
| `0x01` | `ARM` | node, channel | ignored | If `nodeId` is mine **and** `channel < NUM_CHANNELS`: arm that channel, disarm my others. Otherwise disarm all of mine. `nodeId = 0` therefore disarms the chain |
| `0x02` | `DISARM_ALL` | ignored | ignored | Disarm all channels |
| `0x03` | `POWER_ALL` | ignored | 0 off, 1 on | Set my sensor supply |
| `0x7F` | `RESET_ALL` | ignored | ignored | Return to power-on state (§8.1), including sensor power off and `answersRead` cleared |

**Addressed.** Only the node whose id matches the target acts; others ignore the frame.

| Opcode | Name | Target | Value | Effect at the matching node |
|---|---|---|---|---|
| `0x10` | `SET_CS` | node, channel | 0 assert (LOW), 1 release | Software-CS fallback. **Only** if armed, on **that** channel, in software mode, and the channel is an SPI channel. Otherwise ignored |
| `0x11` | `SET_MODE` | node | 0 software, 1 strobe | CS mode. Persists until `RESET_ALL` or reset. Power-on default: strobe |
| `0x12` | `SET_SENSOR_POWER` | node | 0 off, 1 on | Drive the pass FET |
| `0x13` | `SET_SENSOR_RESET` | node | 1 hold, 0 release | Hold: supply off, `held in reset` set. Release: supply on. A power cycle is a stronger reset than the sensor's own, at no pin cost |
| `0x20` | `IDENTIFY` | node | ignored | That node answers the next read; **every other node stops answering reads** |

`ARM` is the hot path: one frame, ~95 µs at 400 kHz. Hosts **MUST** skip it when the target
is already armed (§9.3).

---

## 7. Reads and identity

- A read from the chain address is answered by **the node the last `IDENTIFY` selected**,
  and by no other. Because `IDENTIFY` is one-hot like `ARM`, two nodes can never drive SDA
  on a read.
- The answer is the **identity block**, 4 bytes:

| Byte | Field | Value |
|---:|---|---|
| 0 | Magic | `0x5C` (`IdentityMagic`). Distinguishes a node from anything else at the address |
| 1 | Protocol version | `0x03` |
| 2 | Node id | As compiled into this node |
| 3 | Status | bit 0 armed, bit 1 strobe mode, bit 2 sensor powered, bit 3 held in reset |

- A node **MUST** return its compiled-in id in byte 2, **not** an echo of the target. That is
  what makes a mis-flashed node detectable.
- If no node is selected for reads, nodes still ACK the address byte (they share it), and
  the bytes read back are bus idle (`0xFF`). Hosts **MUST** treat a bad magic as "no node"
  (§14.6).

---

## 8. Node behaviour

### 8.1 Power-on state

Before enabling its I2C slave, a node **MUST** be in:

| State | Value |
|---|---|
| Armed | none |
| Every SPI channel's CS | HIGH |
| Every I2C channel's gated SCL | LOW |
| CS mode | strobe |
| Sensor supply | **off** |
| Answers reads | no |

### 8.2 State variables

`armed` (bool), `armedChannel`, `csMode`, `sensorPowered`, `sensorHeldInReset`,
`answersRead`. Status byte bits are derived from these after every frame.

### 8.3 Rules

- **One-hot.** On every `ARM`, a node arms at most one of its channels, and only if the
  frame names it. Any `ARM` naming another node disarms it. Every node sees every `ARM`, so
  there is never a window with two armed.
- **Strobe mode, armed:** the channel's gated signal follows the gating equation (§4.2)
  combinationally.
- **Software mode, armed:** the channel's CS is driven by `SET_CS`; the strobe is ignored
  (on-chip variant) or parked low by the host (external-gate variant). In the external-gate
  variant, arming itself drives ARMED_N active, so CS asserts at `ARM` rather than at the
  first `SET_CS 0`. That is harmless because the host only arms on its way to asserting
  (§9.4), but it means "armed in software mode" is not a neutral state on that variant.
- **Disarmed (either mode):** every channel at its idle level.
- **I2C channels** ignore `SET_CS` and are never driven by the strobe: armed means SCL passes,
  disarmed means SCL held low.
- **Unknown or malformed frames** change nothing (§6.1).

---

## 9. Host behaviour

### 9.1 Bring-up

On `init()`, for each chain, a host **MUST**:

1. Validate the chain address is in the I2C-usable range (`0x08..0x77`). If not, log and
   leave the chain inert, but report the interface as initialised so the failure surfaces
   per sensor (absent), not as a dead bus.
2. Attach the I2C peripheral to the chain's pins. Drive CS_STROBE HIGH if present.
3. `DISARM_ALL`.
4. `POWER_ALL 0`, then wait at least **`SensorPowerOffHoldMicros`** (100 µs). This
   power-cycles any sensor left on by a previous run; the QMC6309 needs its supply below
   0.2 V for a while before it will power-on-reset again.
5. For each id 1..15: `IDENTIFY` that id, read 4 bytes. The node is **present** only if the
   read returns 4 bytes, magic `0x5C`, **and** version equal to the host's. A host **MUST**
   refuse a node reporting another version: log an error and treat its sensor as absent,
   never power or arm it. Log an error if the reported id differs from the probed id.
6. For each present node, in id order: `SET_SENSOR_POWER 1`, then wait
   **`SensorPowerOnSettleMillis`** (15 ms) before the next. One at a time, not a
   broadcast: a shorted sensor becomes attributable to a node id, and inrush is spread over
   milliseconds instead of summed at the end of a metre of thin cable (DEC-014).

Startup cost: 15 ms per present node, once.

### 9.2 Presence

A sensor on a node that did not answer step 5 **MUST** be reported absent (`isPresent() ==
false` / `hasSensorOnBus() == false`), not as a failed interface. A missing node must take
out its own sensors, not the whole chain.

### 9.3 Selecting a target

```
select(node, ch):
    if target == cachedArmed:          return ok         # no bus traffic
    if node != 0:
        disarm every other chain on these I2C pins that may be armed      (§11)
        mayBeArmed = true
    write ARM target
    on NACK:  cachedArmed = 0; log; return fail          # do NOT touch the strobe
    cachedArmed = target
    wait ArmSettleMicros (2 µs)
```

- The host **MUST** cache the armed target and skip `ARM` when it matches. Twenty
  consecutive reads of an armed sensor cost zero I2C traffic.
- On any I2C failure the host **MUST** drop its cached belief (`cachedArmed = 0`) rather
  than assume the write landed.
- The host **MUST** track "may be armed" separately from the cached target. After a failed
  `ARM`, the cache is cleared but the previously armed node may still be armed.

### 9.4 Framing an SPI transaction

- **Assert:** `select()`; if it failed, return **without touching the strobe**, because some
  other node may still be armed and pulsing the shared strobe would assert *its* CS. Then
  drive CS_STROBE LOW.
- **Release:** if the target is not the armed one (typically after a failed `ARM`), drive
  CS_STROBE HIGH and return. Releasing **never** arms. Otherwise drive CS_STROBE HIGH.
- **"Armed" is not "asserted".** Assertion is the arm latch AND the strobe. After a failed
  `ARM` the old node remains armed but not asserted, because the strobe is idle high. Code
  that conflates the two is wrong in exactly this case.
- **Software-CS fallback** (no strobe conductor): send `SET_CS` instead of toggling the
  strobe. ~1000× slower per transaction; bring-up only. On a dropped `SET_CS`, clear the
  cached target so the next attempt starts from scratch.

### 9.5 Talking to a chained I2C sensor

Before every transaction burst, the host **MUST**:

1. **Attach the I2C peripheral to the chain's pins, every time**, even when the target is
   already armed. A local I2C sensor on other pins may have moved it, and `select()`
   skips the bus entirely when nothing needs arming. Skipping this once read a chained
   sensor over the local bus from the second poll cycle on.
2. `select(node, ch)`. **If it fails, `DISARM_ALL`.** Otherwise the previously armed I2C
   sensor stays ungated and answers traffic meant for this one: a plausible, wrong
   reading. Disarmed, the transaction NACKs visibly.
3. Talk to the sensor at its own address as on any I2C bus.

---

## 10. Timing

| Event | Budget | Source |
|---|---|---|
| CS_STROBE → sensor CS, strobe mode | < 100 ns, combinational | §4.2 |
| `ARM` written → gated signal valid | 2 µs | `ArmSettleMicros` |
| One frame on the wire | ~95 µs at 400 kHz (~38 µs at 1 MHz, §14.2) | 4 bytes incl. address |
| Software-CS framed transaction | ~190 µs at 400 kHz | bring-up only |
| Sensor supply off → may be re-enabled | ≥ 100 µs | `SensorPowerOffHoldMicros` |
| Sensor supply on → sensors respond | 15 ms | `SensorPowerOnSettleMillis` (QMC6309 PSUP < 10 ms + PORT < 3 ms, plus margin) |

Worked numbers (wire time only, a lower bound; each is pinned in `sim/check_numbers.py`,
which recomputes it from the constants and fails if it moves):

- 4 sensors at 200 Hz on a 400 kHz chain: 4 arm writes per 5 ms cycle ≈ 380 µs ≈ 7.6 %.
- One ICM-45686 visit reads FIFO_COUNT, then at least one 20-byte packet: 24 bytes with
  the address bytes, 48 µs at 4 MHz.
- 16 sensors at 200 Hz: I2C 1.52 ms + SPI 0.77 ms ≈ 46 % of the cycle. Lower the output
  rate, or split the sensors across hosts; Fast-mode Plus is not available on the reference
  host (§14.2).
- How many sensors fit in a cycle at all: §14.2.

---

## 11. Several chains

A host **MAY** run several chains, on separate pins or sharing one I2C bus.

- Chains on **separate** I2C pins and strobes are independent.
- Chains **sharing** SDA/SCL:
  - **MUST** have distinct whitelisted addresses, and distinct CS_STROBE pins. Every node
    on both chains hears every frame, so an `ARM` meant for one chain would otherwise arm
    the same node id on the other. The reference generator refuses such a configuration,
    because nothing at runtime would show it.
  - The host **MUST** hold one-hot **across** them: before arming any target, disarm every
    other chain on the same pins that may be armed (`disarmOtherChainsOnThisBus`).
    Otherwise a gated I2C sensor on each chain listens at once and two at the same address
    collide. This costs one extra frame whenever consecutive sensors sit on different
    chains of the same bus.
- The whitelist has seven entries, so at most seven chains share one I2C bus. Beyond that,
  use separate pins.

---

## 12. Versioning and extension

- `ProtocolVersion` **MUST** be incremented for any change that alters how an existing
  frame is interpreted. v1 → v2 added the channel nibble; v2 → v3 moved to one address and
  three-byte frames, which is not wire-compatible.
- Hosts refuse other versions (§9.1). A mixed chain therefore fails loudly per node instead
  of misbehaving.
- New commands **SHOULD** keep the three-byte frame and fall in the free part of their
  range:

| Range | Use | Allocated |
|---|---|---|
| `0x01–0x0F` | Chain-wide, every node acts | `0x01–0x03` |
| `0x10–0x1F` | Addressed configuration | `0x10–0x13` |
| `0x20–0x2F` | Addressed, selects read content | `0x20` |
| `0x30–0x6F` | Reserved for future standard use | — |
| `0x70–0x7E` | Experimental; never in a release | — |
| `0x7F` | `RESET_ALL` | fixed |
| `0x80–0xFF` | Reserved | — |

- Old nodes ignore unknown opcodes (§6.1), so adding a command needs no version bump
  unless hosts depend on it. If they do, bump the version.

---

## 13. Conformance

### 13.1 Node

A node implementation conforms when:

| # | Requirement | § | Checked by |
|---|---|---|---|
| N1 | Arms one-hot; never two channels asserted on a chain | 8.3 | `sim/run.sh` (every scenario), `sim/sweep.sh` (all 3¹⁵ topologies) |
| N2 | Honours `SET_CS` only when armed, on that channel, in software mode | 6.2 | sim: software-CS scenarios |
| N3 | Identity block: magic `0x5C`, version 3, its compiled-in id | 7 | sim: mis-flashed node scenario |
| N4 | Only the last `IDENTIFY`-selected node answers reads | 7 | sim: read-collision guard |
| N5 | Sensor supply off at reset, on only by command | 4.3, 8.1 | sim: staged power-up |
| N6 | Gated signal follows the strobe combinationally while armed in strobe mode | 4.2 | hardware: scope at the IMU CS |
| N7 | I2C channels hold SCL low when disarmed | 4.2 | sim: identical I2C sensors; hardware: scope |
| N8 | Discards non-3-byte frames and unknown opcodes | 6.1 | node firmware review; `compile-check.sh` builds every variant |
| N9 | Pin map matches the node firmware's ports | 4.4 | `gen/check_node_pins.py` (hardware repo) |

The simulator's node model is an **independent** implementation of this spec, not the node
firmware. That is what catches a host and a node disagreeing about the wire format. It is
also why it cannot catch the node firmware failing to implement part of the spec: N6–N8
need the firmware and hardware themselves.

### 13.2 Host

| # | Requirement | § | Checked by |
|---|---|---|---|
| H1 | Bring-up order, off-hold, staged power with settle | 9.1 | sim: staged power-up, power-off hold |
| H2 | Refuses other protocol versions | 9.1 | sim: older-protocol node |
| H3 | Skips `ARM` for the armed target | 9.3 | sim: repeat polls are free |
| H4 | Never pulses the strobe after a failed `ARM` | 9.4 | sim: failed arm |
| H5 | Re-attaches the chain's I2C pins on every chained-I2C swap-in | 9.5 | sim: chained beside local I2C |
| H6 | `DISARM_ALL` after a failed `ARM` for an I2C sensor | 9.5 | sim: failed arm with I2C sensors |
| H7 | One-hot across chains sharing a bus | 11 | sim: two chains on one bus |
| H8 | Chain address from the shared constant, whitelisted | 5.1 | `sim/check_board_config.py` |
| H9 | Generated sensor descriptors type-check | — | `sim/check_desc_list.py` |

Run everything with `./VERIFY.sh`; CI runs it on every pull request.

---

## 14. Limits, scaling and open questions

Every figure in §14.1–14.5 is pinned in `sim/check_numbers.py`, which recomputes it from the
protocol constants and declared physical values and fails if it moves. (It does not read
this file: change a figure in both places.) Values marked *estimate* are inputs to measure
at bring-up, not results. Bus times are wire time only, so they are lower bounds: the host
also spends time between bytes.

### 14.1 Hard limits of protocol v3

| Limit | Value | Set by |
|---|---|---|
| Nodes per chain | **15** (ids 1–15; 0 is "no node") | High nibble of the target byte (§5.2) |
| Channels per node | **16** | Low nibble of the target byte. In practice the node MCU's pins: **1** on the reference ATtiny412 (§4.1) |
| Targets per chain | **240** | 15 × 16 |
| Chains sharing one I2C bus | **7** | Entries in `AddressWhitelist` (§5.1, §11) |
| Targets on one I2C bus | **1,680** | 7 × 240 |
| Chains on separate pins | No protocol limit | Host GPIOs: three per chain (SDA, SCL, strobe), fewer if chains share an I2C bus |
| Bring-up time, full chain | **~228 ms**, once at boot | Power staging, 15 × `SensorPowerOnSettleMillis` = 225 ms, plus ~3.2 ms probing ids 1–15 (§9.1) |
| Sensors per tracker (reference firmware) | **16** | The board-config schema; `MAX_SENSORS_COUNT` is generated from the list. A choice, not a protocol limit |

Selection is one-hot (§9.3), so more channels or more nodes add **addresses**, never
**bandwidth**. Every target on a host shares one SPI bus and the host's one I2C peripheral
(§14.3).

### 14.2 What binds first

Long before addressing runs out, one of these does. In rough order:

**1. Bus time.** The host visits every sensor on every loop pass, and each visit to a
chained sensor costs an `ARM` (95 µs at 400 kHz) plus its FIFO read (48 µs at 4 MHz SPI,
§10): **143 µs** per sensor per cycle. At 200 Hz (a 5 ms cycle):

| | 400 kHz (reference) | 1 MHz (Fast-mode Plus) | 100 kHz |
|---|---|---|---|
| Per sensor | 143 µs | 86 µs | 428 µs |
| Sensors that fill the whole cycle | 34 | 58 | — |
| Sensors in half the cycle (leaving time for fusion and Wi-Fi) | **17** | 29 | 5 |

- **The reference host is limited to 400 kHz.** The ESP32-C5's I2C controller does
  Standard and Fast mode only, and the firmware fixes `I2C_SPEED` at 400 kHz for every bus.
  The 1 MHz column needs a Fast-mode-Plus host and nodes, a firmware change, and much
  stronger pull-ups (limit 2).
- **Magnetometers add to this.** An SPI mag on its own node channel (§4.5 B) costs two more
  arms and a 7-byte read every 10 ms, ~102 µs per 5 ms cycle at 400 kHz: 245 µs per
  sensor, so **10** sensors in half the cycle. An aux mag (§4.5 A) costs no chain time but
  ~0.25 ms of host time per sample (estimate).

Halving the output rate doubles these. Raising the SPI clock helps only the 48 µs term.
**A realistic ceiling on the reference host is about 17 sensors at 200 Hz** (10 with SPI
mags), whatever the chain count, since the host's time is shared by all of its chains.

**2. I2C bus capacitance.** Fast mode allows a 300 ns rise time (Fast-mode Plus 120 ns).
With a pull-up `R`, the bus may carry at most `t_r / (0.8473 R)`:

| Pull-up | Fast mode (400 kHz) | Fast-mode Plus (1 MHz) |
|---|---|---|
| 2.2 kΩ (default, §3.1) | ~160 pF | ~64 pF |
| ~970 Ω (strongest Fast-mode pull-up at VOL 0.4 V, 3 mA) | ~365 pF | — |
| ~145 Ω (strongest Fast-mode-Plus pull-up, 20 mA) | — | 550 pF (the spec's cap) |

Each node adds an estimated 15 pF per line (MCU pin, two jacks, traces), the cable ~60 pF/m,
and the host's own pin and traces a little more. So:

- Two nodes on the 2.2 kΩ default leave room for ~2.2 m of cable.
- **15 nodes alone exceed what 2.2 kΩ can drive at 400 kHz.** A full chain needs ~1 kΩ
  pull-ups, and then has room for ~2.35 m of cable.
- At Fast-mode Plus, 2.2 kΩ drives fewer than five nodes and no cable. A full chain plus
  2 m (~345 pF) needs ~410 Ω.
- Past these: 100 kHz (`ARM` 380 µs, about 5 sensors in half a 200 Hz cycle), an active
  I2C buffer, or more, shorter chains.

**3. SPI on cable.** SCK, MOSI, MISO and CS_STROBE run unterminated past every node's stub,
and MISO carries every sensor's tri-stated output pin. Each node lowers the usable clock.
There is no formula worth trusting here: measure the ceiling per build (§3.2).

**4. Supply.** VBUS and GND are one conductor each. On flat 32 AWG cable (§3.3, ~1.08 Ω/m
round trip) a full chain of reference nodes draws ~81 mA and drops **~175 mV** over 2 m.
Allowing 100 mV of sag, 2 m of flat cable carries only **~46 mA**: about **8** reference
nodes. On 26 AWG round cable the same chain drops ~43 mV, and 2 m carries ~187 mA. The
sensors themselves tolerate more sag than 100 mV (check each part's minimum VDD), so this
budget is a choice, not a cliff. For long or full chains, specify the cable or regulate
at the nodes.

**5. Software.** The 16-sensor schema ceiling is easy to raise. The server's behaviour with
more than 16 sensors on one tracker, and the Wi-Fi packet rate that implies, are
untested.

### 14.3 Scaling past one chain

Under v3, with no protocol change:

- **More chains on one I2C bus**, up to seven, each with its own strobe pin and whitelisted
  address (§11). They share I2C time and capacitance, so limits 1 and 2 apply to the bus,
  not the chain.
- **Chains on separate I2C pins**, which also splits the capacitance (limit 2). The
  reference host moves one `Wire` peripheral between pin sets, so these chains still share
  I2C time (limit 1). Running two truly in parallel would need a second I2C peripheral
  (ESP32 and ESP32-S3 have two; the ESP32-C5 has a second, low-power, master-only one) and
  host changes that do not exist yet.
- **Nodes with more channels** (ATtiny414/1614, or external gates). These save boards,
  parts and power at a site, but not time (§14.1).

This is the recommended path. Limit 1 caps a host well below 15 fully used nodes at
200 Hz, so v3's address space is not what stops a build.

### 14.4 Extending the protocol

If a future design needs more than 15 nodes on one chain:

- **The value byte alone is not enough.** `ARM` and `IDENTIFY` ignore their value today,
  so it could carry the high bits of the node id. But the addressed configuration commands
  (`SET_CS`, `SET_MODE`, `SET_SENSOR_POWER`, `SET_SENSOR_RESET`) already use their value
  byte, so the extension would cover arming and identification and nothing else.
- **A four-byte frame** (opcode, node-high, target, value) extends every command: up to
  4,095 nodes × 16 channels. `ARM` grows to ~117.5 µs at 400 kHz, making limit 1 worse for
  every chain.
- **A page register** (a chain-wide `SELECT_PAGE` that each node compares with its own page)
  keeps the three-byte frame. But it makes routing depend on a frame the node might have
  missed. Not recommended.

Any of these changes how existing frames are read, so it needs a version bump (§12).
v3 hosts refuse it, and a mixed chain fails loudly. **Recommendation: do not extend.** Use
§14.3 until a design is limited by addresses rather than by time, which limit 1 makes
unlikely.

### 14.5 Cameras and other high-bandwidth sensors

**Raw video: not supported, and not a goal.**

- **Bandwidth.** The whole chain shares one SPI bus at ~8–12 MHz on cable. A 320×240
  greyscale frame (76.8 KB) then takes the entire bus to move **13–19.5 frames/s for one
  camera**, with nothing left for IMUs. Compression helps proportionally; the bus is still
  shared.
- **Interfaces.** Most image sensors output parallel video (DVP, 8+ data lines plus a pixel
  clock at tens of MHz) or MIPI CSI (differential pairs). Neither fits §2.1.
- **Power.** A small camera module draws an estimated 80 mA. The 100 mV budget in §14.2
  covers **two** such nodes on 2 m of 26 AWG cable, and **none** on flat 32 AWG. A camera
  chain would need a higher VBUS with regulation at each node, which is a change to §3.

**What does fit:**

- **Sensors that report results, not images.** An IR blob tracker of the Pixart PAJ7025
  kind (the PAJ7025R2 has SPI) reports a record per tracked object, up to 16 objects, at up
  to ~200 frames/s. That is far less than video, though several times an IMU's FIFO read:
  size it from the datasheet's report format. If it tri-states MISO when deselected, it is
  an ordinary SPI channel (§4.2).
- **Configuration of identical cameras.** Image sensors are configured over SCCB, which is
  I2C-like with fixed addresses. A gated I2C channel (§4.2, DEC-016) isolates each one, the
  same way chained I2C IMUs are isolated.
- **Frame synchronisation (genlock).** This is where I2SPI is unusually good. CS_STROBE
  reaches every node through combinational gates (< 100 ns, §10) with no CPU in the path,
  so a strobe edge can fire every camera together. Skew is cable propagation (~5 ns/m)
  plus gate spread, far below any exposure time. It needs two additions, **proposed, not
  allocated**:
  1. A chain-wide command in `0x04–0x0F` that arms every node's *trigger* channel at
     once.
  2. An exception to one-hot (§9.3) for output-only trigger channels. This is safe because
     a trigger channel never drives MISO or SDA.

  Old nodes ignore the unknown opcode (§6.1). A version bump is needed only if hosts come
  to depend on it (§12).

### 14.6 Open questions

Verified on hardware: **nothing yet.** Everything above is verified by simulation,
compilation and static checks. Settle these at bring-up:

- **Empty-slot reads.** The sim models a read with no node selected as "no answer". Real
  nodes share the address and ACK it, so the host most likely reads `0xFF` and rejects it
  on magic. That should log one warning per empty id. It is harmless, but confirm and
  consider silencing.
- **Gate at an arm transition mid-transaction.** The host only re-arms between transactions,
  so it should not arise. Scope SCL at the sensor during a switch.
- **Magnetometer reads through AUX1.** Writes were fixed (they were being issued as reads).
  Live reads have never been seen. If a magnetometer enumerates and returns nothing, try
  `I2CM_RESTART_EN = 1` first (`icm45base.h`).
- **SPI clock on cable.** 4 MHz is the conservative start. The usable ceiling for a given
  length is a measurement, not a calculation.
- **Magnetometer calibration.** No hard- or soft-iron calibration yet (§4.5). The axis
  mapping exists but is unproven on hardware.
- **Deliberately unsupported:** hot-plug; runtime node ids; bulk transfer through a node;
  more than one gated signal per channel; any pinout other than §2.1.

---

## 15. Design checklist for new hardware

**Host board**

- [ ] RJ45 pinout exactly as §2.1, straight-through
- [ ] 33–47 Ω series on SCK, MOSI, CS_STROBE at the host
- [ ] Pull-ups on CHAIN_SDA/SCL at the host only: 2.2 kΩ for short chains, stronger (down to
      ~970 Ω) for long or full ones (§14.2)
- [ ] Sensor count and output rate within the bus-time budget (§14.2, limit 1)
- [ ] CS_STROBE on a GPIO that is not a strapping, flash, USB or console pin for the MCU.
      (ESP32-C5: avoid GPIO2/3/7/11–22/25–28; GPIO15 is SPICS1 on PSRAM modules)
- [ ] Local sensors' chip selects never reach the connector
- [ ] Chain address left at default unless a second chain shares the bus
- [ ] Board config passes `VERIFY.sh` (whitelist, reserved pins, descriptor type check)

**Node board**

- [ ] MCU with hardware I2C slave; pin map checked against the vendor symbol
- [ ] Gating per §4.2 (on-chip, or 74LVC1G32 per SPI channel / 74LVC1G08 per I2C channel)
- [ ] P-FET high-side sensor switch with gate pull-up to OFF; local bulk on the gated rail
- [ ] No I2C pull-ups on the node
- [ ] SCK/MOSI/MISO straight from cable to sensor
- [ ] Magnetometer on the IMU's AUX bus or its own gated SPI channel, never the chain I2C (§4.5)
- [ ] Two RJ45 jacks in parallel; 100 nF per supply pin, 10 µF bulk
- [ ] Programming pad; node id label on the silkscreen (ids are compiled in)
- [ ] Node firmware built with the shared protocol header and **no** `-DBASE_ADDRESS`
      unless deliberate

**Bring-up order** (each step proves one thing):

1. Host alone: local sensors, network.
2. One node, 30 cm cable, software-CS mode (no strobe in the board config): proves I2C
   and identity.
3. Same, strobe mode: scope CS at the IMU; the strobe edge should arrive in tens of ns.
4. Raise the SPI clock until detection fails; back off by half.
5. Add nodes one at a time; re-check every earlier node after each.

---

## 16. Reference implementation map

| What | Where |
|---|---|
| Protocol constants (shared) | `src/sensorinterface/ATTinyCSProtocol.h` |
| Host: chain bus, SPI chip select, I2C sensor interface | `src/sensorinterface/ATTinyCSInterface.{h,cpp}` |
| Host: descriptor helpers (`ATTINY_CS*`, `I2SPI_WIRE*`, `SPI_MAG`) | `src/sensors/SensorBuilder.cpp` |
| Host: magnetometer detection, setup, polling (aux and SPI) | `src/sensors/softfusion/magdriver.{h,cpp}`, test `sim/test_magdriver.sh` |
| Host: defaults (`REMOTE_CS_*`) | `src/globals.h` |
| Board config → build flags | `scripts/preprocessor.py`, `board-defaults.json` (`REMOTE_CS`, `cs: {type: attiny}`, I2C `node`), `board-defaults.schema.json` |
| Node firmware (ATtiny412 / external-gate variants) | `extras/attiny-cs-node/` |
| Chain simulation, topology sweep | `sim/run.sh`, `sim/sweep.sh`, `sim/chain_model.*` |
| Address map and whitelist derivation | `sim/i2c_address_map.py` |
| Board/descriptor checks | `sim/check_board_config.py`, `sim/check_desc_list.py`, `sim/check_numbers.py` |
| Boot test in QEMU | `qemu/run.sh` (`chain` scenario) |
| Cable and electrical notes, node MCU survey | `docs/dev/HARDWARE-RJ45-SPI-BUS.md` |
| Example build (5 hubs, 8 nodes) | `docs/dev/EXAMPLE-18POINT-BUILD.md` |
| Hub and node boards, KiCad generator | [SlimeVR-Tracker-ESP-Hardware](https://github.com/HelaFaye/SlimeVR-Tracker-ESP-Hardware) |

**Board config, by example.**

```json
"REMOTE_CS": { "scl": "4", "sda": "5", "strobe": "6" },
"SENSORS": [
  { "protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_0",
    "cs": { "type": "direct", "pin": "0" } },
  { "protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_0",
    "cs": { "type": "attiny", "node": 1 } },
  { "protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_0",
    "cs": { "type": "attiny", "node": 2, "channel": 1 } },
  { "protocol": "I2C", "imu": "IMU_ICM45686", "rotation": "DEG_0",
    "node": 3, "address": 104 },
  { "protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_0",
    "cs":  { "type": "attiny", "node": 4 },
    "mag": { "cs": { "type": "attiny", "node": 4, "channel": 1 }, "axes": "+Y-X+Z" } }
]
```

`"mag"` adds an SPI magnetometer on its own chip select (§4.5 B), fused with that sensor.
Its `cs` takes the same forms as a sensor's, a host pin included. `"axes"` maps the mag's
axes onto the IMU's (§4.5); without a `cs` it maps an aux-port mag.

Omit `strobe` for software-CS bring-up. Omit `baseAddress` to use the default. For several
chains, make `REMOTE_CS` a map of named chains and add `"chain": "<name>"` to each sensor
(or its `cs`).

# I2SPI

**SPI data, I2C selection.** A way to hang many SPI sensors off one off-the-shelf flat
RJ45 cable, using an addressed microcontroller at each sensor to own its chip select.

Version 2 of the wire protocol. This document is the specification; the reasoning behind
each choice is in `dev/DECISIONS.md`, referenced inline as DEC-nnn.

---

## 1. What problem it solves

SPI has no addressing. Every device needs its own chip select line, so *n* sensors need
*n* GPIOs at the host and *n* conductors in the cable. On a body-worn tracker with sensors
a metre apart that fails immediately: an 8-conductor cable runs out after three sensors.

I2SPI keeps the SPI bus for data and adds an I2C control plane for *selection*. One host
GPIO frames every transaction; which sensor that GPIO is talking to is set by an I2C
broadcast. Sensor count is limited by addressing, not by conductors.

**The name is a pun and slightly misleading** — it reads as I²S to most eyes, and it
suggests a merged bus when in fact SPI carries 100% of the sensor data and I2C carries
only the selection. Recorded as DEC-013; say "I2SPI (SPI data, I2C selection)" on first
use and the ambiguity goes away.

---

## 2. Cable and pinout

Off-the-shelf **flat** 8P8C patch cable, straight-through (T568B both ends). Flat cable is
a ribbon: the pairs are not twisted, so treat it as eight parallel single-ended wires with
significant pin-to-pin capacitance and exactly one ground return.

| Pin | T568B colour | Signal | Direction | Notes |
|---:|---|---|---|---|
| 1 | white/orange | **VBUS** (3V3) | hub → nodes | Powers node MCUs; sensor rails are gated locally |
| 2 | orange | **GND** | — | The only return path for all seven signals |
| 3 | white/green | **SPI_SCK** | hub → nodes | 33 Ω series at the hub |
| 4 | blue | **SPI_MOSI** | hub → nodes | 33 Ω series at the hub |
| 5 | white/blue | **SPI_MISO** | nodes → hub | Only the selected sensor drives it |
| 6 | green | **CS_STROBE** | hub → nodes | The armed node mirrors this to its local CS |
| 7 | white/brown | **CHAIN_SDA** | bidirectional | 2.2 kΩ pull-up **at the hub only** |
| 8 | brown | **CHAIN_SCL** | hub → nodes | 2.2 kΩ pull-up **at the hub only** |

Straight-through matters: every node is wired identically and cables are interchangeable.

GND on pin 2 sits between VBUS and SCK, the best available placement for the worst
aggressor given a fixed straight-through assignment. There is no second ground to give.

### 2.1 Why pin 6 is a strobe and not an interrupt

The single most consequential decision in the design (DEC-004).

Almost every IMU this targets — ICM-45686, BMI270, LSM6DSx — requires CS to *rise* between
register transactions; the SPI state machine resets on that edge. So CS cannot be parked
low for a sensor's whole polling burst.

If each CS assert and deassert cost an I2C round trip, the arithmetic is fatal: a 3-byte
I2C write at 400 kHz is ~70 µs, and one FIFO poll is several transactions. The fix is to
make the *frame* free and charge only for *selection*:

- The host writes one short I2C message to arm a node.
- That node routes CS_STROBE straight through to its sensor's CS **in hardware** —
  combinational, tens of nanoseconds, no CPU in the path.
- Every other node forces its CS high.
- The host then frames each transaction by toggling one ordinary GPIO.

I2C traffic therefore scales with **sensor switches**, not **SPI transactions**. Measured
in simulation: a four-sensor poll cycle costs 4 I2C writes total, and twenty consecutive
reads of an already-armed sensor cost zero.

Losing the interrupt line is acceptable because the firmware already treats INT as
optional — `DirectPinInterface` maps pin 255 to `nullptr` and the softfusion drivers
timer-poll the FIFO. What is lost is INT-driven wake, which costs power, not correctness.

---

## 3. Addressing

Every node listens on two 7-bit addresses:

| Address | Purpose |
|---|---|
| `0x30` (`BaseAddress`) | Shared. All nodes listen. One-hot arm. |
| `0x30 + nodeId` | Unicast. Identify, configuration, software-CS fallback. |

`nodeId` is `1..15`; `0` means "nothing armed" and is the defined idle state. Default
unicast range `0x31..0x3F` sits clear of common IMU addresses (`0x4A/0x4B`, `0x68/0x69`)
and of the `0x20` MCP23x17 block, so a chain can share a bus with local I2C sensors.
`AddressMin = 0x08` and `AddressMax = 0x77` bound the usable range; the host validates that
`base` through `base + 15` fits inside it and refuses to transact otherwise.

A node may own up to 16 chip selects, addressed by **channel** `0..15`. Node id and channel
are packed into one byte: `(nodeId << 4) | channel`.

> Channels reduce **node count**, not bus traffic. Five nodes with three channels each
> costs exactly the same fifteen arm writes per cycle as fifteen single-channel nodes. The
> saving is board area, parts and power.

---

## 4. Commands

All commands are a one-byte opcode, optionally followed by one payload byte.

**The two opcode spaces are deliberately disjoint.** Arduino TWI slave drivers on the
ATtiny cores do not report *which* of a node's two addresses matched, so the node cannot
distinguish a chain write from a unicast write by address. Disjoint opcodes make the
address irrelevant to decoding. Keep them disjoint when extending the protocol.

### 4.1 Chain address (`0x30`)

| Opcode | Payload | Meaning |
|---|---|---|
| `0x01` `ARM` | `(nodeId << 4) \| channel` | The matching node arms that channel. Every other node, and every other channel on that node, disarms. `nodeId = 0` disarms all. |
| `0x02` `DISARM_ALL` | — | Equivalent to `ARM 0`. |
| `0x03` `POWER_ALL` | `0` off, `1` on | Every node gates its sensor supply at once. |
| `0x7F` `RESET_ALL` | — | Back to power-on state: disarmed, CS high, sensors unpowered. |

`ARM` is the hot path: 3 bytes on the wire, ~70 µs at 400 kHz, ~30 µs at 1 MHz, issued
once per sensor switch. The host skips it entirely when the requested target is already
armed.

**One-hot is by construction, not by convention.** Every node sees the same broadcast, so
there is no window in which two are armed. That is a safety property: two nodes asserting
CS means two IMUs driving MISO, which is a bus fight rather than a glitch and is close to
invisible on a scope.

### 4.2 Unicast address (`0x30 + nodeId`)

| Opcode | Payload | Meaning |
|---|---|---|
| `0x10` `SET_CS` | `(channel << 4) \| level` | Software-CS fallback. Only honoured while armed **on that channel**, so a stale command cannot pull a chip select out from under the host. |
| `0x11` `SET_MODE` | `0` software, `1` strobe | Persists until reset. Power-on default is strobe. |
| `0x12` `SET_SENSOR_POWER` | `0` off, `1` on | Drives the VCC pass MOSFET. |
| `0x13` `SET_SENSOR_RESET` | `0` release, `1` hold | Cuts the rail — a power cycle is a stronger reset than the sensor's own and costs no extra pin. |
| `0x20` `IDENTIFY` | — | Next read returns the identity block. |

### 4.3 Reads

A read from a unicast address returns four bytes:

| Byte | Meaning |
|---:|---|
| 0 | Magic `0x5C` — distinguishes a node from whatever else answers at that address |
| 1 | Protocol version, currently `0x02` |
| 2 | `nodeId` as the node believes it to be |
| 3 | Status: bit0 armed, bit1 strobe mode, bit2 sensor powered, bit3 held in reset |

Byte 2 exists to catch the failure that otherwise costs an afternoon: a node flashed with
the wrong `-DNODE_ID`. The host logs an error when a node answering at one address reports
a different id.

A v1 node ignores the channel nibble and still works as a single-channel node, so v2 is
backward compatible in the direction that matters. The host warns when it probes one.

---

## 5. Power sequencing

Each node switches its sensor's 3V3 through a **P-channel high-side pass MOSFET** driven by
the node MCU. Sensors power up **off**.

The polarity is chosen so the failure mode is de-energised: gate high turns the FET off,
and a 100 kΩ pull-up holds the gate high whenever the MCU is not actively driving it —
unprogrammed, held in reset, or simply not yet at `setup()`. An unpowered IMU cannot drive
MISO and cannot fight the bus, so a node that fails to boot degrades to "sensor absent"
rather than to a conflict that takes down its neighbours.

Low-side switching would be one cheaper part and is wrong here: it leaves the sensor's
ground floating while its I/O pins are still tied to a live bus, back-powering the part
through its ESD diodes.

**Bring-up sequence** (`ATTinyCSBus::init()`):

1. `POWER_ALL 0` — belt and braces in case a previous run left a node powered.
2. `DISARM_ALL`.
3. Probe `IDENTIFY` at each of the 15 possible unicast addresses; record which answered.
4. For each present node, in id order: `SET_SENSOR_POWER 1`, then wait
   `SensorPowerOnSettleMillis` (10 ms).

Staging one at a time rather than broadcasting is deliberate (DEC-014). A shorted or
mis-soldered sensor becomes attributable to a node id instead of browning out the rail
anonymously, and inrush is spread over milliseconds instead of summed — which at the far
end of a metre of thin cable is the difference between a droop and a brownout.

Cost: 10 ms per sensor at startup, once. 80 ms for an eight-extension build.

---

## 6. Host state machine

```
                     ┌───────────────┐
   startup ─────────▶│ power off all │
                     │ disarm all    │
                     │ enumerate     │
                     │ stage power   │
                     └───────┬───────┘
                             │
                     ┌───────▼────────┐  target == armed
   select(node, ch) ─▶│ already armed? ├────────────────────▶ no bus traffic
                     └───────┬────────┘
                             │ different
                     ┌───────▼────────┐   ok     ┌──────────────────┐
                     │ write ARM      ├─────────▶│ armed = target   │
                     └───────┬────────┘          │ wait 2 µs        │
                             │ NACK              └──────────────────┘
                     ┌───────▼──────────────────────────┐
                     │ armed = none; log; DO NOT touch  │
                     │ the strobe - another node may    │
                     │ still be armed and would assert  │
                     └──────────────────────────────────┘
```

Two behaviours worth internalising:

**A failed arm must not pulse the strobe.** Some other node may still be armed, and
pulsing the shared strobe would assert *its* chip select.

**"Armed" and "asserted" are not the same thing.** Assertion is the arm latch AND the
strobe. After a failed arm the previously armed node remains armed — the chain never saw
the write — but its CS is not asserted because the strobe is idle high. Code that conflates
the two is wrong in exactly this case.

**Releasing a chip select never arms.** If the target is not the armed one, the host drives
the strobe to idle and returns rather than spending an I2C write to reach a state it is
immediately leaving.

---

## 7. Timing

| Event | Budget |
|---|---|
| `CS_STROBE` → sensor CS, strobe mode | < 100 ns, combinational |
| `ARM` → CS valid | 2 µs (`ArmSettleMicros`) |
| `ARM` on the wire | ~70 µs at 400 kHz, ~30 µs at 1 MHz |
| Software-CS assert or deassert | ~60 µs at 400 kHz — bring-up only |
| Sensor power-on → responsive | 10 ms (`SensorPowerOnSettleMillis`) |

Worked example, four sensors at 200 Hz on a 400 kHz chain: 4 arm writes per 5 ms cycle
≈ 280 µs ≈ 5.6% of the budget. Sixteen sensors at 200 Hz is ~37% and wants Fast-mode Plus,
a lower sensor ODR, or both.

---

## 8. Electrical limits

**Clock.** The `24'000'000` in older board defaults is a PCB-trace number. Start at
**4 MHz** on cable, prove the chain end to end, then walk it up. Expect 8–12 MHz for ~1 m,
falling off quickly beyond.

**Series termination.** 33–47 Ω in series with SCK, MOSI and CS_STROBE **at the hub**
(source termination). Single highest-value signal-integrity measure on ribbon cable, three
resistors.

**Pull-ups.** 2.2 kΩ at the hub only. Six nodes at 4.7 kΩ each parallel down to 780 Ω,
below what many parts can pull low. Cable capacitance is the other half: flat cable runs
~50–70 pF/m per conductor against I2C's 400 pF budget, so beyond ~2 m drop to 100 kHz or
add an active terminator.

**Current.** ~6 mA per node (sensor + mag + MCU). 26 AWG at ~0.14 Ω/m over 0.85 m at 12 mA
is ~1.4 mV of drop — negligible, and stays that way unless nodes gain LEDs.

**Topology.** Daisy chain, two jacks per node wired pin-for-pin in parallel, so a
mid-chain node is a zero-length stub. No end terminator: the reflection is tolerable at
these rates and a parallel terminator costs standing current a battery tracker does not
have.

**No hot-plug.** Powering a node while the bus is live can latch up the sensor through its
I/O pins. Power the hub down to re-cable.

---

## 9. Node requirements

**Must have:** a *hardware* I2C slave peripheral. A bit-banged slave caps near 100 kHz and
puts the chain permanently in the bring-up performance tier.

**Must have:** three free I/O with an external gate (SDA, SCL, ARMED_N), four with on-chip
gating (add CS_STROBE in).

**The combinational path can come from either** on-chip logic (ATtiny CCL, PIC CLC) or one
74LVC1G32 wired `CS = CS_STROBE OR ARMED_N`, built with `-DEXTERNAL_CS_GATE`. Identical
timing, identical protocol; the host cannot tell them apart (DEC-010). Software-CS mode
degenerates correctly with the gate fitted: park the strobe low and `CS == ARMED_N`.

**Reference node:** ATtiny412, SOIC-8. The pin map is not a free choice. On an 8-pin
tinyAVR, PA4 and PA5 do not exist, so `LUT0-OUT` (PA4) is unavailable and **PA7 carries
`LUT1-OUT`** — the firmware therefore uses `Logic1`, not `Logic0`. LUT1's direct pin
inputs are on PORTC, which an 8-pin package does not have, so the strobe reaches the LUT
through the event system from PA6. TWI has no alternate pin position on 8-pin parts, so
SDA/SCL are fixed at PA1/PA2. (ATtiny212/412 datasheet DS40001911B, Table 5-1.)

| ATtiny412 | Signal |
|---|---|
| PA0 | UPDI |
| PA1 | CHAIN_SDA (cable pin 7) |
| PA2 | CHAIN_SCL (cable pin 8) |
| PA3 | Sensor power gate |
| PA6 | CS_STROBE in (cable pin 6) |
| PA7 | CS out, to the sensor |

**Not viable:** ATtiny4/5/9/10 — no serial peripheral of any kind, so I2C would be
bit-banged in 1 KB of flash and 32 bytes of SRAM. ATtiny85 works only with the external
gate (USI, no CCL). Alternatives with on-chip logic: PIC16F18313/18323, which additionally
have PPS so the gated output routes to any pin.

`SCK`, `MOSI` and `MISO` **bypass the node MCU entirely**, running from cable to sensor. A
hung node can fail to select; it cannot corrupt data.

---

## 10. Magnetometers

A magnetometer at a node connects to that node's IMU **AUX1 I2C master**, not to the chain.
The QMC6309 has a fixed device id (`0x7c`) with no address strap, so several on one bus
would collide; on AUX1 each sits on a private bus behind its own IMU. `startAuxPolling`
puts its samples into the IMU FIFO, so a magnetometer adds **zero** SPI transactions and
**zero** chain traffic (DEC-008).

---

## 11. Conformance

A node implementation is conformant when, against `sim/`:

- it arms one-hot and never leaves two chip selects asserted;
- it honours `SET_CS` only for the armed channel;
- it returns the identity block with magic `0x5C` and its own compiled-in id;
- it powers its sensor off at reset and only on command;
- its CS follows CS_STROBE combinationally while armed in strobe mode.

`sim/run.sh` models a node independently of the node firmware precisely so a wire-format
disagreement between host and node shows up there rather than on a bench. That is the
failure that has cost the most time on this project.

# Hardware: SPI sensor chain over flat RJ45 cable

## Cable

Off-the-shelf **flat** 8P8C patch cable, straight-through (T568B both ends). Flat cable is
a ribbon — the pairs are not twisted, so treat it as eight parallel single-ended wires
with a lot of pin-to-pin capacitance and exactly one ground return. That is the
constraint everything below follows from.

Straight-through matters: every node is wired identically and cables can be swapped
without thinking about crossover.

## Pinout

| RJ45 pin | T568B colour | Signal | Direction | Notes |
|---|---|---|---|---|
| 1 | white/orange | **3V3** | hub → nodes | See current budget below |
| 2 | orange | **GND** | — | Only return path for all signals |
| 3 | white/green | **SCK** | hub → nodes | Series resistor at hub, see below |
| 4 | blue | **MOSI** | hub → nodes | |
| 5 | white/blue | **MISO** | nodes → hub | Only the armed node drives it |
| 6 | green | **CS_STROBE** | hub → nodes | Armed node mirrors this to its local CS |
| 7 | white/brown | **SDA** | bidirectional | I2C, pull-up at hub only |
| 8 | brown | **SCL** | hub → nodes | I2C, pull-up at hub only |

GND on pin 2 sits between 3V3 and SCK, which is the best available placement for the
worst aggressor given a straight-through flat cable. There is no second ground to give.

**Why no INT line:** see DEC-004 in `DECISIONS.md`. Short version — an interrupt wire
would cost an I2C round trip per SPI transaction to frame CS, and this firmware polls the
IMU FIFO anyway.

## Node board, minimum parts

- ATtiny with CCL and TWI slave — ATtiny412 (8-pin) is the reference; ATtiny402/1616 also
  fine.
- *Or*, on any MCU with a hardware I2C slave but no CCL (ATtiny85 and friends), a
  74LVC1G32 OR gate in SOT-353 wired `CS = CS_STROBE OR ARMED_N`, with the node driving
  `ARMED_N`. Build the node firmware with `-DEXTERNAL_CS_GATE`. Same timing, same
  protocol, one extra part. See DEC-010.
- Either way the MCU needs a **hardware** I2C slave. A bit-banged slave (the only option
  on an ATtiny10, which has no serial peripheral at all) tops out around 100 kHz and puts
  the chain in the bring-up-only performance tier.
- Two RJ45 jacks wired pin-for-pin in parallel (in and out) for daisy chaining.
- The IMU (ICM-45686 on the reference node).
- Optionally a magnetometer (QMC6309 on the reference node) wired to the **IMU's AUX1
  pins**, not to the chain I2C. See DEC-008: this keeps every mag on its own private bus
  behind its own IMU, so their fixed `0x7c` device id can't collide, and the samples
  arrive in the IMU's FIFO at no extra bus cost.
- 100 nF close to every supply pin, plus 10 µF bulk per node.
- UPDI pad for flashing the ATtiny.

### Node MCU candidates

What the node actually has to do is small: answer I2C, and hold one pin. The hard
requirements are therefore short.

**Must have:** a *hardware* I2C slave peripheral. A bit-banged slave tops out around
100 kHz and drops the chain into the bring-up-only performance tier permanently.

**Must have:** three free I/O with the external gate (SDA, SCL, ARMED_N), or four with
on-chip gating (add CS_STROBE in).

**Nice to have:** on-chip combinational logic (CCL / CLC), which saves the gate. And two
own-addresses, which the protocol uses today — though see the single-address note below.

| Part | Package | On-chip gating | Two addresses | Toolchain | Notes |
|---|---|---|---|---|---|
| **ATtiny412 / 402 / 212 / 202** | SOIC-8, UDFN-8 | CCL | yes | megaTinyCore, UPDI | The reference. Only PA7 works as a CCL output on 8 pins, so the pin map is fixed |
| ATtiny414 / 814 / 1614 | SOIC-14 | CCL | yes | megaTinyCore, UPDI | Same, with pins to spare for sensor power/reset |
| PIC16F18313 / 18323 | 8/14-pin | CLC | yes (MSSP) | MPLAB X + XC8, ICSP | Has **PPS**, so the CLC output routes to *any* pin — no fixed pin map. Cost is a second toolchain in the project |
| CH32V003 (J4M6 / F4P6) | SOP-8, TSSOP-20 | no — use the gate | via software filtering | PlatformIO (WCH platform), SWIO | Very cheap RISC-V. Vendor SDK has I2C slave examples; the Arduino core's `Wire` slave support has been patchy, so budget time |
| STM32C011F | SO8N, TSSOP-20 | no — use the gate | yes (OA1 + OA2, native) | STM32Cube / PlatformIO, SWD | The I2C peripheral has two own-address registers, which maps onto our scheme exactly |
| PY32F002A | SOP-8, TSSOP-20 | no — use the gate | check the part | vendor SDK | Cheapest of the lot by some way. Also the least mature tooling and the thinnest English documentation |

**Not viable:** ATtiny4/5/9/10 — no serial peripheral at all (DEC-009, DEC-010).
ATtiny85 works only with the external gate, since it has USI but no CCL.

**The no-MCU option.** With the gate fitted, the node's entire job is "listen on I2C,
drive one pin" — which is what a PCF8574 or TCA9534 does, with the address set by strap
resistors and no firmware at all. It is genuinely tempting, and it costs two things worth
weighing: the one-hot broadcast arm (DEC-007) becomes two writes per sensor switch with a
window where two nodes can be armed at once, and the identity block goes away, so a
mis-strapped node is silent instead of self-reporting. Those two properties are most of
what the MCU is buying.

**Single-address protocol option.** The two-address scheme is a convenience, not a
necessity. Every write already carries a node id in its payload, and because arming is
one-hot, a read from the shared address could be answered by the armed node alone. A v2
protocol on one address would drop the dual-address requirement entirely and open the
list to any part with a plain I2C slave. Not done — v1 works and dual-address parts are
easy to find — but it is the first thing to reach for if part availability bites.

### ATtiny pin assignment (ATtiny412 reference)

| ATtiny pin | Function |
|---|---|
| PA6 | `CS_STROBE` in (from cable pin 6) |
| PA7 | `CS` out (to IMU) — CCL LUT output |
| PA1 | SDA |
| PA2 | SCL |
| PA3 | Gate of the sensor VCC pass MOSFET |
| PA0 | UPDI |

CCL **LUT1** (not LUT0: PA4/PA5 are absent on an 8-pin package, so `LUT0-OUT` cannot be
routed out) is configured as a pass-through of `CS_STROBE` to `CS`. When the node is not
armed, the LUT is disabled and `CS` is driven high by the port. When armed, the LUT is
enabled and the strobe reaches the IMU with combinational delay only — tens of
nanoseconds, not the microseconds an interrupt handler would cost.

SCK / MOSI / MISO **bypass the ATtiny entirely** and go straight from the cable to the
IMU. The ATtiny is not in the SPI data path; it only gates CS. This keeps the data path
as fast as the cable allows and means a hung ATtiny cannot corrupt SPI data — it can only
fail to select.

## Electrical limits

**Clock rate.** The `24'000'000` in the existing board defaults is a *PCB trace* number.
Do not use it on a metre of flat cable. Start at **4 MHz**, prove the chain works end to
end, then walk it up. Expect somewhere in the 8–12 MHz region for ~1 m and to fall off
quickly beyond that. The default in the generated config for `attiny` chip selects is
deliberately conservative.

**Series termination.** 33–47 Ω in series with SCK, MOSI and CS_STROBE at the *hub* end
(source termination). This is the single highest-value change for signal integrity on
ribbon cable and costs three resistors.

**I2C pull-ups.** 2.2 kΩ at the hub only. Do not put pull-ups on every node — six nodes
with 4.7 k each is 780 Ω of parallel pull-up, which most parts cannot pull low properly.
Cable capacitance is the other half of the problem: I2C's 400 pF budget is real, and flat
cable runs roughly 50–70 pF/m per conductor. Beyond about 2 m total chain length, drop to
100 kHz I2C or add an active terminator.

**Current budget.** 26 AWG is 0.1339 Ω/m, and the current traverses **two** conductors —
out on VBUS and back on GND — so budget 0.27 Ω/m round trip. Six nodes at ~4 mA each
(0.42 mA IMU + ~0.5 mA mag + ~3 mA ATtiny) is 24 mA, giving ~6.4 mV/m. Negligible. It stops
being negligible if nodes get LEDs or the chain gets long; regulate locally at the node if
you add anything hungry.

**Hot-plug.** Not supported. Powering a node while the bus is live can latch up the IMU
through its I/O pins. Power the hub down to re-cable.

## Topology

Daisy chain (each node has in and out jacks), not a star. A star from the hub would need
one jack per node at the hub, which is exactly the fan-out problem this design exists to
avoid. Electrically the chain is a multi-drop bus with all stubs of zero length, which is
the best case available.

Chain end: no terminator. At these rates and lengths the reflection is tolerable, and the
alternative — a parallel terminator — costs standing current the tracker's battery does
not have.

## Bring-up order

1. One node, 30 cm cable, 1 MHz SPI, software-CS mode. Confirm the IMU is detected.
2. Same node, strobe mode. Confirm detection still works, confirm the CS waveform at the
   IMU with a scope: the strobe edge should reach CS in tens of ns.
3. Walk the clock up until detection fails, then back off by half.
4. Add nodes one at a time; check every previously-working node after each addition.

# Decision log

Short ADR-style records. Each one states the decision, why it was taken, what was
rejected, and what would make us revisit it.

---

## DEC-001 — Use the pioarduino platform fork for ESP32-C5, not `espressif32 @ 6.7.0`

**Decision.** The `BOARD_ESP32C5_DEVKITC1` env uses
`https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip`
with `board = esp32-c5-devkitc-1`.

**Why.** The C5 needs Arduino-ESP32 3.3.x / ESP-IDF 5.5.x. Official
`platformio/platform-espressif32` has historically lagged badly on new SoCs, and 6.7.0 —
which the rest of this repo pins for C3/S3 — is IDF 5.1 era and has no C5 target at all.
The repo already reaches outside the official platform for the C6 boards (it pins a
Tasmota `platform-espressif32` zip), so "use a community platform for a new SoC" is an
established pattern here rather than a new one.

**Rejected.** Pinning `platform_packages` overrides onto `espressif32 @ 6.7.0` the way
the C3 envs do. That works when the *toolchain* already supports the target and only the
Arduino core needs bumping; for C5 the toolchain, the IDF, and the bootloader all move,
so package pinning turns into a losing game.

**Revisit when.** Official `platform-espressif32` ships a C5 target, or the C6 envs get
migrated — at which point all the non-8266 envs should be unified rather than each board
carrying its own platform URL.

---

## DEC-002 — Do not expose 5 GHz Wi-Fi yet

**Decision.** C5 support lands as a 2.4 GHz tracker. No band selection, no config flag.

**Why.** The whole point of the C5 for SlimeVR is 5 GHz — a body full of trackers is
exactly the congested-2.4 GHz case that hurts. But band selection is not a board-support
change, it is a `wifihandler` + provisioning + server-discovery change:

- `wifiprovisioning` and the credential path assume one band.
- Server discovery is UDP broadcast on the local subnet; a 5 GHz-only tracker on a
  dual-band AP that bridges bands is fine, one that lands on a separate SSID is not.
- Roaming/scan behaviour (`feat/wifiscan_channel` branch upstream) is in flux.

Shipping "the board boots and connects like every other board" first keeps the change
reviewable and means a C5 tracker is useful immediately.

**Revisit when.** Phase 1 is bench-verified. Then 5 GHz gets its own plan, ideally
coordinated with whatever upstream does about channel selection.

**Amendment (2026-09-02).** "Do nothing" turned out not to be an option. Arduino-ESP32
defaults the C5 to `WIFI_BAND_MODE_AUTO`, which faults when the radio starts, so the band
has to be chosen explicitly before the first `WiFi.begin()` whichever band you want.
`WIFI_TRACKER_BAND_MODE` now does that in `WiFiNetwork::setUp()`, between `WiFi.mode()`
and the first connect attempt, defaulting to `WIFI_BAND_MODE_2G_ONLY`.

The decision itself stands: the default is 2.4 GHz and 5 GHz is a build-flag override, not
a supported configuration, until server discovery is verified on it. Discovery is a UDP
broadcast on the local subnet, so a 5 GHz-only tracker on an AP that puts 5 GHz on a
separate SSID will associate happily and never find the server. That is a bad failure to
ship by default.

---

## DEC-003 — ATtiny per sensor node, not a shift register or an I2C GPIO expander

**Decision.** Follow the requested topology: one ATtiny per remote sensor, each with a
unique I2C address, owning that sensor's `CS`.

**Why this beats the alternatives**, given the 8-conductor budget:

| Option | Wires needed | Verdict |
|---|---|---|
| One host GPIO per CS | 5 + N | Fails at N=4 on one RJ45; defeats the purpose |
| 74HC595 chain at each node | 5 + 2 (data, latch; clock shared with SPI) | Works, but the chain is positional — cutting a cable renumbers every node downstream, and a node can't identify itself |
| One central MCP23X17 at the hub | 5 + 2 | Wires still fan out from the hub to each sensor; doesn't survive the cable topology |
| **ATtiny per node, I2C addressed** | **5 + 2 + 1** | Node identity is in the node's own firmware, order-independent, and the node has spare logic for CS strobe gating, sensor power, and identification |

The decisive property is **addressability**. A shift register's position in the chain
*is* its identity, so the physical build order becomes part of the configuration. An
addressed node knows what it is, which means a sensor can be moved to a different port,
a chain can be built in any order, and the firmware config refers to "elbow node" rather
than "third device from the hub".

Secondary wins: the ATtiny can hold the sensor in reset while the host boots, can gate
sensor power, and can answer an identify/version query — all of which matter for a build
where the sensors are metres away inside a suit.

**Cost accepted.** One more part per node, and a second firmware image to maintain and
flash (UPDI, one wire, cheap). Documented in `ATTINY-CS-PROTOCOL.md`.

**Revisit when.** If nodes end up needing enough smarts to poll the IMU themselves, the
right answer stops being "an ATtiny that pulls CS" and becomes "a proper sensor node with
its own MCU speaking a packet protocol" — a much bigger change.

---

## DEC-004 — Spend the 8th conductor on a CS strobe, not on INT

**Decision.** The RJ45 pinout is: 3V3, GND, SCK, MOSI, MISO, SDA, SCL, **CS_STROBE**.
No interrupt line reaches the remote nodes.

**Why.** This is the single most consequential decision in the design, so the reasoning
in full:

Almost every IMU this firmware supports (ICM-45686, BMI270, LSM6DSx) requires `CS` to
rise between register transactions — the SPI state machine resets on the rising edge.
So CS cannot simply be parked low for the duration of a sensor's polling burst.

If CS assert/deassert each cost an I2C round trip, the arithmetic is fatal. A 2-byte I2C
write at 400 kHz is roughly 60 µs. A single FIFO poll is several register transactions;
at 6 sensors × a few hundred polls/second you are spending more time toggling CS than
reading sensors.

The fix is to make the *frame* free and only the *selection* cost I2C:

- The host writes one short I2C message to select a node ("you are armed").
- The armed node routes the shared `CS_STROBE` conductor straight through to its local
  `CS` pin in hardware (ATtiny CCL — combinational, nanoseconds, no CPU involvement).
- Every other node holds its `CS` high.
- The host then frames each SPI transaction by toggling one ordinary GPIO, exactly as
  it would for a locally-wired sensor.

I2C traffic therefore scales with *sensor switches* (a handful per polling cycle), not
with *SPI transactions* (hundreds).

Losing INT is acceptable because this firmware already treats it as optional: the
`DirectPinInterface` validator maps pin 255 to `nullptr`, and the softfusion drivers
timer-poll the FIFO rather than waiting on an edge. Trackers built this way lose the
INT-driven wake path, which matters for power, not correctness.

**Rejected.**
- *Shared open-drain INT, wired-OR, poll all sensors on any edge.* Costs the strobe wire,
  and with several sensors at a few hundred Hz the line is essentially always asserted,
  so it degenerates into polling anyway — with an extra wire spent.
- *ATtiny reports data-ready over I2C.* Adds an I2C round trip per poll, i.e. the exact
  cost we just designed away.
- *9th conductor.* Not off-the-shelf. The requirement is stock flat patch cable.

**Fallback that stays supported.** `ATTinyCSPinInterface` also implements a pure-software
mode where assert/deassert are I2C writes and no strobe conductor is needed. It is much
slower and is intended for bring-up and for hand-wired nodes without CCL, not for a
finished tracker. Selected per-node in the board config.

**Revisit when.** Bench measurement shows the strobe doesn't survive the cable at useful
clock rates, or a use case appears where INT-driven wake matters more than rate.

---

## DEC-005 — Fix the SPI interface cache to hold a pointer, not a reference to a cache key

**Decision.** `DirectSPIInterface` takes `SPIClass*`; the manager caches on
`(busIndex, SPISettings, sck, miso, mosi)`.

**Why.** The existing code is:

```cpp
SensorInterface<DirectSPIInterface, SPIClass, SPISettings> directSPIInterfaces;
// ... get(Args... args) takes args BY VALUE, then does new InterfaceClass(args...)
```

`DirectSPIInterface` stores `SPIClass& m_spiClass`. That reference binds to `get()`'s
by-value parameter, which is destroyed when `get()` returns. Every subsequent use is a
dangling reference. It happens to work today because `SPIClass` copies are shallow and
the copy's internals still point at the one real peripheral — but it is undefined
behaviour that will bite the moment a core changes `SPIClass`'s layout or adds a
non-trivial destructor.

It also makes the cache key wrong in a way that matters now: `operator<(const SPIClass&)`
does a byte-compare over the object's representation, which includes mutable driver
state, so two lookups for the same bus can miss the cache and construct duplicate
interfaces that both call `begin()`.

Since Phase 2 has to touch this constructor anyway to add pins, fixing it here is nearly
free and removes the `operator<(const SPIClass&)` overload entirely.

**Note.** `byteCompare` also has a real bug — it returns `false` on the first byte that
isn't less-than, instead of continuing while bytes are equal, so it is not a strict weak
ordering. The `SPISettings` overload still uses it. Left alone for now because fixing it
changes cache behaviour for existing boards; filed as a follow-up in `PROGRESS.md`.

---

## DEC-006 — Keep `DIRECT_SPI(...)` working unchanged

**Decision.** `DIRECT_SPI(clock, bitOrder, mode)` stays and means "the default SPI bus on
its default pins". The new `SPI_BUS(clock, bitOrder, mode, sck, miso, mosi)` is additive.

**Why.** `BOARD_SLIMEVR_V1_2` — a shipped product — uses `DIRECT_SPI` in
`boards_default.h`, and `board-defaults.json` generates it for every `"protocol": "SPI"`
sensor. Changing the macro's arity would mean touching a shipping board's config in the
same change that introduces a new SoC and a new bus topology. Keeping the old spelling
means the C5/RJ45 work can be reviewed and reverted independently of the ESP8266 boards.

---

## DEC-007 — Node selection is a broadcast one-hot write, not per-node select/deselect

**Decision.** Selecting node *N* is a single write to a shared "chain" address carrying
*N* as payload. Every node sees it; the match arms itself, all others disarm. There is no
explicit deselect.

**Why.** Two I2C transactions per sensor switch becomes one, and — more importantly —
there is no window in which two nodes are armed at once, which is what you get if a
deselect is dropped due to a bus error. One-hot-by-construction is a safety property, not
just an optimisation: two nodes driving `CS` low simultaneously means two IMUs driving
`MISO`, which is a bus fight.

Node id `0` is reserved to mean "no node armed", so a defined idle state exists.

**Why not I2C general call (address 0x00).** General call is technically the right
primitive, but Arduino `Wire` slave support for general call on the ATtiny cores is
inconsistent, and general call collides with the reset/programming semantics some devices
attach to it. A normal 7-bit address that every node listens to alongside its own unicast
address is boring and portable. Unicast addresses remain for identify/diagnostics.

**Revisit when.** A chain needs more than 127 nodes (it will not).

---

## DEC-008 — The magnetometer rides the IMU's AUX1 bus, not the chain

**Decision.** A QMC6309 at each node connects to that node's ICM-45686 AUX1 pins, not to
the chain's SDA/SCL. No change to the cable, the connector, or the ATtiny.

**Why.** The alternative — hanging every mag off the shared chain I2C — breaks
immediately: the QMC6309 answers at a fixed device id (`0x7c`) with no address strap, so
six of them on one bus is six devices at one address. Fixing that would mean gating each
node's mag SCL through the ATtiny (a second CCL LUT or an external AND gate, plus a pin),
which is real cost for no benefit.

The ICM-456xx family is a dual-interface part: the host talks to it on UI (our SPI), and
it runs its own I2C master (I2CM) on AUX1 for an external sensor. Each mag therefore sits
on a private two-wire bus behind its own IMU, and address collisions cannot happen no
matter how many nodes are on the chain.

The performance argument is stronger still. `startAuxPolling` puts the mag's samples into
the IMU's FIFO as ES0 data, so the host reads accel, gyro and mag in the same FIFO burst
it was already doing. A mag adds **zero** SPI transactions and **zero** chain I2C traffic.
Given that the whole topology was designed around minimising bus round trips (DEC-004),
getting the mag for free is exactly the right shape.

**Consequence for the node board.** The node carries ICM-45686 + QMC6309 with two extra
short traces between them. The ATtiny is unaffected — it still owns one CS line and
nothing else.

---

## DEC-009 — ATtiny412-class part, not ATtiny10 or ATtiny85

**Decision.** The node MCU must have a hardware TWI slave **and** CCL. ATtiny412/402 is
the reference; ATtiny414/1614 if you want spare pins.

**Why not ATtiny10.** Three independent blockers, any one of which is fatal:

1. *No serial peripheral of any kind.* ATtiny4/5/9/10 have no TWI, no USI, no SPI. I2C
   slave would have to be bit-banged, in software, responding to two addresses, while
   also not missing the strobe. Slave-mode bit-bang cannot NAK-stretch its way out of
   trouble the way a master can — it has to keep up or corrupt the bus.
2. *No CCL.* The hardware strobe pass-through is the entire reason this design performs
   (DEC-004). Without it every CS edge goes through an interrupt handler, which on a
   1 KB part is microseconds per edge, and the chain collapses to the software-CS
   fallback we explicitly designated as bring-up only.
3. *Not enough pins.* Six-pin package, four I/O, one of which is RESET/TPI. We need SDA,
   SCL, CS_STROBE and CS — four — before any reset or power-gate line.

1 KB of flash and 32 bytes of SRAM would also be tight once a software TWI slave is in
there, but the pin count settles it before that matters.

**Why not ATtiny85.** It has USI, so an I2C slave is at least possible, but no CCL, so the
same argument as (2) above applies. It is also physically larger than an ATtiny412 in
SOIC-8 for strictly less capability.

**What actually matters when substituting.** Any tinyAVR 0/1/2-series part works if it
has CCL with a usable output pin and TWI slave with dual-address support. On 8-pin packages there is exactly one usable CCL output, and it is **LUT1-OUT on PA7**,
not LUT0 — PA4 and PA5 do not exist on the package. An earlier revision of this record said
LUT0, and the firmware was written against that; corrected after checking DS40001911B
Table 5-1.

---

## DEC-010 — CCL is a requirement of the *default* node, not of the design

**Decision.** Keep the CCL pass-through as the reference implementation, and add an
`EXTERNAL_CS_GATE` build variant that replaces it with one 74LVC1G32 OR gate.

**Why.** DEC-009 said "the node MCU must have CCL", which conflated two things: the design
needs a *combinational* path from the shared strobe to the local CS, and the ATtiny412
happens to be able to provide one on-chip. A single external OR gate provides the same
thing for about two cents:

```
CS = CS_STROBE OR ARMED_N
```

Not armed → the node holds `ARMED_N` high → `CS` is forced high regardless of the strobe.
Armed → `ARMED_N` low → `CS` follows the strobe, combinationally, no CPU in the path.
Identical timing behaviour, identical firmware protocol; the tracker cannot tell the two
variants apart.

It also falls out that software-CS mode still works with the gate fitted: if the host
parks the strobe low, `CS == ARMED_N`, so driving `ARMED_N` over I2C *is* driving CS. No
special case needed.

**What this buys.** Second-sourcing on the node MCU. Any part with a hardware I2C slave
and three free pins can be a node — ATtiny85 (USI), ATtiny84, an STM8, whatever is in
stock. Given that the node is otherwise a two-part board, being locked to one MCU family
for a peripheral that a jellybean gate can replace was a bad trade.

**Still excluded: ATtiny10.** The gate fixes the CCL problem and the pin problem — in
software-CS mode a node needs only SDA, SCL and CS, which fits the ATtiny10's three usable
I/O. What it does not fix is that ATtiny4/5/9/10 have **no serial peripheral at all**: no
TWI, no USI, not even SPI. The ATtiny85 can run the well-trodden USI TWI slave; the
ATtiny10 would need a fully bit-banged I2C slave, in 1 KB of flash and 32 bytes of SRAM
(stack included), decoding two addresses, over TPI rather than UPDI. Even done perfectly
it caps out around 100 kHz, which puts a CS edge at roughly 270 µs and drops the chain to
the bring-up-only performance tier. The part is 3 cents cheaper than an ATtiny412.

**Revisit when.** Never, for ATtiny10. The `EXTERNAL_CS_GATE` variant should get bench
time alongside the CCL one, since it is the fallback if the CCL setup fights megaTinyCore.

---

## DEC-011 — Protocol v2: keep arm/strobe as canonical, adopt channels from the review

**Decision.** When two chip-select designs collided, the arm/strobe protocol stays and the
per-write addressed scheme goes — but the multi-channel idea from the latter is folded in
as protocol v2.

**Why keep arm/strobe.** The alternative proposal drove CS with one addressed I2C write
per edge. Its own header comment costed this at ~60 µs per register access at 400 kHz,
which is precisely the software-CS fallback DEC-004 exists to avoid, promoted from
bring-up mode to the only mode. It also left RJ45 pin 6 as dead copper and, more seriously,
discarded one-hot arming (DEC-007): with per-node addressed writes nothing structurally
prevents two chip selects being asserted at once, and two IMUs driving MISO is a bus
fight, not a glitch.

**Why adopt channels.** The rejected design had one thing the original lacked: a channel
nibble, letting one node own up to 16 chip selects instead of one. On a chain that is
genuinely useful — a cluster of sensors at one point on the body can share a node instead
of needing one per sensor. It costs one nibble in a payload byte that was carrying a node
id in its low four bits anyway, so v2 packs `(nodeId << 4) | channel` and loses nothing.

A v1 node ignores the channel nibble and still works as a single-channel node, so the
change is backward compatible in the direction that matters. The host warns when it probes
a v1 node so nobody wires a second sensor to one and wonders why.

**Constraint accepted.** Multi-channel needs one gated output per channel, and an 8-pin
tinyAVR has exactly one usable CCL output. So multi-channel implies the `EXTERNAL_CS_GATE`
build with one OR gate per channel. The firmware enforces this with an `#error` rather
than failing quietly at runtime.

---

## DEC-012 — Presence is asked, not inferred

**Decision.** `PinInterface` gains `virtual bool isPresent() const { return true; }`.
`SPIImpl::hasSensorOnBus()` returns `m_csPin->isPresent()` and does no bus probing.

**Why.** A proposed fix for the long-standing `return true; // TODO` inferred presence by
reading registers `0x00`, `0x01`, `0x02`, `0x0F` and rejecting the bus if all four came
back identically `0x00` or `0xFF`. On the ICM-45686 that logic rejects a working sensor:
`TempData` is at `0x0c`, so `0x00`–`0x0b` are accel and gyro data, `0x0F` is still in the
data block, and `WHO_AM_I` is at `0x72` — outside the probed range. `hasSensorOnBus()`
runs before the driver configures anything, while accel and gyro are in standby, so all
four registers read zero on a perfectly healthy part. Sensor 0 is generated non-optional,
so the result is "Mandatory sensor 1 not found" on correct hardware.

The deeper problem is that SPI has no addressing and no ACK, so there is no bus-level
presence signal to read. Any answer inferred from MISO is a guess, and a guess that can
produce a false negative is worse than the `return true` it replaced — a false negative
takes down working hardware, while `return true` merely defers the question to
`checkPresent()`, which knows the actual `WHO_AM_I`.

What *is* knowable is whether the chip select can be reached. For a local pin that is
trivially true. For a remote ATtiny node it is false when the node never answered the
identity probe, which is exactly the failure worth catching early — and `ATTinyCSBus`
already enumerates the chain at boot, so the information was sitting there unused.

The default implementation returns true, so no existing `PinInterface` changes behaviour.

---

## DEC-013 — The mechanism is called I2SPI

**Decision.** Project term for the addressed remote chip-select scheme is **I2SPI**.
Settled by the project owner. Code identifiers (`ATTinyCSBus`, `ATTinyCSPinInterface`,
`ATTINY_CS`) are unchanged for now; the name applies to the mechanism and the wiring
standard, and a rename can follow if wanted.

**Recorded caveat**, so it is on the record rather than rediscovered later: the string
reads as I²S to most eyes, and it implies a merged bus when in fact SPI carries all the
sensor data and I2C carries only the selection. If a reader ever seems to think sample
data flows over the I2C pair, this name is why.

**Mitigation.** Docs say "I2SPI (SPI data, I2C selection)" on first use in each document,
which costs four words and removes the ambiguity where it matters.

---

## DEC-014 — Sensor VCC is gated, and sensors come up one at a time

**Decision.** Each node switches its sensor's 3V3 through a P-channel pass MOSFET driven
by the ATtiny. Sensors power up **off**; `ATTinyCSBus::init()` enumerates the chain with
only the ATtinys drawing current, then brings sensors online one at a time with a settle
delay between each.

**Why gate at all.** Three things, in order of how much they matter:

1. **Attribution.** A sensor that is shorted, mis-soldered or drawing wrongly takes the
   rail down. If everything comes up at once, all you know is that the chain browned out.
   Bringing them up one at a time makes the failure attributable to a node id, which on a
   suit with sensors sewn into it is the difference between a five-minute fix and an
   afternoon.
2. **Inrush.** Every sensor has bulk capacitance, and the node at the far end of the chain
   is behind a metre of thin cable with real series resistance. Summed inrush is a
   brownout; staged inrush is a droop.
3. **Recovery.** A hung sensor can be power-cycled without rebooting the tracker, which is
   why `SetSensorReset` now cuts the rail rather than driving a separate reset pin — a
   power cycle is a stronger reset than the sensor's own, and it costs no extra pin.

**Why P-channel high-side with a gate pull-up.** The polarity is chosen so that the
failure mode is de-energised. Gate high turns the FET off, and a 100k pull-up holds the
gate high whenever the ATtiny is not actively driving it — unprogrammed, held in reset, or
simply not yet at `setup()`. An unpowered IMU cannot drive MISO and cannot fight the bus,
so a node that fails to boot degrades to "sensor absent" rather than to a bus conflict
that takes down its neighbours.

Low-side switching would have been one cheaper part, and is wrong here: it leaves the
sensor's ground floating while its I/O pins are still tied to a live bus, which
back-powers the part through its ESD diodes.

**Cost.** One FET and one resistor per node, and a 10 ms settle per sensor at boot — 80 ms
for the eight-extension build, once, at startup.

**Verified in simulation**, not on hardware: `sim/` checks that nothing is powered before
`init()`, that all present nodes come up, that never more than one is ramping at a time,
that an absent node costs no settle delay, and that an unpowered sensor floats MISO rather
than returning plausible data.

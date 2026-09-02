# Progress log

Newest first. Each entry says what changed, what was verified, and what is still unproven.

---

## 2026-09-02i — Scope settled: palm only, no fingers

Requirement is palm rotation and position. That is Reading A from `GLOVE-OVER-I2SPI.md`:
back-of-hand trackers on `LEFT_HAND` / `RIGHT_HAND`, attaching as node 2 on the arm chains
that already declare an optional third sensor. **No firmware change, no server change, no
glove, no flex harness.** Build stands at 15 IMU sites / 18 tracked points.

The finger note is kept rather than deleted — the bus arithmetic and the "channels reduce
nodes, not traffic" point are worth having if per-finger comes up later.

### Worth being precise about "position"

SlimeVR IMU trackers are rotation-only; `Tracker.hasPosition` defaults to `false`. The palm
*position* is solved rather than measured. `HumanPoseManager.makeComputedTracker()` builds
`human://LEFT_HAND` with `hasPosition = true, hasRotation = true`, so downstream consumers
get a full 6-DoF palm pose — rotation from the IMU, position by forward kinematics down
shoulder → upper arm → lower arm → hand.

With all three arm segments measured, that chain is fully constrained, which is the best
case the solver gets. It also means the palm's positional accuracy depends on body
proportion calibration rather than on the sensor, so that is where to look if the palm
lands in the wrong place.

Same fact from the other direction, tying back to the arm FK correction two entries ago:
because the IMU carries no position, a palm tracker can never satisfy
`leftHandTracker.hasPosition` and therefore can never flip the skeleton into
controller-driven arms, whatever `forceArmsFromHMD` is set to.

---

## 2026-09-02h — "wrist" corrected to "hand/glove"

New note: `GLOVE-OVER-I2SPI.md`.

### The number 15 is doing double duty

`TrackerPosition` defines exactly **15 finger bones per hand** (thumb metacarpal/proximal/
distal plus proximal/intermediate/distal for four fingers), ids 21-35 left and 36-50 right.
So "15 points" reads either as 15 IMU sites on the body — the previous interpretation,
where the two extras are back-of-hand trackers and nothing changes — or as one full glove.
Flagged rather than assumed; the note covers both.

### Server support: complete

`HumanSkeleton` carries a bone and tracker slot for all 30 finger positions, plus
`hasLeftFingerTracker` / `hasRightFingerTracker` and `updateFingerTransforms()`.
`SkeletonConfigManager` divides total finger length over anatomical ratios.
`FirmwareConstants` already lists `GLOVE_IMU_SLIMEVR_DEV`. No patch needed.

The gap is assignment: board type arrives in the handshake but is informational, so 15
sensors per hand get assigned by hand in the UI. Thirty manual assignments across two
gloves is where wrong fingers come from. Server feature request, not a blocker.

### Changed

`board-defaults.schema.json` sensor ceiling 8 → 16, so a 15-finger-plus-palm config is
expressible. All 19 boards still generate.

### Where this lands, honestly

I2SPI is right for the forearm-to-glove link and questionable inside the glove. The chain
design solves "several sensors metres apart where one GPIO per CS is impossible"; a glove
has 20 cm runs, and `glove_default.h` already solves fan-out with a PCA9547 mux and ten
sensors using cheaper, smaller parts than an ATtiny per node.

Two things worth writing down before the channel feature gets oversold:

- **Channels reduce nodes, not bus traffic.** Five nodes × three channels costs exactly the
  same fifteen arm writes per cycle as fifteen single-channel nodes. The saving is board
  area, parts and power.
- **Multi-channel needs `EXTERNAL_CS_GATE`**, so three OR gates per finger node — fifteen
  extra parts per glove, mounted on fingers.

Bus arithmetic for 16 sensors is in the note: ~37% of a 200 Hz cycle at 400 kHz, ~11% at
1 MHz and 100 Hz. Fingers do not need 200 Hz, and the in-glove wiring is short enough that
Fast-mode Plus is much easier there than on the 85 cm body cable.

Also noted: the existing glove uses two sensors per finger, not three. The distal joint is
strongly coupled to the intermediate one, so the third segment is usually derived. Ten
sensors buys most of the fidelity of fifteen — worth deciding deliberately rather than
defaulting to one-per-bone because the enum has one per bone.

### The real blocker is mechanical

An RJ45 jack does not go on a finger and flat patch cable does not survive a knuckle. The
protocol travels into a glove; the connector and cable standard do not. Six signals plus
power to every finger segment, flexing at every joint — that flex harness is the hardest
engineering problem in this project, and the one with the least prior art in this repo.

---

## 2026-09-02g — Correction: the arm FK warning in the previous entry was wrong

The previous entry said `forceArmsFromHMD` defaults to `true` and that this causes the arm
trackers to be ignored, and advised turning it off. **That is backwards on both counts.**

From `SkeletonConfigToggles.java`:

```java
FORCE_ARMS_FROM_HMD(4, "Force arms from HMD", "forceArmsFromHMD", true),
```

and from `HumanSkeleton`:

```kotlin
get() = leftHandTracker != null && leftHandTracker!!.hasPosition && !forceArmsFromHMD
```

With the default `true`, `isTrackingLeftArmFromController` is false, and
`assembleSkeletonArms()` takes the branch that builds the arm downward from the shoulder —
every arm bone driven by the tracker on it. That is the mode this build wants. Turning the
toggle off, as previously advised, is what would have moved toward controller-driven arms.

The name misleads: "force arms from HMD" means the arm chain is anchored to the
HMD-referenced body and assembled from the shoulder down, not that the HMD supplies arm
rotations.

It is doubly a non-issue: `Tracker.hasPosition` defaults to `false` and SlimeVR IMU
trackers are rotation-only, so a wrist IMU assigned to `LEFT_HAND` cannot satisfy the
condition regardless of the toggle. Controller-driven arms need a positional hand tracker,
i.e. a SteamVR controller through the bridge.

**Switching between the two modes** is a live toggle — GUI Settings → General → FK
settings → Arm FK, or the same toggle over RPC. `updateToggleState()` calls
`assembleSkeletonArms(true)` and `computeDependentArmOffsets()`, re-parenting the bone tree
and recomputing offsets immediately, so it can be flipped while wearing the suit.

`EXAMPLE-18POINT-BUILD.md` has been corrected with the relevant source quoted, so the
wrong version does not survive in the docs.

### Lesson for the rest of this work

The mistake came from reading the condition at its use site (`if
(isTrackingLeftArmFromController)`) and inferring the polarity from the toggle's name
instead of reading its definition and default. Worth remembering for the remaining
server-side questions in `PLAN.md`, which are the same shape.

---

## 2026-09-02f — C5 band mode; wrist tracking checked against the server

### Fixed: the C5 will not start its radio without an explicit band

Arduino-ESP32 defaults a dual-band part to `WIFI_BAND_MODE_AUTO`, which faults when the
radio starts. `WiFiNetwork::setUp()` now calls `WiFi.setBandMode(WIFI_TRACKER_BAND_MODE)`
between `WiFi.mode(WIFI_STA)` and the first `WiFi.begin()`, which is the ordering the
reported workaround requires. Default is `WIFI_BAND_MODE_2G_ONLY`; override per build.

This amends DEC-002. Deferring 5 GHz was fine as a scope decision, but "leave the band
alone" was never an option on this silicon — the call is mandatory whichever band you end
up on. Without it the C5 boards would have failed at first boot in a way that looks like
a bad platform package rather than a missing API call.

The 5 GHz caveat stands and is now written down where someone will hit it: server
discovery is a UDP broadcast on the local subnet, so a 5 GHz-only tracker on an AP with a
separate 5 GHz SSID associates fine and then never finds the server.

### Note on the two conflicting platformio.ini recipes

The research handed over contains both `platform = espressif32@6.7.0` with
`board = esp32-c5-devkitc-1`, and a statement that stable `espressif32` has no C5 board
definitions. The second is right and the first cannot work — 6.7.0 predates the C5
entirely. Our envs already use pioarduino (DEC-001), which is the same conclusion the
research reaches in its Option 1. No change needed; recording it so the 6.7.0 snippet
doesn't get copied in later.

### Wrist tracking: no patch needed, on either side

Checked against the uploaded server source rather than from memory.

`TrackerPosition.kt` has 50 entries including `LEFT_HAND` (id 17) and `RIGHT_HAND` (18),
each with a `TrackerRole`, and `HumanSkeleton` gives them `leftHandBone`,
`leftHandTrackerBone` with a `COMPLETE` constraint, and a computed tracker. There is no
`WRIST` position and there does not need to be — a wrist-mounted tracker is assigned to
the hand position, which is what the skeleton is built around. "Wrist" exists in the
server only as an internal Unity/VMC armature node and VRChat OSC input paths.

Firmware needs nothing either: body position is assigned server-side, and the arm hubs
already declare an optional node 2 that currently finds nothing.

**The one thing that will bite:** `HumanSkeleton.forceArmsFromHMD` defaults to `true`.
While arms track from controllers, `BoneType.LEFT_LOWER_ARM` and `BoneType.LEFT_HAND` are
driven by the controller and the arm-chain trackers are ignored entirely. The symptom is
four sensors that connect, report, and visibly do nothing — which reads as a hardware
fault. Documented in the build doc.

### Point count resolved

15 IMU sites (13 + 2 wrists) is 18 tracked points with HMD and two controllers. Both
numbers describe the same build. `PLAN.md` open question closed.

### Not verified

The band mode call is written against the Arduino-ESP32 3.3 API and has not been compiled
— `WiFi.setBandMode` and `WIFI_BAND_MODE_2G_ONLY` need to exist under whatever pioarduino
build you land on. It's guarded by `#if defined(ESP32C5)` so it cannot affect other
boards.

---

## 2026-09-02e — Example build, hub board, board specs

### Added

- `docs/dev/EXAMPLE-18POINT-BUILD.md` — the 5-hub / 8-extension topology end to end:
  chain assignment, node id scheme, bus timing, power budget, bring-up order.
- `docs/hardware/BOARD-SPECS.md` — net-level specifications for the two PCBs.
- `BOARD_SLIMEVR_C5_CHAIN_HUB` (board id 30) plus its PlatformIO env. Three sensors: a
  local IMU on a direct chip select and nodes 1-2 on I2SPI, sharing one SPI bus.

The hub board is the first config to mix a direct GPIO chip select with remote ones on the
same bus, which is the case the `PinInterface` indirection was built for — `SPIImpl`
cannot tell them apart. Generated and checked; all 19 boards still build their flags and
pre-existing boards are unchanged.

Because sensor 0 is mandatory and the rest optional, the same image serves the arm hubs
(which have no node 2) and the chest/leg hubs. **Three firmware images cover thirteen
boards**: one hub, two node ids.

### Point count discrepancy, flagged not guessed

The listed sites are 13, which is 16 points counting HMD and two controllers, not 18. Two
shoulder nodes on the arm chains would close it with no firmware change — those chains
already declare a node 2 that currently finds nothing. Noted in `PLAN.md` under open
questions and called out in the build doc rather than silently assumed either way.

### kicad-happy

Looked it up rather than assumed. It's aklofas/kicad-happy, a suite of Claude Code skills
that **analyze** existing KiCad projects — schematic and layout review, EMC
pre-compliance, SPICE, datasheet extraction, BOM sourcing, fab prep. Two consequences:
it isn't available in this web session (no KiCad entry in the plugin catalog), and it
reviews rather than authors, so it can't take a description and produce boards.

`BOARD-SPECS.md` is therefore written as the *input* to schematic capture — nets named,
values fixed, constraints stated — with a list of the specific questions worth putting to
kicad-happy once the boards are drawn. The EMC pass on an unshielded 8-conductor cable
carrying a 4 MHz clock is the one I'd most want checked.

### Naming

I2SPI adopted as the project term (DEC-013), with the I²S-collision caveat recorded rather
than argued again.

### Not verified

Nothing new built or bench-tested. Power figures are estimates and labelled as such.
Cable lengths are nominal. The server's handling of three sensors on one tracker is still
unverified.

---

## 2026-09-02d — Review fixes; protocol v2

Audit of the incoming `ATTinyCSPinInterface.{h,cpp}` and `SPIImpl` changes is in
`REVIEW-attiny-cs-pin-interface.md`; all ten findings are now resolved.

### The one that would have hurt

`hasSensorOnBus()` had been changed from `return true; // TODO` to a heuristic that read
registers `0x00`, `0x01`, `0x02`, `0x0F` and declared the bus dead if all four matched at
`0x00` or `0xFF`. On the ICM-45686 those are all accel/gyro data registers — `TempData` is
at `0x0c` and `WHO_AM_I` is at `0x72`, outside the probed range — and the probe runs before
the driver leaves standby, so a healthy sensor reads four zeros and gets rejected. Sensor 0
is non-optional, so the symptom is "Mandatory sensor 1 not found" on correct hardware.

Replaced with `PinInterface::isPresent()` (DEC-012). SPI has no addressing and no ACK, so
there is nothing on the bus to infer presence *from*; what is knowable is whether the chip
select is reachable, and for a remote node `ATTinyCSBus` already had that answer from its
boot enumeration and wasn't using it.

### Protocol v2

Two chip-select designs had collided. Kept arm/strobe (the alternative cost ~60 µs per
register access and dropped one-hot arming, which is a bus-fight safety property, not an
optimisation), but took the multi-channel idea from the other: `Arm` and `SetCs` payloads
now pack `(nodeId << 4) | channel`, so one node can own up to 16 chip selects. v1 nodes
ignore the nibble and still work as single-channel nodes; the host warns when it sees one.
DEC-011.

Multi-channel needs one gated output per channel and an 8-pin tinyAVR has one usable CCL
output, so it requires the `EXTERNAL_CS_GATE` build — enforced with an `#error` rather than
failing quietly.

### Also

- Deleted the duplicate `::ATTinyCSPinInterface`. Two classes with the same name in
  different namespaces compiled only because unqualified lookup inside `namespace SlimeVR`
  found the inner one first.
- All six `SPIImpl` register accessors gated on `isUsable()`; `readBytes` zeroes the
  caller's buffer. The old comment claimed this was already true; only
  `hasSensorOnBus()` was.
- `ATTinyCSBus` validates that `base` through `base + MaxNodeId` stays inside the usable
  I2C range, logs failures throughout, and clears the armed target on a failed CS write. A
  failed select no longer pulses the strobe, which would have asserted whichever node was
  still armed.
- `channel` added to the board-defaults schema and generator (`ATTINY_CS_CH`).

### Verified

- All 18 boards still generate; pre-existing boards byte-identical.
- `clang-format` 17 clean.
- Compiled *and ran* the presence logic against stubs: present → true, absent node →
  false, null chip select → false, no dereference.

### Still not verified

No target build, no hardware. Unchanged from previous entries.

---

## 2026-09-02c — Node MCU survey; naming left open

### Added

`HARDWARE-RJ45-SPI-BUS.md` now carries a "Node MCU candidates" section: the two hard
requirements (a *hardware* I2C slave; three free I/O with the gate, four without), a
comparison table covering ATtiny 0/1/2-series, PIC16F18313/18323, CH32V003, STM32C011F
and PY32F002A, and two alternatives that came out of writing it:

- **The no-MCU option.** With the gate fitted, the node's whole job is "answer I2C, drive
  one pin" — a PCF8574 with strapped address does that with no firmware. What it costs is
  specific and worth naming: one-hot arming (DEC-007) degrades to two writes per sensor
  switch with a window where two nodes can be armed, and the identity block disappears, so
  a mis-strapped node goes silent instead of announcing itself. Those two properties are
  most of what the MCU is actually buying.
- **A single-address protocol (v2).** Noticed while checking which parts support two own
  addresses: every write already carries a node id, and since arming is one-hot, a read
  from the shared address could be answered by the armed node alone. That removes the
  dual-address requirement and opens the part list to anything with a plain I2C slave.
  Not implemented — v1 works — but it's the lever to pull if part supply gets awkward.

Worth flagging: PIC16F18313 has **PPS**, so its CLC output routes to any pin. That
removes the fixed PA6/PA7 pin map the ATtiny412 forces on us. The cost is a second
toolchain in a repo that is otherwise entirely PlatformIO.

### Open question recorded, not decided

Naming. `I2SPI` is now listed under "Open questions" in `PLAN.md` with the argument
against it (collides with I²S; implies a merged bus when SPI carries all the data and I2C
only the selection). Not renamed anything — that call isn't mine to make, and it's a
mechanical change whenever it's made.

### Not verified

Nothing new was built or tested. The table is compiled from datasheets and, for the
CH32V003 Arduino core's I2C slave support, from PlatformIO community reports rather than
first-hand use — treat that row as the least certain.

---

## 2026-09-02b — Node MCU requirements loosened; ATtiny10 still out

Follow-up to "can the ATtiny10 do the chip select like the ATtiny85". Answering it exposed
that DEC-009 had over-constrained the design: it said the node MCU needs CCL, when what
the design actually needs is *a combinational path from strobe to CS*. An external OR gate
provides that for two cents.

### Added: `EXTERNAL_CS_GATE` build variant

`extras/attiny-cs-node/` now builds two ways:

- **Default (CCL).** ATtiny412-class part, strobe gated on-chip. Unchanged.
- **`-DEXTERNAL_CS_GATE`.** Any MCU with a hardware I2C slave and three free pins, plus a
  74LVC1G32 wired `CS = CS_STROBE OR ARMED_N`. The node drives `ARMED_N`; the gate does
  the combinational work. Pin numbers are plain and overridable (`-DPIN_ARMED_N`), the
  megaTinyCore `Event`/`Logic` includes are compiled out, and `digitalWriteFast` falls
  back to `digitalWrite` on cores that lack it.

Software-CS mode needed no special case in the gate variant: with the host parking the
strobe low, `CS == ARMED_N`, so the existing `SetCs` path drives the same line.

The tracker firmware is unchanged and cannot tell the variants apart — the gate node is
just a strobe-mode node as far as `ATTinyCSBus` is concerned.

### ATtiny10: still no, for a narrower reason than before

The gate removes the CCL objection, and pin count is fine in software-CS mode (SDA, SCL,
CS = three, which the ATtiny10's three usable I/O covers). What remains is decisive:
ATtiny4/5/9/10 have **no serial peripheral of any kind** — no TWI, no USI, not even SPI.
The ATtiny85 has USI and can run the standard USI TWI slave; the ATtiny10 would need a
bit-banged I2C slave decoding two addresses in 1 KB of flash and 32 bytes of SRAM, stack
included, flashed over TPI. Done perfectly it caps near 100 kHz, which is ~270 µs per CS
edge — the bring-up-only performance tier, permanently.

Written up as DEC-010.

### Not verified

Neither variant has been compiled or bench-tested. The gate variant is the more likely of
the two to build first, since it has no core-specific peripheral API in it — worth trying
if the megaTinyCore `Event`/`Logic` setup fights back.

---

## 2026-09-02 — ICM-45686 + QMC6309 pass

Triggered by the question "can our I2C protocol identify the sensors, and can we use an
ATtiny10". Short answers: identification already works and needs no protocol change; the
ATtiny10 cannot do the job. Both written up as DEC-008 and DEC-009.

### Found: QMC6309 configuration writes are silently discarded

`softfusionsensor.h` built its `MagInterface` with

```cpp
.writeByte = [&](uint8_t address, uint8_t value) {},   // empty body
```

while `ICM45Base::writeAux()` sat there unused. So every register write in the QMC6309
`setup()` lambda — soft reset, 8 g range, 200 Hz, oversampling — went nowhere. The mag
would still be *detected*, because `WHO_AM_I` is a read and reads worked, and would then
sit in standby returning nothing. That is a nasty failure shape: the log says the mag was
found, and the data is silently absent.

Wired `writeByte` to `writeAux`. **Only half a fix.** `writeAux()` is a verbatim copy of
`readAux()` with `I2CMDevProfile0`/`I2CMWrData0` added — the transaction-type bits in
`I2CM_COMMAND_0` still say `0b01 << 4 // Read with register`, comments and all. That has
to be checked against AN-000478 / the ICM-45686 register map before mag configuration can
be trusted. Marked with a FIXME at the call site rather than guessed at.

### Changed

- `BOARD_ESP32C5_RJ45_HUB` now names `IMU_ICM45686` instead of `IMU_AUTO`. On a chain,
  `IMU_AUTO` probes every supported driver *per node* through remote chip select, which
  is a lot of arming and SPI traffic at boot for a build where the part is known.
- `docs/dev/DECISIONS.md`: DEC-008 (mag on AUX1), DEC-009 (node MCU requirements).
- `docs/dev/HARDWARE-RJ45-SPI-BUS.md`: node parts list now covers the mag.

### Unchanged, deliberately

The ATtiny protocol still identifies *nodes*, not sensors, and should stay that way. The
sensors identify themselves over the paths that already exist: the IMU by `WHO_AM_I`
(reg `0x72` == `0xE9`) over SPI through the selected node, the mag by `WHO_AM_I`
(reg `0x00` == `0x90`) over the IMU's AUX1 I2C master. Duplicating that into the node
firmware would create a second source of truth that can disagree with the hardware.

---

## 2026-09-01 — Initial implementation pass

### Done

**Documentation** (`docs/dev/`)
- `PLAN.md`, `DECISIONS.md`, `HARDWARE-RJ45-SPI-BUS.md`, `ATTINY-CS-PROTOCOL.md`, this file.

**Phase 1 — ESP32-C5**
- `src/consts.h`: `BOARD_ESP32C5_DEVKITC1` (28), `BOARD_ESP32C5_RJ45_HUB` (29).
- `platformio.ini`: two envs on the pioarduino platform, board `esp32-c5-devkitc-1`.
  `ci/build-matrix.py` derives the CI matrix from the ini's `[env:...]` sections, so both
  are covered automatically.
- `lib/i2cscan/i2cscan.cpp`: `ESP32C5` arm. Candidate pins are GPIO 0,1,3,4,5,6,8,9,10,
  11,12,15,23,24 — everything except flash/PSRAM (16–22), USB-JTAG (13–14), strapping
  (2, 7, 25, 27, 28) and boot mode (26). Cross-checked against the ESP-IDF C5 GPIO table.
- `board-defaults.json` + schema: `BOARD_ESP32C5_DEVKITC1` (two I2C ICM45686 on
  SCL 4 / SDA 5, battery on GPIO1 which is ADC1_CH0).

**Phase 2 — SPI**
- `DirectSPIInterface` now takes `SPIClass*` plus explicit `sck`/`miso`/`mosi`, with
  `PinDefault` (-1) meaning "core default for this SoC". `init()` is `#ifdef ESP32`-split
  because ESP8266's `begin()` takes no pins.
- `SensorInterfaceManager` caches SPI buses on `(SPIClass*, SPISettings, sck, miso, mosi)`.
  Removed `operator<(const SPIClass&)` — see DEC-005 for the dangling-reference bug this
  fixes.
- `SensorBuilder`: added `SPI_BUS(clock, bitOrder, mode, sck, miso, mosi)`.
  `DIRECT_SPI(clock, bitOrder, mode)` is now a thin wrapper over it and generates the same
  descriptor as before.
- `scripts/preprocessor.py`: optional `"SPI"` block in board values drives clock, bit
  order, mode and pins.

**Phase 3 — ATtiny remote chip select**
- `src/sensorinterface/ATTinyCSProtocol.h` — wire constants, shared verbatim with the node
  firmware so the two cannot drift.
- `src/sensorinterface/ATTinyCSInterface.{h,cpp}` — `ATTinyCSBus` (arming, enumeration,
  identity checks) and `ATTinyCSPinInterface` (a `PinInterface` that `SPIImpl` can't tell
  from a local pin).
- `SensorBuilder`: `ATTINY_CS(nodeId)` and `ATTINY_CS_ON(scl, sda, base, strobe, nodeId)`.
- `src/globals.h`: `REMOTE_CS_SCL` / `_SDA` / `_BASE_ADDR` / `_STROBE` defaults.
- `scripts/preprocessor.py` + schema: `"REMOTE_CS"` block and object-form `"cs"`.
- `extras/attiny-cs-node/` — node firmware, PlatformIO config, README.
- `BOARD_ESP32C5_RJ45_HUB` board default: four auto-detected SPI IMUs on nodes 1–4,
  bus on GPIO 10/11/12, chain I2C on 4/5, strobe on 6, 4 MHz.

### Verified

- `scripts/preprocessor.py` runs clean against the real schema for **all 18 boards**.
- `BOARD_SLIMEVR_V1_2`'s generated flags are **byte-identical** to before this change,
  which was the point of keeping `DIRECT_SPI` at its original arity (DEC-006). Same for
  every other pre-existing board.
- `clang-format` 17 (repo `.clang-format`) is clean on every touched and added file, so
  the CI format job should pass.

### Not verified — this is the important part

**Nothing has been compiled.** No PlatformIO toolchain in this environment and no network
route to the platform registries. Every call site was hand-checked against the interfaces
as they exist in this tree, but the first `pio run` is the real review.

Specific things to watch on first build:

1. `SPIClass::begin(sck, miso, mosi, ss)` — exists on ESP32 cores, guarded for ESP8266,
   guard untested.
2. pioarduino's C5 variant may not define `LED_BUILTIN`; `board-defaults.json` assumes it.
3. megaTinyCore's `Event`/`Logic` API names (`gen0::pin_pa6`, `user::ccl0_event_a`) drift
   between versions.
4. megaTinyCore `Wire.begin(addr, broadcast, second_address)` dual-address encoding.

Nothing has been on hardware. The bring-up order in `HARDWARE-RJ45-SPI-BUS.md` exists
because the failure modes here (a chain that half-works at 8 MHz, a node flashed with the
wrong id) are much easier to find one variable at a time.

### Open issues found along the way

- **`byteCompare` is not a strict weak ordering.** In `SensorInterfaceManager.cpp` it
  returns `false` on the first byte that isn't less-than instead of continuing while bytes
  are equal. Any `std::map` keyed with it can misbehave. Still used for `SPISettings`.
  Left alone deliberately: fixing it changes cache behaviour for shipping boards and
  belongs in its own change. (DEC-005)
- **`SPIImpl::hasSensorOnBus()` returns `true` unconditionally** (pre-existing `// TODO`).
  With remote nodes we could do better — `ATTinyCSBus::probe()` already knows whether the
  node answered. Would need `SPIImpl` to be able to ask its CS pin, which means either a
  new virtual on `PinInterface` or a `dynamic_cast`. Not done.
- **Sensor 0 is always generated as mandatory** (`'false' if index == 0`), so on a chain
  board node 1 must be present or the tracker reports an erroneous sensor. Probably right,
  but it should be expressible in the JSON.
- **The arming I2C write happens inside an open SPI transaction.**
  `DirectSPIInterface::beginTransaction()` calls `spi->beginTransaction()` and *then*
  `csPin->digitalWrite(LOW)`, which for a remote pin may do an I2C write. It only happens
  on the first transaction after a sensor switch, so it is not hot, but it holds the SPI
  bus mutex across an I2C transfer. Cleaner would be a `prepare()` hook on `PinInterface`
  called before `beginTransaction`.
- **`PIN_IMU_INT` was only emitted when a sensor declared an `int` pin**, but
  `serialcommands.cpp` prints it unconditionally. Now defaults to 255. This was latent —
  any board config without an `int` on sensor 0 would have failed to build.

### Next

1. Build both C5 envs. Fix whatever the toolchain says.
2. Flash `BOARD_ESP32C5_DEVKITC1` on a devkit with two I2C IMUs — proves the board support
   independently of the chain work.
3. Build one node board. Bring it up in software-CS mode first (`"strobe"` omitted from
   `REMOTE_CS`), which removes CCL from the equation entirely.
4. Switch that node to strobe mode, scope the CS edge at the IMU.
5. Walk the clock up, then add nodes.
6. Then, and only then, revisit 5 GHz (DEC-002).

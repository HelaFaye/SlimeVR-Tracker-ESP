# Plan: ESP32-C5 support + remote SPI sensors over RJ45 with ATtiny chip-select nodes

Status: in progress
Owner: (you)
Last updated: 2026-09-01

## Goal

Three related pieces of work, in dependency order:

1. **ESP32-C5 board support.** New RISC-V SoC, dual-band Wi-Fi (2.4 + 5 GHz), 29 GPIOs.
   Needs a PlatformIO env, a board id, board defaults, and pin-scan tables.
2. **First-class SPI sensor support.** The tree already has `DirectSPIInterface` and
   `SPIImpl`, but the SPI bus pins are not configurable, the bus object is cached by
   value (a latent dangling-reference bug), and the JSON board-defaults generator
   hard-codes 24 MHz / MODE3 / direct-GPIO chip select.
3. **Remote chip select via ATtiny I2C nodes.** Each remote sensor board carries an
   ATtiny with its own I2C address. The ATtiny owns the sensor's `CS` line so that an
   arbitrary number of SPI sensors can hang off one 8-conductor flat RJ45 cable without
   needing one host GPIO per sensor.

The wiring target is off-the-shelf **flat** RJ45 patch cable (8P8C, straight-through,
untwisted ribbon). Eight conductors is the hard budget that shapes the whole design —
see `HARDWARE-RJ45-SPI-BUS.md`.

## Phases

### Phase 0 — Survey (done)

- [x] Map the sensor abstraction: `SensorInterface` (bus/mux) vs `PinInterface` (a single
      pin) vs `RegisterInterface` (register-level sensor access).
- [x] Map the build-time config path: `board-defaults.json` → `scripts/preprocessor.py`
      → `-D` flags → `SENSOR_DESC_LIST` → `SensorBuilder::buildAllSensors()`.
- [x] Confirm CI builds every `[env:...]` in `platformio.ini` automatically
      (`ci/build-matrix.py` parses the ini), so a new env is auto-covered.
- [x] Confirm `intPin` is optional throughout (`DirectPinInterface` validator rejects
      pin 255 and returns `nullptr`); softfusion drivers poll the FIFO on a timer.
      **This is what frees the 8th conductor for a CS strobe.** See DEC-004.

### Phase 1 — ESP32-C5 board support

- [x] `BOARD_ESP32C5_DEVKITC1` id in `src/consts.h`.
- [x] `[env:BOARD_ESP32C5_DEVKITC1]` in `platformio.ini` on the pioarduino platform.
- [x] `ESP32C5` guard arms in `lib/i2cscan/i2cscan.cpp` (port array + exclusions).
- [x] `board-defaults.json` entry + `board-defaults.schema.json` enum entry.
- [ ] Verify a real build (needs network access to the pioarduino platform — not
      possible in this sandbox, see "Verification gap" below).
- [ ] Bench-check: LED pin, ADC pin for battery, USB-CDC serial behaviour.
- [x] Band mode must be set explicitly on the C5 (AUTO faults at radio start).
      `WIFI_TRACKER_BAND_MODE` added, defaulting to 2.4 GHz. See DEC-002 amendment.
- [ ] Verify 5 GHz end to end, including UDP server discovery. Still deferred.

### Phase 2 — SPI as a first-class bus

- [x] Give `DirectSPIInterface` explicit `sck` / `miso` / `mosi` pins, with `-1`
      meaning "use the core's default pins for this SoC".
- [x] Fix the interface cache to key on `(busIndex, settings, sck, miso, mosi)` and hold
      the bus as a pointer rather than binding a reference to a by-value cache key.
      (DEC-005)
- [x] `SPI_BUS(...)` descriptor macro alongside the existing `DIRECT_SPI(...)`, which
      stays as a backwards-compatible alias so `BOARD_SLIMEVR_V1_2` is untouched.
- [x] Teach `scripts/preprocessor.py` to emit SPI pins / clock / mode from JSON instead
      of hard-coding them.
- [ ] Measure achievable clock on real hardware over 1 m of flat cable.

### Phase 3 — ATtiny remote chip select

- [x] Protocol spec (`ATTINY-CS-PROTOCOL.md`).
- [x] `ATTinyCSBus` — owns the I2C side, tracks which node is currently selected,
      and skips redundant selects.
- [x] `ATTinyCSPinInterface` — a `PinInterface` that looks like a normal CS pin to
      `SPIImpl` but routes assert/deassert through the bus.
- [x] Wire both into `SensorInterfaceManager` + an `ATTINY_CS(...)` descriptor macro.
- [x] JSON schema + generator support for `"cs": { "type": "attiny", ... }`.
- [x] ATtiny node firmware (`extras/attiny-cs-node/`).
- [ ] Bench bring-up: one node, then three, then a full 6-node chain.
- [ ] Hot-plug / absent-node behaviour (currently: node absent → sensor reports as
      not present, which is the same path as a dead I2C sensor).

### Phase 4 — Integration and polish

- [ ] A `BOARD_ESP32C5_RJ45_HUB` board default that ships the 6-sensor chain config.
- [ ] Raise `MAX_SENSORS_COUNT` handling for chains (glove already uses 10, so the
      machinery works; the schema's `maxItems: 2` is the blocker — raised to 8).
- [ ] Serial `CONFIG` command output for remote nodes (currently prints
      `PIN_IMU_SDA`/`SCL`/`INT` from `-D` flags, which is already flagged FIXME upstream).
- [ ] Server-side: sensor position assignment for >2 sensors on one tracker.

## Verification gap (read this before trusting the diff)

This sandbox has no PlatformIO toolchain and no network route to
`dl.registry.platformio.org` / `dl.espressif.com`, so **nothing here has been compiled.**
The C++ is written against the interfaces as they exist in this tree, and every call site
was checked by hand, but treat the first `pio run` as the real review. Likely first-build
friction points, in rough order of probability:

1. `SPISettings` field names (`_clock`, `_bitOrder`, `_dataMode`) are already used by
   `SPIImpl`'s logging on both cores, so they should be fine — but they are private in
   some Arduino cores and the existing code only compiles because of core-specific
   `friend`/public declarations. If it breaks, it breaks in code that predates this work.
2. `SPIClass::begin(sck, miso, mosi, ss)` exists on ESP32 cores; ESP8266's `SPIClass`
   takes no arguments. Guarded with `#ifdef ESP32`, but the guard is untested.
3. The pioarduino platform pin defines for C5 (`SDA`, `SCL`, `LED_BUILTIN`) may differ
   from what `board-defaults.json` assumes.

## Open questions

- ~~How the example build counts to 18 points.~~ **Resolved:** the two wrist extensions
  make it 15 IMU sites and 18 tracked points. They attach as node 2 on the arm chains,
  which needs no firmware or server change.

- ~~What to call the remote chip-select mechanism.~~ **Settled: I2SPI.** See DEC-013.
  Code identifiers unchanged for now; rename is mechanical whenever wanted.
- **Whether to move to a single-address protocol (v2).** Would widen the node MCU list to
  any part with a plain I2C slave. See `HARDWARE-RJ45-SPI-BUS.md`.
- **Whether the node needs an MCU at all**, versus a PCF8574 plus the OR gate. Same doc.

## Out of scope for now

- ESP-NOW / any transport change (there is an `espnow` branch upstream; unrelated).
- Powering remote nodes from the cable at more than a few tens of mA (see the
  voltage-drop note in `HARDWARE-RJ45-SPI-BUS.md`).
- Daisy-chained CS shift registers (74HC595) — rejected, DEC-003.

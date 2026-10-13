# Overlap with upstream and forks

A survey, done 2026-10-12, of every branch and every recently active fork of
SlimeVR-Tracker-ESP and SlimeVR-Server, looking for anything that duplicates or collides
with the work in this fork and its two sibling repositories.

## Method

- **Upstream branches:** all heads of `SlimeVR/SlimeVR-Tracker-ESP` (34) and
  `SlimeVR/SlimeVR-Server` (79), listed over git. Candidates fetched and diffed against
  `main`.
- **Upstream pull requests:** all 26 open tracker PRs, from GitHub's PR list. Overlapping
  ones fetched (`refs/pull/N/head`) and diffed against their merge base.
- **Tracker forks:** the 96 forks GitHub lists as active in the last two years (4 pages).
  Every branch listed over git (718 branches); the 314 tips not already present upstream
  were fetched and their **added lines** grepped against upstream `main`, in two passes:
  - broad: C5, band, SPI pins, chip select, ATtiny, I2SPI, RJ45, E22, ESP-NOW,
    multiplexers, channel switching, communication strategy;
  - narrow: strong signals only.
- **Server forks:** the 63 forks listed as active in the last year (3 pages). Every branch
  listed (879); the 270 tips not upstream were fetched tree-only and searched for Python
  tools, emulators, fakes, simulators, ESP-NOW and dongle work.
- **Outside GitHub's fork graph:** web searches for SlimeVR C5 ports, multi-IMU chain
  designs and fake-tracker tools.

GitHub's fork list hides forks with no activity in the period, and forks of forks unless
they are active. Anything older or fully dormant was not examined.

## Overlaps that need action

### 1. Configurable SPI bus pins: upstream PR #539 (open)

**"Add configurable shared SPI bus pins"**, Feather-P, July 2026. Also mirrored as
`unlogisch04/feat/spi-pin`, by an upstream maintainer.

It is the same change we made in `DirectSPIInterface`: hold the bus by pointer (its comment
cites a heap double-free on ESP32-C3 when the global `SPI` is copied through the interface
cache, which is our DEC-005 by another route) and accept SCK/MISO/MOSI. Differences:

| | #539 | This fork |
|---|---|---|
| "Default pin" sentinel | `255` | `-1` (`DirectSPIInterface::PinDefault`) |
| Descriptor | `DIRECT_SPI(clock, order, mode[, sck, miso, mosi])` | `DIRECT_SPI(...)` unchanged, plus `SPI_BUS(... sck, miso, mosi)` |
| Board schema | Restructured: `BUS` objects (`I2C_BUS`, `SPI_BUS`) that contain their IMUs | Top-level `SPI` (one bus or named map); sensors pick with `"bus"` |
| Cache key | — | Includes the pins, so two buses on one peripheral stay distinct |

**Action:** do not upstream our SPI-pin change separately. If #539 merges, rebase onto it:

- adopt its sentinel and descriptor signature;
- re-express `SPI`, `REMOTE_CS` and chained I2C sensors inside its `BUS` model;
- carry over our pins-in-the-cache-key (#539 needs it as soon as two buses share
  `&SPI`).

`sim/check_desc_list.py` will flag any descriptor arity mismatch during that rebase.

### 2. Magnetometer aux writes: upstream PR #465 (open)

**"Mag Support (Continuation)"**, gorbit99. Contains a correct `writeAux`. Upstream's
`mag-and-spi` branch (April 2025) also had it right, so `main`'s read-instead-of-write is a
regression. **Action:** report as "please land #465"; drop our local fix when rebasing onto
it. Recorded in `UPSTREAM-FINDINGS.md` §1.

**Since 2026-10-13 we also overlap #465's mag pipeline** (DEC-017). We needed SPI
magnetometers, and `main` cannot deliver a mag sample to the fusion at all, so we wrote
our own host-polled path rather than wait on a WIP PR. Overlapping pieces:

| #465 | This fork |
|---|---|
| `processMagSample`, mag read through the IMU aux master | `MagDriver::poll()`, host-polled at `MagTs`, any SoftFusion IMU |
| `scaleMagSample`, per-part `resolution` | Same names and intent; adds byte order, zero offset, per-transport burst flag |
| `isMagAttached` | Same |
| `readAux` burst | Same shape (`readAux(addr, buf, len)`) |
| `SensorToggles` `emitToggleChange` fix | Same fix |
| — | SPI transport, MMC5983MA, LIS3MDL, `"mag"` in board config |

**Action:** when #465 lands, rebase onto it, keep its names, and re-add the SPI transport
and the two parts on top. Offer the SPI transport upstream as a follow-up to #465, not as
a competing PR.

### 3. Wi-Fi transport abstraction: upstream PR #534 (open)

**"Move Wi-Fi code to strategy pattern"**, gorbit99, July 2026. Adds
`CommunicationStrategy` and moves Wi-Fi into `src/network/wifi/`. 32 files, ~1.9k lines.

**Action:**

- Our only network change, ESP32-C5 band selection in `wifihandler.cpp`, will conflict
  textually; it moves into `WiFiCommunication` when rebasing.
- Any future transport (ESP-NOW hub, a co-processor radio) **must** be built as a strategy
  on #534, not as a parallel abstraction. See `E22-AND-C5-HUB.md`.

### 4. I2C scanner: upstream PR #538 (open)

**"fix i2c scann stalling on ESP32\* boards"**, unlogisch04. Rewrites the scan loop and the
ESP32 exclude list. Our ESP32-C5 port arrays are a separate `#elif` block. **Action:** expect
a small textual conflict; keep the C5 block (its pins are checked by
`sim/check_numbers.py`).

## Prior art to build on, not repeat

### 5. ESP32-C5 builds

- `unlogisch04/esp32_tasmota` (June 2025) has an `env:esp32c5` against pioarduino
  `develop_33`: a test build only, with no board definitions, band selection or pin work.
- No other fork, and nothing found on the web, ports SlimeVR to the C5.

This fork's C5 support is not redundant. Coordinate with unlogisch04 before upstreaming,
since they have evidently looked at it.

### 6. ESP-NOW trackers and a USB gateway

| Where | What | Last activity |
|---|---|---|
| `mitzey234/SlimeVR-Tracker-ESP` `esp-now` (and `PT-1.5B/D`) | Tracker side: pairing, gateway search by channel hop over {2, …, 14}, gateway-assigned ids, rate control, OTA over ESP-NOW | Mar 2026 |
| `mitzey234/SlimeVR-Receiver-ESP-Now` | ESP32-S3 USB gateway | — |
| `Shine-Bright-Meow` `espnow`, `RamesTheGeneric` `espnow-update`, `pembem22` `esp-now` | Variants of the same | 2025–2026 |
| `gorbit99` `dongle-support`, `espnow-with-sfusion` | Earlier dongle work | Nov 2024 |
| Upstream `espnow` branch | Original experiment (Eiren) | Nov 2024 |

**Action:** the C5 hub in `E22-AND-C5-HUB.md` should start from mitzey234's tracker and
receiver, add 5 GHz and the channel-switch announcement, and land as a strategy on #534.

### 7. Multi-IMU wiring

The community **L,i,me** design (multiple IMUs per tracker, hardware only, development
ended) is the nearest prior art to I2SPI found. Nothing found routes chip selects or gated
I2C clocks over a shared cable to addressed nodes. I2SPI is not redundant.

## Checked, no overlap

- **Tracker:** `machine-optimized-spi` and `mag-and-spi` are the older origin of the
  `SPIImpl` and ICM-45 work now on `main`. `network-experiments`, `feat/wifiscan_channel`
  (PR #531) and `wip/packet-compression` touch network code we did not change. PR #541
  ("Config optimization") touches configuration, logging and sensors, none of our files.
- **Server:** `llelievr/trackers-udp-tests` refactors `TrackersUDPServer` and the protocol
  parser; it is not a tracker simulator. Nothing upstream or in the 63 active server forks
  is a synthetic or fake tracker (scan result below). After that refactor lands, rerun
  `tools/synthetic-tracker` against it, since it parses the same packets.
- **Web:** the nearest fake-tracker tool found is an npm package that emulates a tracker
  from serial data. It is not a posable multi-tracker UDP driver.

## Server fork scan result

All 270 non-upstream branch tips across the 63 active server forks were fetched tree-only
and searched for Python files, fake, synthetic or simulated trackers, emulators, I2SPI,
ATtiny and ESP-NOW work.

- **No tracker simulator anywhere.** The name matches were upstream's own `ViveEmulation`
  (a skeleton feature) and the dongle onboarding and telemetry UI.
- **MonakaVR/MonakaVR** carries Python tooling: `third_party/monaka-protocol{,-v2}/tools/`
  and release and protocol verification scripts. These are codec, schema and fixture tests
  for its own MonakaProtocol wire format, not a driver that speaks the SlimeVR UDP tracker
  protocol at a server.
- **Dongle UI** (`gui/.../onboarding/pages/Dongle.tsx`, and in KibbieKatt's
  `projected-yaw-rst` `DongleSettings`/`DongleTelemetry`) is server-side support for the
  official nRF dongle. Relevant background if a C5 ESP-NOW gateway (§6) is ever presented
  to the server as a dongle rather than as UDP trackers.

`tools/synthetic-tracker` in HelaFaye/SlimeVR-Server is therefore not redundant.

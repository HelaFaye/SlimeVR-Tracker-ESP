# Booting the firmware in QEMU

`qemu/run.sh` builds a board, packs it into a flash image and boots it in
[Espressif's QEMU fork](https://github.com/espressif/qemu). It then checks the serial log:
exactly one boot banner, no panic, abort, backtrace or watchdog reset, and every line
the scenario expects.

```sh
qemu/run.sh BOARD_WROOM32                    # one board, stock config
qemu/run.sh BOARD_ESP32S3_SUPERMINI chain    # S3 with the I2SPI chain config swapped in
qemu/run.sh --all                            # everything in qemu/scenarios.txt
```

Logs land in `.pio/qemu/<env>[-<scenario>]/`: `build.log`, `serial.log` (the firmware's
output), `qemu.log`.

## What it can and cannot show

Stock Espressif QEMU emulates the **ESP32, ESP32-S3 and ESP32-C3** CPUs, flash and UART,
but not Wi-Fi, I2C or SPI peripherals, and it has **no ESP32-C5 or C6 machine**. With it,
`run.sh` proves that the image boots, `setup()` completes, and the firmware survives
absent hardware without crashing or boot-looping. The `chain` scenario takes the I2SPI
host code through an empty chain (`No ATtiny CS nodes answered`).

## With sensors, chains and a server

[HelaFaye/qemu_esp32](https://github.com/HelaFaye/qemu_esp32) carries a patch series on
Espressif's QEMU that adds the S3's GPIO matrix, SPI and I2C masters, Wi-Fi with an
emulated access point, the RMT, emulated **ICM-45686s** on I2C or SPI, and **I2SPI
chains**. `qemu/s3.sh` clones it at the commit pinned in `qemu/QEMU_ESP32`, builds its
QEMU, builds `BOARD_ESP32S3_SUPERMINI` from this checkout and runs two checks against a
stand-in SlimeVR server on the host:

```sh
qemu/s3.sh                           # everything; work in .pio/qemu-s3
S3_CHECKS=i2spi I2SPI_SCENARIOS="rj45-hub software-cs" qemu/s3.sh
QEMU_XTENSA=/path/to/qemu-system-xtensa qemu/s3.sh   # skip building QEMU
```

It needs PlatformIO, `esptool`, and QEMU's build dependencies (`ninja`, glib, pixman,
libgcrypt, libslirp). CI runs it as the `qemu-s3` job. To move to a newer qemu_esp32,
change the commit in `qemu/QEMU_ESP32`.

- `check_tracker.py`: the build as it is, with its two ICM-45686s on I2C. It boots,
  hashes its own image, drives its LED through the RMT, saves its configuration, finds
  and calibrates both IMUs, joins Wi-Fi, finds the server by broadcast, and streams
  rotations that follow the IMUs as they're turned (within 5 degrees).
- `check_i2spi.py`: the same build with its IMUs on I2SPI chains, one image per board
  configuration in `qemu/i2spi/` (through `SLIMEVR_OVERRIDE_DEFAULTS`):

| Scenario | Configuration | Shows |
|---|---|---|
| rj45-hub | four nodes, strobe (as `BOARD_ESP32C5_RJ45_HUB`) | all four sensors stream rotations |
| chain-hub | a hub IMU on a host pin + two nodes (as `BOARD_SLIMEVR_C5_CHAIN_HUB`) | direct and chained chip selects share one SPI bus |
| channels | two IMUs on one node's channels 0 and 1, one on another node | channels select within a node |
| software-cs | no strobe pin: every transaction framed by `SET_CS` | the bring-up/fallback path |
| two-chains | named chains at 0x13 and 0x14 on one I2C bus, each with its own strobe | one-hot across chains |
| missing-node | four-node build, node 3 not fitted | only its sensor goes; the rest stream |
| misflashed-node | node 2 flashed with node 5's image | logged by name, still used |
| old-nodes | protocol-v2 nodes | refused, never powered or armed |
| empty-cable | no nodes | sensors absent, the tracker carries on |

  In every scenario the emulated parts count any moment two chip selects are asserted
  together; there were none.

What this does not cover: real timing and signal integrity (the cable, CCL delays), the
node firmware itself (the emulated nodes implement the spec independently, as `sim/`'s
do), chained I2C sensors behind gated SCL, magnetometers, and the C5. The C5 boards
share every line of I2SPI and SoftFusion code with the S3 build; what differs is their
Wi-Fi band selection and pin map.

The software-cs scenario found a host bug: with no strobe, nodes were never told to leave
strobe mode, so they ignored every `SET_CS` and all of the chain's sensors read as absent
(fixed; `sim/` now has the scenario too).

## Requirements

- PlatformIO (`pio`). It needs `api.registry.platformio.org` and
  `dl.registry.platformio.org` reachable to install toolchains.
- Espressif's QEMU: `qemu-system-xtensa` (ESP32, S3) and `qemu-system-riscv32` (C3).
  Release binaries are at <https://github.com/espressif/qemu/releases>; ESP-IDF users can
  run `idf_tools.py install qemu-xtensa qemu-riscv32`. Override the binaries with
  `QEMU_XTENSA` / `QEMU_RISCV32` if they are not on `PATH`.
- `QEMU_TIMEOUT` (default 40 s) bounds each run. The firmware never exits, so reaching
  the timeout is the normal end of a run.

## Adding a scenario

A scenario is `qemu/scenarios/<name>.json`: a full `values` block in `board-defaults.json`
format, which replaces the board's own for that build through the generator's
`SLIMEVR_OVERRIDE_DEFAULTS` hook. Add a `<name>.expect` with one regular expression per line
that must appear in the serial log, and list it in `qemu/scenarios.txt`.

## Status

`run.sh` is unchanged from its first version and has not been re-run against stock QEMU
since. The qemu_esp32 test cases above run in that repository's CI.

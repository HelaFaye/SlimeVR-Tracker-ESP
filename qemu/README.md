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

Espressif's QEMU emulates the **ESP32, ESP32-S3 and ESP32-C3** CPUs, flash and UART. It does
**not** emulate Wi-Fi, I2C or SPI peripherals, and it has **no ESP32-C5 or C6 machine**.

So a run proves that:

- the image boots and `setup()` completes;
- the firmware survives absent hardware (no Wi-Fi, no sensors) without crashing or
  boot-looping;
- for the `chain` scenario, the I2SPI host code (`ATTinyCSBus`) enumerates an empty chain,
  logs `No ATtiny CS nodes answered`, and carries on. That is the "chain unplugged" path,
  on real ESP32 code generation rather than the host simulator.

It does not exercise sensors, the chain protocol, or networking. Those are covered by
`sim/` (chain protocol, against a modelled chain), `VERIFY.sh` (everything else that runs
on a host) and, eventually, hardware.

The C5 boards share every line of I2SPI code with the S3 build in the `chain` scenario.
What differs is the C5-specific Wi-Fi band selection and the pin map, and QEMU can check
neither.

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

The scripts were written and partly checked in a cloud environment without QEMU and with
PlatformIO's registry blocked. The log checker was tested against a clean log and against a
crash plus reboot loop, the `chain` scenario was run through the board generator, and
`run.sh` was syntax-checked. **No board has been booted in QEMU yet.** The first local
`qemu/run.sh --all` is the real test. Expect to adjust eFuse handling for the C3, or the
flash size, depending on the QEMU release you have.

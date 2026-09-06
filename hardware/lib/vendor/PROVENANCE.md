# Vendored KiCad libraries

Not written here. Copied in because KiCad 7's stock libraries predate these parts.

| File | Source | Provides |
|---|---|---|
| `Espressif.kicad_sym`, `Espressif.pretty/` | Espressif's official `kicad-libraries` | `ESP32-C5-WROOM-1` symbol + footprint, and every other current Espressif module |
| `Mumo.kicad_sym`, `Mumo.pretty/` | the Mumo project | `QMC6309` symbol + footprint, `IMU` LGA-14 land pattern |

## What these settled

**ESP32-C5-WROOM-1 — authoritative.** Espressif's own library, so the pin numbering is as
good as a datasheet. It also corrected a live firmware bug: the module's pins 24 and 25
are `U0RXD/GPIO12` and `U0TXD/GPIO11`, and `BOARD_SLIMEVR_C5_CHAIN_HUB` had SPI MISO and
MOSI on exactly those two GPIOs. That would have fought the console UART on every boot.

**QMC6309 — corrected.** The generated placeholder assumed a DFN-6 with numeric pins. The
real part is a **4-pad WLCSP** with pads `A1`, `A2`, `B1`, `B2`. Not a variation on the
guess; a different package with a different pad count.

## What these did NOT settle

**ICM-45686 — now settled from the datasheet itself** (TDK DS-000577 Rev 1.0). Neither
library has the part, so `pinouts.py` still generates the symbol, but the pin table is now
read off the datasheet rather than guessed, and marked `verified=True`.

The guess it replaced was wrong on 10 of 14 pins. Only the power pins (5 VDDIO, 6 GND,
7 RESV, 8 VDD) happened to be right. Notably `AP_SDO` is pin **1**, not 9; `AP_CS` is
**12**, not 10; and pin 14 is `AP_SDI`, not a second ground. A board built to the guess
would have had MISO, MOSI, SCLK and CS all on the wrong pads.

`Mumo.pretty/IMU.kicad_mod` remains a **BMI160** land pattern by its own description — same
LGA-14 2.5 x 3.0 mm package, different part. The generated footprint is used instead.

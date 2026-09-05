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

**ICM-45686.** Neither library has it. `Mumo.pretty/IMU.kicad_mod` is an LGA-14 land
pattern whose own description cites the **BMI160** datasheet — a different part that
happens to share the LGA-14 2.5 x 3.0 mm package. The land patterns may well be
interchangeable, but "may well be" is not verification, and the pin *functions* certainly
are not the same. The ICM-45686 pinout in `hardware/gen/pinouts.py` remains marked
unverified.

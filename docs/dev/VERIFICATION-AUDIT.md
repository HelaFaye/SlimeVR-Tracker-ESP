# Verification audit

Every load-bearing factual claim in this project, checked against a primary source rather
than recalled. Four were wrong. Two of those were causing bugs in code that already
existed.

Method: primary sources only where possible — Espressif's own documentation and KiCad
library, Microchip datasheets, TDK's ICM-45686 documentation, and the SlimeVR sources
themselves. Where no primary source was reachable, the claim is marked unverifiable rather
than quietly kept.

---

## Wrong, and fixed

### V1 — CCL: PA7 is `LUT1-OUT`, not LUT0's alternate

**Claimed:** "on an 8-pin tinyAVR the only usable CCL output is LUT0's alternate output on
PA7."

**Actual** (ATtiny212/412 datasheet DS40001911B, Table 5-1): PA7 carries **`LUT1-OUT`**.
`LUT0-OUT` sits on PA4, which does not exist on an 8-pin package — that is *why* PA7 is
the only option, not because of an alternate position.

**Impact: real.** The node firmware was written against the wrong claim and configured
`Logic0`, whose output cannot reach a pin on this package. The strobe pass-through — the
mechanism the entire performance argument rests on (DEC-004) — would not have worked.
Changed to `Logic1` and `user::ccl1_event_a`; the event-system routing is still required,
because LUT1's direct pin inputs are on PORTC, absent from an 8-pin part.

The conclusion ("PA7 is the usable CCL output, reached via the event system") survived; the
reasoning behind it did not, and the code followed the reasoning.

### V2 — LCSC part numbers were fabricated

**Claimed:** specific LCSC numbers for every part (`C5736265` for the C5 module,
`C5457057` for the ICM-45686, `C79945` for the ATtiny412, and so on).

**Actual:** these were written from nothing. The single one that could be checked is wrong
— JLCPCB lists ICM-45686-P as **C9900251359**, not `C5457057`.

**Impact: potentially the most expensive item here.** A plausible-but-wrong part number in
a BOM uploaded for assembly gets the wrong component soldered to every board in the order.
All numbers stripped to `None` with a TODO. The BOM now exports an empty LCSC column,
which fails loudly at upload rather than quietly at assembly.

### V3 — ICM-45686 current overstated by ~6x

**Claimed:** ~2.5 mA for gyro + accel active.

**Actual** (TDK documentation): **0.42 mA** in 6-axis low-noise mode, ~0.22 mA low-power.

**Impact: minor but in the wrong direction** — the power budget overstated the cost of the
chain. Per-node draw corrected from ~6 mA to ~4 mA, and the runtime penalty of a two-node
chain from ~12% to ~8%.

### V4 — QMC6309 package (found earlier, recorded here)

**Claimed:** DFN-6, 1.6 × 1.6 mm, numeric pins. **Actual:** 4-pad WLCSP, pads `A1`, `A2`,
`B1`, `B2`. Corrected when the Mumo library arrived.

---

## Verified correct

| Claim | Source | Verdict |
|---|---|---|
| ESP32-C5 has 29 GPIOs, GPIO0–28 | ESP-IDF GPIO reference | ✅ |
| Strapping pins GPIO2, 7, 25, 27, 28 | ESP-IDF GPIO reference | ✅ exactly as used |
| GPIO16–22 are SPI0/1 flash + PSRAM | ESP-IDF GPIO reference | ✅ |
| GPIO13/14 are USB-JTAG | ESP-IDF GPIO reference | ✅ |
| Boot mode set by GPIO26/27/28 | ESP32-C5 datasheet §3 | ✅ — justifies excluding GPIO26 |
| ADC1 on GPIO1–6; battery sense on GPIO1 | ESP-IDF GPIO reference | ✅ GPIO1 = ADC1_CH0 |
| ICM-45686 is 14-pin LGA 2.5 × 3.0 mm | TDK documentation | ✅ |
| ICM-45686 has a dual interface with an AUX port for a magnetometer | TDK documentation | ✅ — DEC-008 holds |
| ATtiny412 TWI has no alternate pin position on 8-pin parts | Microchip TWI documentation | ✅ SDA/SCL fixed at PA1/PA2 |
| tinyAVR 1-series CCL has two LUTs | Microchip application note | ✅ |
| ATtiny4/5/9/10 have no serial peripheral | Microchip product pages | ✅ DEC-009 holds |
| Espressif QEMU supports ESP32/S3/C3 only, no Wi-Fi or I2C/SPI peripherals | Espressif QEMU docs | ✅ |
| pioarduino platform ships an `esp32-c5-devkitc-1` board | pioarduino releases | ✅ DEC-001 holds |
| SlimeVR UDP port 6969; packet ids 0/3/15/17 | `packets.h`, `TrackersUDPServer.kt` | ✅ read from source |
| `TrackerPosition` has `LEFT_HAND` = 17, `RIGHT_HAND` = 18 | `TrackerPosition.kt` | ✅ |
| 15 finger bones per hand | `TrackerPosition.kt` | ✅ |
| `FORCE_ARMS_FROM_HMD` defaults true | `SkeletonConfigToggles.java` | ✅ (corrected earlier) |
| ICM-45686 `WHO_AM_I` = `0xE9` at `0x72` | `icm45686.h` in this tree | ✅ shipping driver |
| QMC6309 device id `0x7c`, `WHO_AM_I` `0x90` at reg `0x00` | `magdriver.cpp` in this tree | ✅ shipping driver |

---

## New risks the verification surfaced

### R1 — GPIO15 may not exist on the module we picked

Espressif's DevKitC-1 guide: *"In modules integrated with SPI PSRAM, this pin is already
used for SPICS1 function, thus unavailable for external use. In modules without SPI PSRAM,
this pin can be used as GPIO15."*

`BOARD_SLIMEVR_C5_CHAIN_HUB` uses **GPIO15 for the local IMU interrupt**. If the specific
ESP32-C5-WROOM-1 variant ordered has PSRAM, that pin is gone. The interrupt is optional in
this firmware (the driver polls the FIFO), so the failure is degraded rather than fatal —
but it should be a deliberate choice. Move it to GPIO24 if in doubt.

### R2 — `i2cscan` probes the console UART pins

The C5 port array includes GPIO11 and GPIO12, which are `U0TXD`/`U0RXD` on the
ESP32-C5-WROOM-1 module. Probing them toggles the console during a scan. Harmless at the
chip level, confusing at the bench. Worth excluding for module-based boards.

*(This is the same fact that caught the MISO/MOSI misassignment — the module's pin 24/25
mapping. The board config is fixed; the scan table is not.)*

---

## Unverifiable here

| Claim | Why |
|---|---|
| Flat ribbon capacitance ≈ 50–70 pF/m per conductor | Varies by cable construction; measure yours |
| 26 AWG ≈ 0.14 Ω/m | Standard wire table, but patch-cable conductor gauge is not guaranteed |
| JLCPCB panel maximum 400 × 500 mm, V-score constraints | Fabricator policy, changes without notice — confirm at order time |
| ICM-45686 pin numbering | No datasheet reached. **Still the only unverified pinout**, and the one that matters most |
| megaTinyCore `Event`/`Logic` API names | Version-dependent; first compile is the test |
| `WiFi.setBandMode` availability in pioarduino | Depends on the Arduino-ESP32 revision the platform ships |

---

## What this pass says about the project

Four wrong claims out of roughly thirty checked. Two were inert documentation errors; two
were live — the CCL LUT number had already been coded against, and the fabricated part
numbers would have reached a factory.

Both live failures share a shape: a conclusion that was *correct* resting on reasoning that
was *wrong*. "PA7 is the CCL output pin" is true; "because it is LUT0's alternate" is not,
and the code followed the reasoning rather than the conclusion. That is the same failure as
the `forceArmsFromHMD` polarity error earlier in this project — inferring from a name
instead of reading the definition.

The mitigation that keeps working is mechanical: `verify.py` catches wrong library
identifiers, the dangling-net check catches unconnected pins, the simulation catches
protocol disagreements, and the `verified` flags catch pinouts nobody checked. None of
those rely on remembering to be careful.

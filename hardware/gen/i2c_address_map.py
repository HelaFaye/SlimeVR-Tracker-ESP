#!/usr/bin/env python3
"""
Which I2C addresses can an I2SPI chain safely use?

The chain's SDA/SCL are shared with whatever else is on the tracker's I2C bus, so node
controller addresses must not collide with any sensor the firmware supports, with common
parts someone might add, or with the addresses the I2C specification reserves.

This computes the answer from the firmware itself rather than from memory: sensor
addresses are parsed out of the driver headers, so the map cannot drift from the code.

    python3 hardware/gen/i2c_address_map.py            # print the map and the whitelist
    python3 hardware/gen/i2c_address_map.py --check    # fail if the configured base collides
"""

import argparse
import glob
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Reserved by the I2C specification: 0x00-0x07 (general call, CBUS, 10-bit prefix) and
# 0x78-0x7F (10-bit addressing). Never usable, whatever else is on the bus.
RESERVED = set(range(0x00, 0x08)) | set(range(0x78, 0x80))

# Parts that are not in this firmware but turn up on hobbyist I2C buses often enough that
# claiming their address would be a trap. Curated by hand; add to it rather than assume.
COMMON = {
    0x0D: "QMC5883L magnetometer",
    0x1C: "LIS3MDL magnetometer",
    0x1D: "ADXL345 / LIS3DH",
    0x1E: "HMC5883L magnetometer",
    0x30: "MMC5983MA magnetometer",
    0x39: "APDS9960",
    0x3C: "SSD1306 OLED",
    0x3D: "SSD1306 OLED",
    0x40: "INA219 / Si7021 / HTU21",
    0x41: "INA219",
    0x44: "SHT3x / INA219",
    0x45: "SHT3x",
    0x48: "ADS1115 / LM75",
    0x49: "ADS1115 / LM75",
    0x53: "ADXL345",
    0x57: "MAX3010x / EEPROM",
    0x5A: "CCS811 / MLX90614",
    0x6C: "IST8310 magnetometer",
    0x6D: "IST8310 magnetometer",
}
for _a in range(0x50, 0x58):
    COMMON.setdefault(_a, "24Cxx EEPROM")
for _a in range(0x60, 0x68):
    COMMON.setdefault(_a, "MCP4725 DAC / ATECC608")


def firmware_addresses():
    """Parse every I2C address this firmware actually uses out of the source."""
    used = {}

    def mark(addr, who):
        used.setdefault(addr, set()).add(who)

    for path in glob.glob(str(ROOT / "src/sensors/softfusion/drivers/*.h")) + [
        str(ROOT / "src/sensors/bno055sensor.h")
    ]:
        text = Path(path).read_text()
        m = re.search(r"Address\s*=\s*(0x[0-9a-fA-F]+)", text)
        if not m:
            continue
        name = Path(path).stem
        base = int(m.group(1), 16)
        # Every one of these parts has an address-select pin giving base or base+1.
        mark(base, name)
        mark(base + 1, f"{name} (AD0 high)")

    mag = (ROOT / "src/sensors/softfusion/magdriver.cpp").read_text()
    for m in re.finditer(
        r'\.name = "([^"]+)"[\s\S]{0,120}?\.deviceId = (0x[0-9a-fA-F]+)', mag
    ):
        mark(int(m.group(2), 16), m.group(1))

    for a in (0x4A, 0x4B):
        mark(a, "BNO08x")
    for a in range(0x20, 0x28):
        mark(a, "MCP23x17 expander")
    for a in range(0x70, 0x78):
        mark(a, "PCA954x mux")
    return used


def busy_map():
    used = firmware_addresses()
    out = {}
    for a in range(0x00, 0x80):
        why = []
        if a in RESERVED:
            why.append("I2C reserved")
        if a in used:
            why += sorted(used[a])
        if a in COMMON:
            why.append(COMMON[a])
        if why:
            out[a] = why
    return out


def clear_windows(size, busy):
    """Base addresses where `size` consecutive addresses are all free."""
    return [
        b
        for b in range(0x08, 0x78)
        if b + size - 1 <= 0x77 and all(a not in busy for a in range(b, b + size))
    ]


def runs(addrs):
    out = []
    for a in addrs:
        if out and a == out[-1][-1] + 1:
            out[-1].append(a)
        else:
            out.append([a])
    return out


def configured_base():
    text = (ROOT / "src/sensorinterface/ATTinyCSProtocol.h").read_text()
    base = int(re.search(r"DefaultBaseAddress = (0x[0-9a-fA-F]+)", text).group(1), 16)
    span = int(re.search(r"AddressSpan = (\d+)", text).group(1))
    return base, span


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit non-zero on a collision")
    args = ap.parse_args()

    busy = busy_map()

    if not args.check:
        print("Occupied I2C addresses (firmware + common parts + spec reserved):\n")
        for a in sorted(busy):
            print(f"  0x{a:02X}  {', '.join(busy[a])}")
        print()
        for n in (16, 9, 5, 2, 1):
            w = clear_windows(n, busy)
            label = f"{n} consecutive"
            if w:
                spans = ", ".join(
                    f"0x{r[0]:02X}" if len(r) == 1 else f"0x{r[0]:02X}-0x{r[-1]:02X}"
                    for r in runs(w)
                )
            else:
                spans = "NO CLEAR WINDOW"
            print(f"  {label:>16}: {spans}")
        print()

    base, span = configured_base()
    collisions = {a: busy[a] for a in range(base, base + span) if a in busy}
    print(f"Configured: base 0x{base:02X}, span {span} (0x{base:02X}-0x{base + span - 1:02X})")
    if collisions:
        for a, why in sorted(collisions.items()):
            print(f"  COLLISION 0x{a:02X}: {', '.join(why)}")
        return 1
    print("  no collisions")
    return 0


if __name__ == "__main__":
    sys.exit(main())

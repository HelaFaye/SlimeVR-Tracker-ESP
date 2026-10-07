#!/usr/bin/env python3
"""
Recompute every quantified claim in the docs from the constants in the source.

The docs are full of numbers - timing budgets, panel dimensions, current draw, bus
loading. Numbers written by hand go stale the moment a constant changes, and a stale
number in a design doc is worse than no number because it gets trusted. This recomputes
them and fails if a doc disagrees.

    python3 sim/check_numbers.py

Physical constants that cannot be derived (wire resistance, cable capacitance, datasheet
current draw) are declared here with their provenance so at least they live in one place.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

failures = []
checks = 0


def check(name, computed, documented, tolerance=0.05, unit=""):
    """Compare a computed value against what the docs claim."""
    global checks
    checks += 1
    if documented is None:
        print(f"  [--] {name}: {computed:g}{unit} (not stated in docs)")
        return
    rel = abs(computed - documented) / max(abs(documented), 1e-12)
    ok = rel <= tolerance
    mark = "ok" if ok else "FAIL"
    print(
        f"  [{mark}] {name}: computed {computed:.4g}{unit}, "
        f"documented {documented:g}{unit}"
        + ("" if ok else f"  <-- off by {rel * 100:.0f}%")
    )
    if not ok:
        failures.append(name)


def source_constant(path, pattern, cast=int):
    text = (ROOT / path).read_text()
    m = re.search(pattern, text)
    if not m:
        failures.append(f"constant not found: {pattern} in {path}")
        return None
    return cast(m.group(1))


# ------------------------------------------------------------ source constants

PROTO = "src/sensorinterface/ATTinyCSProtocol.h"
base_addr = source_constant(PROTO, r"DefaultBaseAddress = (0x[0-9A-Fa-f]+)",
                            lambda s: int(s, 16))
addr_span = source_constant(PROTO, r"AddressSpan = (\d+)")
frame_len = source_constant(PROTO, r"FrameLength = (\d+)")
addr_min = source_constant(PROTO, r"AddressMin = (0x[0-9A-Fa-f]+)", lambda s: int(s, 16))
addr_max = source_constant(PROTO, r"AddressMax = (0x[0-9A-Fa-f]+)", lambda s: int(s, 16))
max_node = source_constant(PROTO, r"MaxNodeId = (\d+)")
max_chan = source_constant(PROTO, r"MaxChannels = (\d+)")
settle_ms = source_constant(PROTO, r"SensorPowerOnSettleMillis = (\d+)")
identity_len = source_constant(PROTO, r"IdentityLength = (\d+)")

# ------------------------------------------------- declared physical constants
#
# Not derivable. Provenance in the comment; challenge these, not the arithmetic.

I2C_FAST_HZ = 400_000          # I2C Fast mode
I2C_FASTPLUS_HZ = 1_000_000    # Fast mode Plus
SPI_HZ = 4_000_000             # our conservative over-cable clock
AWG26_OHM_PER_M = 0.1339       # standard wire table, 26 AWG copper at 20 C
RIBBON_PF_PER_M = 60           # midpoint of the 50-70 pF/m range; MEASURE YOURS
I2C_BUS_PF_BUDGET = 400        # I2C spec, Fast mode
IMU_MA = 0.42                  # TDK ICM-45686, 6-axis low-noise mode
MAG_MA = 2.0                   # QMC6309 datasheet Table 2: ODR=200 Hz, OSR1=8 (high
                               # power) = 2000 uA. The firmware writes 0x0a=0x21 which
                               # selects OSR1=8, and 0x0b=0x48 which selects 200 Hz.
ATTINY_MA = 3.0                # ATtiny412 at 5 MHz / 3.3 V - ESTIMATE
HUB_MA = 100                   # ESP32-C5 Wi-Fi connected average - ESTIMATE, varies wildly

LONGEST_CHAIN_M = 0.85         # thigh -> lower leg -> foot, per the example build
FIFO_BURST_BYTES = 20          # one packet plus register address


def i2c_write_us(payload_bytes, hz):
    """Start + (n bytes x 9 bits with ACK) + stop. The bit either side of the frame is
    the usual approximation for START and STOP."""
    bits = 1 + payload_bytes * 9 + 1
    return bits / hz * 1e6


def spi_transfer_us(nbytes, hz):
    return nbytes * 8 / hz * 1e6


print("Protocol constants read from source:")
print(f"  base address 0x{base_addr:02X}, nodes 1..{max_node}, {max_chan} channels")
print(f"  usable I2C range 0x{addr_min:02X}..0x{addr_max:02X}")
print(f"  identity block {identity_len} bytes, power settle {settle_ms} ms")

# ----------------------------------------------------------------- addressing

print("\nAddressing")
check("addresses occupied by the whole chain", addr_span, 1, 0, "")
checks += 1
if addr_min <= base_addr <= addr_max:
    print(f"  [ok] 0x{base_addr:02X} is inside the usable range "
          f"0x{addr_min:02X}..0x{addr_max:02X}")
else:
    failures.append("chain address outside the usable I2C range")

# The address must be on the vetted whitelist, not merely free today.
checks += 1
wl = re.search(r"AddressWhitelist\[\] = \{([^}]*)\}",
               (ROOT / PROTO).read_text()).group(1)
whitelist = [int(x.strip(), 16) for x in wl.split(",") if x.strip()]
if base_addr in whitelist:
    print(f"  [ok] 0x{base_addr:02X} is on the vetted whitelist "
          f"({len(whitelist)} entries)")
else:
    failures.append(f"chain address 0x{base_addr:02X} is not on the whitelist")
    print(f"  [FAIL] 0x{base_addr:02X} is not on the whitelist")

checks += 1
packed_max = ((max_node & 0x0F) << 4) | ((max_chan - 1) & 0x0F)
if packed_max > 0xFF:
    failures.append("packTarget overflows a byte")
    print("  [FAIL] packTarget overflows a byte")
else:
    print(f"  [ok] packTarget(max) = 0x{packed_max:02X}, fits in one byte")

check("max addressable sensors", max_node * max_chan, 240, 0, "")

# --------------------------------------------------------------------- timing

print(f"\nBus timing (v3 frame is {frame_len} bytes: opcode, target, value,\n        plus the address byte)")
arm_400 = i2c_write_us(frame_len, I2C_FAST_HZ)
arm_1m = i2c_write_us(frame_len, I2C_FASTPLUS_HZ)
check("ARM write at 400 kHz", arm_400, 70, 0.10, " us")
check("ARM write at 1 MHz", arm_1m, 30, 0.15, " us")

softcs_400 = i2c_write_us(frame_len, I2C_FAST_HZ) * 2
check("software CS assert+deassert at 400 kHz", softcs_400, 145, 0.05, " us")

fifo_us = spi_transfer_us(FIFO_BURST_BYTES, SPI_HZ)
check("one FIFO burst at 4 MHz", fifo_us, 40, 0.05, " us")

print("\nPoll cycle, 4 sensors at 200 Hz (5 ms period)")
cycle_us = 5000
i2c_4 = 4 * arm_400
check("I2C per cycle", i2c_4, 280, 0.10, " us")
check("as a fraction of the cycle", i2c_4 / cycle_us * 100, 5.6, 0.10, " %")

print("\nPoll cycle, 16 sensors at 200 Hz")
i2c_16_400 = 16 * arm_400
i2c_16_1m = 16 * arm_1m
spi_16 = 16 * fifo_us
check("I2C at 400 kHz", i2c_16_400 / 1000, 1.2, 0.10, " ms")
check("I2C at 1 MHz", i2c_16_1m / 1000, 0.48, 0.15, " ms")
check("SPI at 4 MHz", spi_16 / 1000, 0.64, 0.05, " ms")
check("total at 400 kHz", (i2c_16_400 + spi_16) / 1000, 1.85, 0.10, " ms")
check("fraction of a 200 Hz cycle at 400 kHz",
      (i2c_16_400 + spi_16) / cycle_us * 100, 37, 0.10, " %")
check("fraction of a 100 Hz cycle at 1 MHz",
      (i2c_16_1m + spi_16) / 10000 * 100, 11, 0.15, " %")

# ---------------------------------------------------------------- electrical

print("\nElectrical")
node_ma = IMU_MA + MAG_MA + ATTINY_MA
check("per-node current", node_ma, 5.4, 0.05, " mA")
two_node_ma = 2 * node_ma
check("two-node chain", two_node_ma, 10.8, 0.05, " mA")
check("runtime penalty, two-node chain",
      two_node_ma / (HUB_MA + IMU_MA + MAG_MA) * 100, 10.4, 0.10, " %")
check("runtime penalty, one-node chain",
      node_ma / (HUB_MA + IMU_MA + MAG_MA) * 100, 5.2, 0.10, " %")

# Both conductors carry the current: VBUS out and GND back.
drop_mv = two_node_ma / 1000 * LONGEST_CHAIN_M * AWG26_OHM_PER_M * 2 * 1000
check("supply drop over the longest chain (both conductors)", drop_mv, 2.5, 0.10, " mV")

cable_pf = LONGEST_CHAIN_M * RIBBON_PF_PER_M
check("I2C cable capacitance, longest chain", cable_pf, 51, 0.10, " pF")
checks += 1
if cable_pf < I2C_BUS_PF_BUDGET:
    print(f"  [ok] {cable_pf:.0f} pF is inside the {I2C_BUS_PF_BUDGET} pF Fast-mode budget")
else:
    failures.append("cable capacitance exceeds the I2C budget")

check("six 4k7 pull-ups in parallel", 4700 / 6, 783, 0.02, " ohm")

# --------------------------------------------------------------- power staging

print("\nPower staging")
check("settle time, 8 extensions", 8 * settle_ms, 120, 0, " ms")
check("settle time, 4-node chain", 4 * settle_ms, 60, 0, " ms")

# Build totals (BOM placements, panel) moved to the hardware repo,
# HelaFaye/SlimeVR-Tracker-ESP-Hardware: gen/check_build_totals.py.

# --------------------------------------------------- firmware/table consistency

print("\nFirmware table consistency")
scan = (ROOT / "lib/i2cscan/i2cscan.cpp").read_text()
m = re.search(r"ESP32C5.*?portArray = \{([^}]*)\}", scan, re.S)
arr = [int(x) for x in m.group(1).split(",")]
m2 = re.search(r"ESP32C5.*?std::array<uint8_t, (\d+)> portArray", scan, re.S)
declared = int(m2.group(1))
check("C5 portArray declared size matches contents", len(arr), declared, 0, "")
m3 = re.search(r"ESP32C5.*?std::array<std::string, (\d+)> portMap", scan, re.S)
check("C5 portMap size matches portArray", int(m3.group(1)), len(arr), 0, "")

# Espressif: strapping 2,7,25,27,28; flash 16-22; USB-JTAG 13,14; boot mode 26,27,28.
forbidden = set([2, 3, 7, 25, 26, 27, 28]) | set(range(16, 23)) | {13, 14}
checks += 1
bad = sorted(set(arr) & forbidden)
if bad:
    failures.append(f"C5 scan array includes reserved GPIOs {bad}")
    print(f"  [FAIL] C5 scan array includes reserved GPIOs: {bad}")
else:
    print(f"  [ok] C5 scan array avoids all reserved GPIOs")

# The module puts UART0 on GPIO11/12 even though the bare chip leaves them free.
checks += 1
uart = sorted(set(arr) & {11, 12})
if uart:
    failures.append(f"C5 scan array includes module UART pins {uart}")
    print(f"  [FAIL] C5 scan array includes module UART pins {uart}")
else:
    print("  [ok] C5 scan array avoids the module console UART (GPIO11/12)")

print(f"\n{checks} checks, {len(failures)} failed")
for f in failures:
    print(f"  - {f}")
sys.exit(1 if failures else 0)

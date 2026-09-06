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
MAG_MA = 0.5                   # QMC6309 continuous - ESTIMATE, not datasheet-checked
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
check("top unicast address", base_addr + max_node, 0x3F, 0, "")
if base_addr + max_node > addr_max:
    failures.append("node addresses run past AddressMax")
    print("  [FAIL] node address range exceeds the usable I2C range")
else:
    checks += 1
    print(f"  [ok] 0x{base_addr:02X}..0x{base_addr + max_node:02X} fits inside "
          f"0x{addr_min:02X}..0x{addr_max:02X}")

checks += 1
packed_max = ((max_node & 0x0F) << 4) | ((max_chan - 1) & 0x0F)
if packed_max > 0xFF:
    failures.append("packTarget overflows a byte")
    print("  [FAIL] packTarget overflows a byte")
else:
    print(f"  [ok] packTarget(max) = 0x{packed_max:02X}, fits in one byte")

check("max addressable sensors", max_node * max_chan, 240, 0, "")

# --------------------------------------------------------------------- timing

print("\nBus timing (ARM is 3 bytes: address, opcode, payload)")
arm_400 = i2c_write_us(3, I2C_FAST_HZ)
arm_1m = i2c_write_us(3, I2C_FASTPLUS_HZ)
check("ARM write at 400 kHz", arm_400, 70, 0.10, " us")
check("ARM write at 1 MHz", arm_1m, 30, 0.15, " us")

softcs_400 = i2c_write_us(3, I2C_FAST_HZ) * 2
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
check("per-node current", node_ma, 4, 0.10, " mA")
two_node_ma = 2 * node_ma
check("two-node chain", two_node_ma, 8, 0.10, " mA")
check("runtime penalty, two-node chain",
      two_node_ma / (HUB_MA + IMU_MA + MAG_MA) * 100, 8, 0.15, " %")
check("runtime penalty, one-node chain",
      node_ma / (HUB_MA + IMU_MA + MAG_MA) * 100, 4, 0.15, " %")

# Both conductors carry the current: VBUS out and GND back.
drop_mv = two_node_ma / 1000 * LONGEST_CHAIN_M * AWG26_OHM_PER_M * 2 * 1000
check("supply drop over the longest chain (both conductors)", drop_mv, 1.8, 0.10, " mV")

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
check("settle time, 8 extensions", 8 * settle_ms, 80, 0, " ms")
check("settle time, 4-node chain", 4 * settle_ms, 40, 0, " ms")

# ------------------------------------------------------------- build totals

print("\nBuild totals")
sys.path.insert(0, str(ROOT / "hardware" / "gen"))
import boards as B  # noqa: E402

hub_n = len(B.BOARDS["hub"]["comps"])
node_n = len(B.BOARDS["node"]["comps"])
check("BOM placements, 5 hubs + 8 nodes", 5 * hub_n + 8 * node_n, 293, 0, "")

hub_w, hub_h = B.BOARDS["hub"]["size_mm"]
node_w, node_h = B.BOARDS["node"]["size_mm"]
import panel as P  # noqa: E402

sel = {"hub": 5, "node": 8}
cols, rows, cw, ch = P.layout(sel)
check("panel cell width", cw, 45.4, 0.01, " mm")
check("panel cell height", ch, 30.4, 0.01, " mm")
check("panel width", cols * cw + 2 * P.PANEL_RAIL_MM, 373.2, 0.01, " mm")
check("panel height", rows * ch + 2 * P.PANEL_RAIL_MM, 70.8, 0.01, " mm")
checks += 1
if cols * rows >= sum(sel.values()):
    print(f"  [ok] {cols}x{rows} grid holds {sum(sel.values())} boards")
else:
    failures.append("panel grid too small")

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
forbidden = set([2, 7, 25, 27, 28]) | set(range(16, 23)) | {13, 14} | {26}
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
    print(f"  [--] C5 scan array includes module UART pins {uart} (risk R2, known)")

print(f"\n{checks} checks, {len(failures)} failed")
for f in failures:
    print(f"  - {f}")
sys.exit(1 if failures else 0)

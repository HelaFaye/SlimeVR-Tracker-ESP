#!/usr/bin/env python3
"""
Recompute the quantified claims in the docs from the constants in the source.

The docs are full of numbers - timing budgets, current draw, bus loading. Numbers written
by hand go stale the moment a constant changes, and a stale number in a design doc is
worse than no number because it gets trusted. This recomputes them and fails if one moves
away from the figure the docs state.

It does not read the docs. Each `documented` value below is the figure as written in the
doc named in its section; change both together. A doc figure with no check here is
unchecked.

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
AWG32_OHM_PER_M = 0.538        # 32 AWG copper. Flat 8P8C patch cable (I2SPI.md §2.1) is
                               # commonly 32 AWG stranded; round patch cable 24-26 AWG.
CABLE_OHM_PER_M = AWG32_OHM_PER_M  # design on the worst cable §2.1 allows
RIBBON_PF_PER_M = 60           # midpoint of the 50-70 pF/m range; MEASURE YOURS
I2C_BUS_PF_BUDGET = 400        # I2C spec, Fast mode
IMU_MA = 0.42                  # TDK ICM-45686, 6-axis low-noise mode
MAG_MA = 2.0                   # QMC6309 datasheet Table 2: ODR=200 Hz, OSR1=8 (high
                               # power) = 2000 uA. The firmware writes 0x0a=0x21 which
                               # selects OSR1=8, and 0x0b=0x48 which selects 200 Hz.
ATTINY_MA = 3.0                # ATtiny412 at 5 MHz / 3.3 V - ESTIMATE
HUB_MA = 100                   # ESP32-C5 Wi-Fi connected average - ESTIMATE, varies wildly

LONGEST_CHAIN_M = 0.85         # thigh -> lower leg -> foot, per the example build
# One ICM-45686 visit (icm45base.h bulkRead): FIFO_COUNT read (address + 2 bytes) as its
# own transaction, then at least one 20-byte packet (FullFifoEntrySize) plus address.
# Wire time only: SPIImpl transfers byte by byte, so real time is longer.
FIFO_COUNT_BYTES = 3
FIFO_PACKET_BYTES = 21
FIFO_BURST_BYTES = FIFO_COUNT_BYTES + FIFO_PACKET_BYTES


def i2c_write_us(payload_bytes, hz):
    """Start + address byte + payload bytes (9 bits each with ACK) + stop. The bit either
    side of the frame is the usual approximation for START and STOP.

    The address byte was left out until 2026-10-13, which understated every ARM figure
    by a quarter (72.5 us instead of 95 us at 400 kHz)."""
    bits = 1 + (1 + payload_bytes) * 9 + 1
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
check("ARM write at 400 kHz", arm_400, 95, 0.02, " us")
check("ARM write at 1 MHz", arm_1m, 38, 0.02, " us")

softcs_400 = i2c_write_us(frame_len, I2C_FAST_HZ) * 2
check("software CS assert+deassert at 400 kHz", softcs_400, 190, 0.02, " us")

fifo_us = spi_transfer_us(FIFO_BURST_BYTES, SPI_HZ)
check("one sensor's FIFO visit at 4 MHz (count + one packet)", fifo_us, 48, 0.02, " us")

print("\nPoll cycle, 4 sensors at 200 Hz (5 ms period)")
cycle_us = 5000
i2c_4 = 4 * arm_400
check("I2C per cycle", i2c_4, 380, 0.02, " us")
check("as a fraction of the cycle", i2c_4 / cycle_us * 100, 7.6, 0.02, " %")

print("\nPoll cycle, 16 sensors at 200 Hz")
i2c_16_400 = 16 * arm_400
i2c_16_1m = 16 * arm_1m
spi_16 = 16 * fifo_us
check("I2C at 400 kHz", i2c_16_400 / 1000, 1.52, 0.02, " ms")
check("I2C at 1 MHz", i2c_16_1m / 1000, 0.61, 0.02, " ms")
check("SPI at 4 MHz", spi_16 / 1000, 0.77, 0.02, " ms")
check("total at 400 kHz", (i2c_16_400 + spi_16) / 1000, 2.29, 0.02, " ms")
check("total at 1 MHz", (i2c_16_1m + spi_16) / 1000, 1.38, 0.02, " ms")
check("fraction of a 200 Hz cycle at 400 kHz",
      (i2c_16_400 + spi_16) / cycle_us * 100, 46, 0.02, " %")
check("fraction of a 200 Hz cycle at 1 MHz",
      (i2c_16_1m + spi_16) / cycle_us * 100, 27.5, 0.02, " %")
check("fraction of a 100 Hz cycle at 400 kHz",
      (i2c_16_400 + spi_16) / 10000 * 100, 23, 0.02, " %")
check("fraction of a 100 Hz cycle at 1 MHz",
      (i2c_16_1m + spi_16) / 10000 * 100, 14, 0.02, " %")

# ---------------------------------------------------------------- electrical

print("\nElectrical")
node_ma = IMU_MA + MAG_MA + ATTINY_MA
check("per-node current", node_ma, 5.4, 0.05, " mA")
two_node_ma = 2 * node_ma
check("two-node chain", two_node_ma, 10.8, 0.05, " mA")
check("runtime penalty, two-node chain",
      two_node_ma / (HUB_MA + IMU_MA + MAG_MA) * 100, 10.6, 0.02, " %")
check("runtime penalty, one-node chain",
      node_ma / (HUB_MA + IMU_MA + MAG_MA) * 100, 5.3, 0.02, " %")

# Both conductors carry the current: VBUS out and GND back.
drop_mv = two_node_ma / 1000 * LONGEST_CHAIN_M * CABLE_OHM_PER_M * 2 * 1000
check("supply drop over the longest chain (both conductors, 32 AWG)", drop_mv, 9.9, 0.02,
      " mV")
check("cable round-trip resistance, 32 AWG", CABLE_OHM_PER_M * 2, 1.08, 0.02, " ohm/m")
check("six reference nodes", 6 * node_ma, 32.5, 0.02, " mA")
check("their drop per metre, 32 AWG", 6 * node_ma * CABLE_OHM_PER_M * 2, 35, 0.02, " mV")

cable_pf = LONGEST_CHAIN_M * RIBBON_PF_PER_M
check("I2C cable capacitance, longest chain", cable_pf, 51, 0.10, " pF")
checks += 1
if cable_pf < I2C_BUS_PF_BUDGET:
    print(f"  [ok] {cable_pf:.0f} pF is inside the {I2C_BUS_PF_BUDGET} pF Fast-mode budget")
else:
    failures.append("cable capacitance exceeds the I2C budget")

check("six 4k7 pull-ups in parallel", 4700 / 6, 783, 0.02, " ohm")

# ------------------------------------------------------- limits (I2SPI.md §14)
#
# Declared here, not derivable. ESTIMATES are marked; measure them at bring-up.

VDD = 3.3
I2C_FAST_RISE_NS = 300         # I2C spec, Fast mode, max rise time 30%->70%
I2C_FAST_SINK_MA = 3           # I2C spec, Fast mode, VOL 0.4 V at 3 mA
I2C_VOL = 0.4
I2C_FMP_RISE_NS = 120          # I2C spec, Fast-mode Plus
I2C_FMP_SINK_MA = 20           # I2C spec, Fast-mode Plus, VOL 0.4 V at 20 mA
PULLUP_DEFAULT_OHM = 2200      # I2SPI.md §3.1 host default
NODE_PF = 15                   # per node per I2C line: MCU pin, two jacks, traces - ESTIMATE
SUPPLY_DROP_BUDGET_MV = 100    # what we allow VBUS to sag end to end - a choice
CAMERA_NODE_MA = 80            # small SPI camera module, active - ESTIMATE, varies 2-3x
QVGA_GREY_BYTES = 320 * 240
LONG_CHAIN_M = 2.0

print("\nLimits (I2SPI.md §14)")
whitelist = (ROOT / PROTO).read_text()
whitelist = re.search(r"AddressWhitelist\[\] = \{([^}]*)\}", whitelist).group(1)
chains_per_bus = len([a for a in whitelist.split(",") if a.strip()])
check("chains sharing one I2C bus", chains_per_bus, 7, 0, "")
check("targets on one I2C bus", chains_per_bus * max_node * max_chan, 1680, 0, "")
check("power staging, full chain", max_node * settle_ms, 225, 0, " ms")
# IDENTIFY (a frame) then a 4-byte read (address + 4 bytes) for each id 1..15.
probe_ms = max_node * (arm_400 + i2c_write_us(identity_len, I2C_FAST_HZ)) / 1000
check("probing ids 1..15 at 400 kHz", probe_ms, 3.2, 0.02, " ms")

per_400 = arm_400 + fifo_us
per_1m = arm_1m + fifo_us
per_100 = i2c_write_us(frame_len, 100_000) + fifo_us
check("per-sensor cost at 400 kHz", per_400, 143, 0.02, " us")
check("per-sensor cost at 1 MHz", per_1m, 86, 0.02, " us")
check("sensors at 200 Hz, whole cycle, 400 kHz", int(cycle_us // per_400), 34, 0, "")
check("sensors at 200 Hz, whole cycle, 1 MHz", int(cycle_us // per_1m), 58, 0, "")
check("sensors at 200 Hz, half the cycle, 400 kHz", int(cycle_us / 2 // per_400), 17, 0, "")
check("sensors at 200 Hz, half the cycle, 1 MHz", int(cycle_us / 2 // per_1m), 29, 0, "")
check("ARM at 100 kHz", i2c_write_us(frame_len, 100_000), 380, 0.02, " us")
check("sensors at 200 Hz, half the cycle, 100 kHz", int(cycle_us / 2 // per_100), 5, 0, "")

# An SPI magnetometer on its own node channel (§4.5 B): every MagTs (10 ms, so every
# other 200 Hz cycle) one ARM to the mag, one back to the IMU, and a 7-byte read.
mag_b_us = (2 * arm_400 + spi_transfer_us(7, SPI_HZ)) / 2
check("SPI mag on a node channel, per 5 ms cycle at 400 kHz", mag_b_us, 102, 0.02, " us")
check("sensors with such a mag, half the cycle, 400 kHz",
      int(cycle_us / 2 // (per_400 + mag_b_us)), 10, 0, "")

# Rise time on an RC: 30% -> 70% takes 0.8473 RC.
def c_max_pf(r_ohm, rise_ns=I2C_FAST_RISE_NS):
    return rise_ns * 1e-9 / (0.8473 * r_ohm) * 1e12

r_min = (VDD - I2C_VOL) / (I2C_FAST_SINK_MA / 1000)
r_min_fmp = (VDD - I2C_VOL) / (I2C_FMP_SINK_MA / 1000)
check("bus capacitance at 400 kHz with the 2.2k default", c_max_pf(PULLUP_DEFAULT_OHM),
      160, 0.02, " pF")
check("strongest Fast-mode pull-up (3 mA sink)", r_min, 970, 0.02, " ohm")
check("bus capacitance at 400 kHz with that pull-up", c_max_pf(r_min), 365, 0.02, " pF")
check("cable left for 2 nodes, 2.2k", (c_max_pf(PULLUP_DEFAULT_OHM) - 2 * NODE_PF)
      / RIBBON_PF_PER_M, 2.2, 0.05, " m")
check("cable left for 15 nodes, strongest pull-up", (c_max_pf(r_min) - 15 * NODE_PF)
      / RIBBON_PF_PER_M, 2.35, 0.05, " m")
check("Fast-mode Plus: bus capacitance with the 2.2k default",
      c_max_pf(PULLUP_DEFAULT_OHM, I2C_FMP_RISE_NS), 64, 0.02, " pF")
check("Fast-mode Plus: strongest pull-up (20 mA sink)", r_min_fmp, 145, 0.02, " ohm")
full_2m_pf = 15 * NODE_PF + LONG_CHAIN_M * RIBBON_PF_PER_M
check("full chain plus 2 m of cable", full_2m_pf, 345, 0.02, " pF")
check("Fast-mode Plus: pull-up that drives it",
      I2C_FMP_RISE_NS * 1e-9 / (0.8473 * full_2m_pf * 1e-12), 410, 0.02, " ohm")
check("glove chain: 6 nodes + 0.3 m", 6 * NODE_PF + 0.3 * RIBBON_PF_PER_M, 108, 0.02, " pF")
check("Fast-mode Plus: pull-up for the glove chain",
      I2C_FMP_RISE_NS * 1e-9 / (0.8473 * 108e-12), 1310, 0.02, " ohm")
checks += 1
if 15 * NODE_PF > c_max_pf(PULLUP_DEFAULT_OHM):
    print("  [ok] 15 nodes alone exceed what the 2.2k default can drive at 400 kHz")
else:
    failures.append("15-node pull-up claim no longer holds")

full_ma = max_node * node_ma
check("full chain of reference nodes", full_ma, 81, 0.02, " mA")
check("its supply drop over 2 m, 32 AWG", full_ma / 1000 * LONG_CHAIN_M * CABLE_OHM_PER_M
      * 2 * 1000, 175, 0.02, " mV")
check("the same on 26 AWG", full_ma / 1000 * LONG_CHAIN_M * AWG26_OHM_PER_M * 2 * 1000,
      43, 0.05, " mV")
budget_ma = SUPPLY_DROP_BUDGET_MV / (LONG_CHAIN_M * CABLE_OHM_PER_M * 2)
check("current within the drop budget over 2 m, 32 AWG", budget_ma, 46, 0.02, " mA")
check("reference nodes within that budget", int(budget_ma // node_ma), 8, 0, "")
budget_26 = SUPPLY_DROP_BUDGET_MV / (LONG_CHAIN_M * AWG26_OHM_PER_M * 2)
check("current within the drop budget over 2 m, 26 AWG", budget_26, 187, 0.02, " mA")
check("camera nodes within that budget, 26 AWG", int(budget_26 // CAMERA_NODE_MA), 2, 0,
      "")

for mhz, fps in ((8, 13), (12, 19.5)):
    check(f"QVGA greyscale frames/s, whole chain, {mhz} MHz SPI",
          mhz * 1e6 / 8 / QVGA_GREY_BYTES, fps, 0.03, " fps")

check("ARM with a 4-byte v4 frame, 400 kHz", i2c_write_us(frame_len + 1, I2C_FAST_HZ),
      117.5, 0.02, " us")

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

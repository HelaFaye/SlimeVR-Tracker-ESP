#!/usr/bin/env python3
"""
Board configuration checks: every board in board-defaults.json generates its flags, and
the chain settings agree with the protocol and with the module the board is built on.

    python3 sim/check_board_config.py

Both failures this guards against shipped once and produced no error anywhere:
  - the node build, the firmware default and two boards each carried their own copy of
    the chain address, and they disagreed (0x30 against 0x13). A hub built that way
    finds no nodes.
  - a board put a chain strobe on ESP32-C5 GPIO15, which the hub hardware leaves
    unconnected because modules with in-package PSRAM use it as SPICS1.
"""

import configparser
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

failures = []
checks = 0


def ok(cond, message):
    global checks
    checks += 1
    print(f"  [{'ok' if cond else 'FAIL'}] {message}")
    if not cond:
        failures.append(message)


def load_preprocessor():
    """The generator is a PlatformIO script; load its functions without PlatformIO."""
    src = (ROOT / "scripts/preprocessor.py").read_text().replace('Import("env")', "pass")
    src = src.split("schema_obj = _load_json")[0]
    module = types.ModuleType("preprocessor")
    exec(compile(src, "preprocessor.py", "exec"), module.__dict__)
    return module


def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


# ESP32-C5 GPIOs a chain may not use. Strapping, flash/PSRAM, USB-JTAG and the module's
# console UART are the same set lib/i2cscan excludes; GPIO15 is SPICS1 on modules with
# in-package PSRAM and is left unconnected on the hub.
C5_RESERVED = {2, 3, 7, 25, 26, 27, 28} | set(range(16, 23)) | {13, 14} | {11, 12} | {15}

# ------------------------------------------------------------------------ generation

pp = load_preprocessor()
schema = json.loads((ROOT / "board-defaults.schema.json").read_text())
defaults = json.loads((ROOT / "board-defaults.json").read_text())

print("Generation")
import os  # noqa: E402

os.chdir(ROOT)  # the generator resolves the protocol header relative to the project
boards = pp.build_boards(schema, defaults)
ok(len(boards) == len(defaults["defaults"]), f"{len(boards)} boards generate their flags")

# ---------------------------------------------------------------------- chain address

print("\nChain address")
default_addr, whitelist = pp._chain_protocol()
ok(default_addr in whitelist, f"protocol default {default_addr:#04x} is whitelisted")

for name, flags in boards.items():
    for flag in flags:
        m = re.fullmatch(r"-DREMOTE_CS_BASE_ADDR=(\d+)", flag)
        if m:
            addr = int(m.group(1))
            ok(addr in whitelist, f"{name}: chain address {addr:#04x} is whitelisted")
        for m in re.finditer(r"(?:ATTINY_CS_ON|I2SPI_WIRE_ON)\(\w+, \w+, (\d+),", flag):
            addr = int(m.group(1))
            ok(addr in whitelist, f"{name}: named chain address {addr:#04x} is whitelisted")

node_ini = (ROOT / "extras/attiny-cs-node/platformio.ini").read_text()
overrides = re.findall(r"^\s*-DBASE_ADDRESS=(0x[0-9A-Fa-f]+)", node_ini, re.M)
ok(not overrides,
   "node build takes the address from the protocol header, not its own -DBASE_ADDRESS"
   + (f" (found {', '.join(overrides)})" if overrides else ""))

globals_h = (ROOT / "src/globals.h").read_text()
ok("#define REMOTE_CS_BASE_ADDR SlimeVR::ATTinyCS::DefaultBaseAddress" in globals_h,
   "firmware default REMOTE_CS_BASE_ADDR is the protocol constant, not a copy")

# --------------------------------------------------------------- multi-chain rules
#
# No shipped board uses two chains any more, so exercise the named-chain path here
# rather than leave it untested.

print("\nNamed chains")


def board(chains, sensors):
    return {
        "values": {
            "LED": {"LED_PIN": "8", "LED_INVERTED": False},
            "SPI": {"sck": "10", "miso": "9", "mosi": "8"},
            "REMOTE_CS": chains,
            "SENSORS": sensors,
        }
    }


def spi_on(chain, node):
    return {"protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_0",
            "cs": {"type": "attiny", "node": node, "chain": chain}}


def build(chains):
    d = {"defaults": {"T": board(chains, [spi_on("a", 1), spi_on("b", 1)])}}
    return pp._build_board_flags(d, "T")


second = next(a for a in whitelist if a != default_addr)
flags = build({"a": {"scl": "4", "sda": "5", "strobe": "6"},
               "b": {"scl": "4", "sda": "5", "strobe": "1", "baseAddress": second}})
ok(f"ATTINY_CS_ON(4, 5, {default_addr}, 6, 1, 0)" in flags[-1]
   and f"ATTINY_CS_ON(4, 5, {second}, 1, 1, 0)" in flags[-1],
   "two chains on one bus with distinct whitelisted addresses generate")
ok(raises(lambda: build({"a": {"scl": "4", "sda": "5", "strobe": "6"},
                         "b": {"scl": "4", "sda": "5", "strobe": "1"}})),
   "two chains on one bus at the same address are refused")
ok(raises(lambda: build({"a": {"scl": "4", "sda": "5", "strobe": "6", "baseAddress": 0x30},
                         "b": {"scl": "4", "sda": "5", "strobe": "1"}})),
   "a chain address off the whitelist (0x30) is refused")

# ------------------------------------------------------------ ESP32-C5 chain pins

print("\nESP32-C5 chain pins")
ini = configparser.ConfigParser(interpolation=None)
ini.read(ROOT / "platformio.ini")
c5_boards = [
    ini[s]["custom_slime_board"]
    for s in ini.sections()
    if "custom_slime_board" in ini[s] and "-DESP32C5" in ini[s].get("build_flags", "")
]
ok(len(c5_boards) > 0, f"{len(c5_boards)} ESP32-C5 boards found")

for name in c5_boards:
    chains = pp._chains(defaults["defaults"][name]["values"])
    for chain_name, c in chains.items():
        if not c:
            continue
        for role in ("scl", "sda", "strobe"):
            pin = c.get(role)
            if pin is None or int(pin) < 0:
                continue
            ok(int(pin) not in C5_RESERVED,
               f"{name}: chain '{chain_name}' {role} on GPIO{pin} is usable on the module")

print(f"\n{checks} checks, {len(failures)} failed")
for f in failures:
    print(f"  - {f}")
sys.exit(1 if failures else 0)

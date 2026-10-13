#!/usr/bin/env python3
"""
Type-check every board's generated SENSOR_DESC_LIST without a toolchain.

    python3 sim/check_desc_list.py

For each board in board-defaults.json this generates the build flags, then compiles (with
the host g++, syntax only) a small file that expands the board's SENSOR_DESC_LIST against
a stub with sensorDescEntry's real signature and the descriptor helpers' real arities. A
generator bug that puts an argument in the wrong slot fails here, not in a PlatformIO
build that may not run for every board.

That is not hypothetical: chained I2C sensors were emitted with the chain interface in the
address slot and a bool where the SensorInterface* goes, and nothing caught it because no
shipped board used one. The check below includes a synthetic board that does.

The helper stubs mirror the lambdas in src/sensors/SensorBuilder.cpp. If a helper is added
there and not here, this fails and says which.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CXX = os.environ.get("CXX", "g++")

# name -> (return type, parameter list), matching SensorBuilder.cpp.
HELPERS = {
    "NO_PIN": None,  # a value, not a function
    "NO_WIRE": None,
    "DIRECT_PIN": ("PinInterface*", "uint8_t"),
    "DIRECT_WIRE": ("SensorInterface*", "uint8_t, uint8_t"),
    "MCP_PIN": ("PinInterface*", "uint8_t"),
    "PCA_WIRE": ("SensorInterface*", "uint8_t, uint8_t, uint8_t, uint8_t"),
    "SPI_BUS": ("DirectSPIInterface*", "uint32_t, uint8_t, uint8_t, int8_t, int8_t, int8_t"),
    "DIRECT_SPI": ("DirectSPIInterface*", "uint32_t, uint8_t, uint8_t"),
    "ATTINY_CS_ON": ("PinInterface*", "uint8_t, uint8_t, uint8_t, int8_t, uint8_t, uint8_t"),
    "ATTINY_CS_CH": ("PinInterface*", "uint8_t, uint8_t"),
    "ATTINY_CS": ("PinInterface*", "uint8_t"),
    "I2SPI_WIRE_ON": (
        "ATTinyCSWireInterface*",
        "uint8_t, uint8_t, uint8_t, int8_t, uint8_t, uint8_t",
    ),
    "I2SPI_WIRE_CH": ("ATTinyCSWireInterface*", "uint8_t, uint8_t"),
    "I2SPI_WIRE": ("ATTinyCSWireInterface*", "uint8_t"),
    "SPI_MAG": ("RegisterInterface*", "DirectSPIInterface*, PinInterface*"),
}

failures = []


def load_preprocessor():
    src = (ROOT / "scripts/preprocessor.py").read_text().replace('Import("env")', "pass")
    src = src.split("schema_obj = _load_json")[0]
    module = types.ModuleType("preprocessor")
    exec(compile(src, "preprocessor.py", "exec"), module.__dict__)
    return module


def helpers_in_source():
    text = (ROOT / "src/sensors/SensorBuilder.cpp").read_text()
    return set(re.findall(r"\[\[maybe_unused\]\]\s+const\s+auto\s+(\w+)", text))


def imu_types():
    text = (ROOT / "src/consts.h").read_text()
    return sorted(set(re.findall(r"#define\s+IMU_\w+\s+(\w+)\s*$", text, re.M)))


def imu_defines():
    """The IMU_* -> class macros themselves, verbatim from consts.h."""
    text = (ROOT / "src/consts.h").read_text()
    return "\n".join(re.findall(r"^#define\s+IMU_\w+\s+\w+\s*$", text, re.M))


def deg_macros():
    text = (ROOT / "src/consts.h").read_text()
    return "\n".join(re.findall(r"^#define DEG_\w+.*$", text, re.M))


def translation_unit():
    lines = [
        "#include <cstdint>",
        "struct PinInterface {};",
        "struct SensorInterface {};",
        "struct DirectSPIInterface : SensorInterface {};",
        "struct ATTinyCSWireInterface : SensorInterface {};",
        "struct RegisterInterface {};",
        "struct EmptySensorInterface : SensorInterface { static EmptySensorInterface instance; };",
    ]
    lines += [f"struct {t} {{}};" for t in imu_types()]
    lines += [
        imu_defines(),
        # ESP8266 boards name pins D0..D8 (pins_arduino.h); any integer will do here.
        *[f"constexpr uint8_t D{i} = {i};" for i in range(9)],
        "#define PI 3.14159265358979f",
        deg_macros(),
        "#define MSBFIRST 1",
        "#define LSBFIRST 0",
        "#define SPI_MODE0 0",
        "#define SPI_MODE1 1",
        "#define SPI_MODE2 2",
        "#define SPI_MODE3 3",
        "#ifndef PRIMARY_IMU_ADDRESS_ONE",
        "#define PRIMARY_IMU_ADDRESS_ONE false",
        "#endif",
        "#ifndef SECONDARY_IMU_ADDRESS_TWO",
        "#define SECONDARY_IMU_ADDRESS_TWO true",
        "#endif",
        # The real signature, from src/sensors/SensorBuilder.h.
        "template <typename SensorType, typename AccessInterface>",
        "bool sensorDescEntry(uint8_t sensorID, AccessInterface accessInterface, float rotation,",
        "    SensorInterface* sensorInterface, bool optional = false,",
        "    PinInterface* intPin = nullptr, int extraParam = 0,",
        "    RegisterInterface* magInterface = nullptr, int magAxes = 136) { return true; }",
        "#define SENSOR_DESC_ENTRY(ImuType, ...) \\",
        "    count += sensorDescEntry<ImuType>(sensorID++, __VA_ARGS__) ? 1 : 0;",
        "int main() {",
        "  uint8_t sensorID = 0; int count = 0;",
        "  [[maybe_unused]] const auto NO_PIN = nullptr;",
        "  [[maybe_unused]] SensorInterface* const NO_WIRE = &EmptySensorInterface::instance;",
    ]
    for name, sig in HELPERS.items():
        if sig is None:
            continue
        ret, params = sig
        lines.append(
            f"  [[maybe_unused]] const auto {name} = []({params}) -> {ret} {{ return nullptr; }};"
        )
    lines += ["  SENSOR_DESC_LIST", "  return count;", "}"]
    return "\n".join(lines) + "\n"


def compile_board(name, flags, tu_path):
    defines = [f for f in flags if f.startswith("-D")]
    if not any(f.startswith("-DSENSOR_DESC_LIST=") for f in defines):
        return None  # board uses the built-in defaults in src/boards, not the generator
    # Flags are written for a shell (PlatformIO passes them through one); parse them the
    # same way so the quoted SENSOR_DESC_LIST arrives as one argument.
    args = shlex.split(" ".join(defines))
    cmd = [CXX, "-std=gnu++2a", "-fsyntax-only", "-x", "c++", *args, str(tu_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def main():
    os.chdir(ROOT)

    print("Helper coverage")
    missing = sorted(helpers_in_source() - set(HELPERS))
    stale = sorted(set(HELPERS) - helpers_in_source())
    ok = not missing and not stale
    print(f"  [{'ok' if ok else 'FAIL'}] stubs match SensorBuilder.cpp's descriptor helpers"
          + (f" (missing {missing}, stale {stale})" if not ok else ""))
    if not ok:
        failures.append("helper stubs out of sync")

    pp = load_preprocessor()
    schema = json.loads(Path("board-defaults.schema.json").read_text())
    defaults = json.loads(Path("board-defaults.json").read_text())

    boards = pp.build_boards(schema, defaults)

    # Synthetic configurations exercising every chain form, including chained I2C sensors,
    # which no shipped board uses yet. The schema only accepts real board names, so each
    # one replaces a real board's values, as qemu/run.sh scenarios do.
    battery = {"type": "BAT_EXTERNAL", "r1": 100, "r2": 220, "shieldR": 180, "pin": "1"}
    led = {"LED_PIN": "23", "LED_INVERTED": False}
    spi = {"sck": "10", "miso": "9", "mosi": "8"}
    synthetic = {
        "synthetic:chain-forms": {
            "LED": led, "BATTERY": battery, "SPI": spi,
            "REMOTE_CS": {"scl": "4", "sda": "5", "strobe": "6"},
            "SENSORS": [
                {"protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_0",
                 "cs": {"type": "direct", "pin": "0"}},
                {"protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_90",
                 "cs": {"type": "attiny", "node": 1},
                 "mag": {"cs": {"type": "attiny", "node": 1, "channel": 1}, "axes": "+Y-X+Z"}},
                {"protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_0",
                 "cs": {"type": "attiny", "node": 2, "channel": 1}},
                {"protocol": "I2C", "imu": "IMU_ICM45686", "rotation": "DEG_180",
                 "node": 3, "address": 0x68, "mag": {"cs": "7"}},
                {"protocol": "I2C", "imu": "IMU_ICM45686", "rotation": "DEG_270",
                 "node": 4, "channel": 1, "mag": {"axes": "-X-Y+Z"}},
            ],
        },
        "synthetic:named-chains": {
            "LED": led, "BATTERY": battery, "SPI": spi,
            "REMOTE_CS": {
                "a": {"scl": "4", "sda": "5", "strobe": "6"},
                "b": {"scl": "1", "sda": "2", "strobe": "3", "baseAddress": 0x12},
            },
            "SENSORS": [
                {"protocol": "SPI", "imu": "IMU_ICM45686", "rotation": "DEG_0",
                 "cs": {"type": "attiny", "node": 1, "chain": "a"}},
                {"protocol": "I2C", "imu": "IMU_ICM45686", "rotation": "DEG_0",
                 "node": 1, "chain": "b"},
            ],
        },
    }
    host = "BOARD_SLIMEVR_C5_CHAIN_HUB"
    for label, values in synthetic.items():
        d = json.loads(json.dumps(defaults))
        d["defaults"][host]["values"] = values
        boards[label] = pp.build_boards(schema, d, host)[host]

    print("\nSENSOR_DESC_LIST type check (host g++, syntax only)")
    with tempfile.TemporaryDirectory() as tmp:
        tu = Path(tmp) / "desc_list.cpp"
        tu.write_text(translation_unit())
        checked = 0
        for name, flags in sorted(boards.items()):
            result = compile_board(name, flags, tu)
            if result is None:
                continue
            checked += 1
            if result.returncode == 0:
                print(f"  [ok] {name}")
            else:
                failures.append(name)
                first = [ln for ln in result.stderr.splitlines() if "error" in ln][:3]
                print(f"  [FAIL] {name}")
                for ln in first:
                    print(f"         {ln.strip()[:200]}")
        print(f"\n{checked} boards type-checked, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

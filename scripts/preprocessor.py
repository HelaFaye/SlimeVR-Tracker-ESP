import json
import re
import os
from pathlib import Path
from typing import Union, Optional, Dict, Any, List

Import("env")

try:
    import jsonschema
except:
    env.Execute(
        env.VerboseAction(
            '$PYTHONEXE -m pip install "jsonschema==4.22.0"',
            "Installing jsonschema for validation",
        )
    )

from jsonschema import Draft202012Validator, exceptions as jsonschema_exceptions



def _load_json(maybe_path_or_dict: Union[str, Path, dict]) -> dict:
    """Load JSON file or accept dict directly."""
    if isinstance(maybe_path_or_dict, dict):
        return maybe_path_or_dict
    p = Path(maybe_path_or_dict)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON file {p}: {e}")

# Allow:
# - unquoted alphanumerics, underscores, dots, dashes
# - or single-quoted with optional escaped double quotes inside
VALID_DEFINE_VALUE = re.compile(
    r"^(?:[A-Za-z0-9_.\-]*|'(\\\"[A-Za-z0-9_.\-\s]*\\\"|[A-Za-z0-9_.\-\s]*)')$"
)

def _validate_define_value(value: str, key: str) -> None:
    if key == "SENSOR_DESC_LIST":
        return

    """Validate the formatted define value to prevent injection."""
    if not VALID_DEFINE_VALUE.fullmatch(value):
        raise ValueError(
            f"Invalid characters in value for {key!r}: {value!r} "
            "(only letters, digits, _, ., -, spaces, and optional quoted forms like '\"text\"' allowed)"
        )

def _format_raw_value(value: Any) -> str:
    """Format booleans for C/C++, otherwise str(value)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)

def format_value(val: Any, typ: str, key: str = "<unknown>") -> str:
    """Format a value according to type, with built-in validation."""
    if typ == "pin":
        if isinstance(val, str) and re.search(r"[AD]", val):
            result = f'{val}'
        else:
            result = _format_raw_value(val)

    elif typ == "string":
        result = f"'\\\"{val}\\\"'"

    elif typ in ("raw", "number"):
        result = _format_raw_value(val)

    else:
        raise ValueError(f"Value type '{typ}' is not supported")


    _validate_define_value(result, key)
    return result


# Kept byte-for-byte as the pre-configurable-SPI default so boards that predate the
# "SPI" config block (notably BOARD_SLIMEVR_V1_2) generate exactly what they did before.
LEGACY_SPI_BUS = "DIRECT_SPI(24'000'000, MSBFIRST, SPI_MODE3)"


def _format_chip_select(cs: Any) -> str:
    """A chip select is either a host GPIO (a plain pin string, the original form) or an
    object describing a remote ATtiny node on an RJ45 sensor chain."""
    if cs is None:
        raise ValueError("SPI sensor is missing a 'cs' entry")

    if not isinstance(cs, dict):
        return f"DIRECT_PIN({format_value(cs, 'pin')})"

    cs_type = cs.get('type', 'direct')

    if cs_type == 'direct':
        return f"DIRECT_PIN({format_value(cs.get('pin'), 'pin')})"

    if cs_type == 'attiny':
        node = cs.get('node')
        if node is None:
            raise ValueError("attiny chip select is missing 'node'")

        # A node may own several chip selects. Channel 0 is the common case and keeps
        # the shorter descriptor, which is also what a protocol v1 node understands.
        channel = cs.get('channel', 0)
        if channel:
            return (
                f"ATTINY_CS_CH({format_value(node, 'number')}, "
                f"{format_value(channel, 'number')})"
            )
        return f"ATTINY_CS({format_value(node, 'number')})"

    raise ValueError(f"Unknown chip select type: {cs_type!r}")


def _format_spi_bus(spi: Optional[dict]) -> str:
    """Build the bus descriptor for the SENSOR_DESC_ENTRY list."""
    if not spi:
        return LEGACY_SPI_BUS

    clock = spi.get('clock', 4000000)
    bit_order = spi.get('bitOrder', 'MSBFIRST')
    mode = spi.get('mode', 'SPI_MODE3')

    sck = spi.get('sck', -1)
    miso = spi.get('miso', -1)
    mosi = spi.get('mosi', -1)

    if sck == -1 and miso == -1 and mosi == -1:
        return f"DIRECT_SPI({format_value(clock, 'number')}, {format_value(bit_order, 'raw')}, {format_value(mode, 'raw')})"

    return (
        f"SPI_BUS({format_value(clock, 'number')}, {format_value(bit_order, 'raw')}, "
        f"{format_value(mode, 'raw')}, {format_value(sck, 'pin')}, "
        f"{format_value(miso, 'pin')}, {format_value(mosi, 'pin')})"
    )


def _build_board_flags(defaults: dict, board_name: str) -> List[str]:
    """Construct list of -D flags for one board."""
    if "defaults" not in defaults:
        raise ValueError("Missing top-level 'defaults' key in defaults JSON.")
    if board_name not in defaults["defaults"]:
        raise ValueError(f"Invalid board selected - {board_name}")

    board_defaults = defaults["defaults"][board_name]
    values = board_defaults.get("values", {})

    args: Dict[str, Dict[str, Any]] = {}

    def add(key: str, value: Any, value_type: str):
        if value is not None:
            args[key] = {"value": value, "type": value_type}

    add('BOARD', board_name, 'raw')
    add('LED_PIN', values.get('LED').get('LED_PIN'), 'pin')
    add('LED_INVERTED', values.get('LED').get('LED_INVERTED'), 'raw')

    sensors = values.get('SENSORS')
    if sensors:
        sensor_list = []

        spi_bus_expression = _format_spi_bus(values.get('SPI'))
        remote_cs = values.get('REMOTE_CS')

        add('PIN_IMU_SDA', 255, 'pin') # FIXME fix the I2C Scanner so it use the sensor list and not be called when no I2C sensor
        add('PIN_IMU_SCL', 255, 'pin')
        add('PIN_IMU_INT_2', 255, 'pin') # FIXME: fix the CONFIG serial command so it use the sensor list

        # More than the historic two sensors is legal (the glove already does ten), but
        # MAX_SENSORS_COUNT sizes the per-sensor ack arrays in connection.h, so it has to
        # be raised in step with the descriptor list.
        if len(sensors) > 2:
            add('MAX_SENSORS_COUNT', len(sensors), 'number')

        if remote_cs:
            add('REMOTE_CS_SCL', remote_cs.get('scl'), 'pin')
            add('REMOTE_CS_SDA', remote_cs.get('sda'), 'pin')
            add('REMOTE_CS_BASE_ADDR', remote_cs.get('baseAddress', 48), 'number')
            # -1 means "no strobe conductor", i.e. drive CS over I2C instead. Slow.
            add('REMOTE_CS_STROBE', remote_cs.get('strobe', -1), 'number')

        for index, sensor in enumerate(sensors):
            if sensor.get('protocol') == 'I2C':
                params = [
                    format_value(sensor.get('imu'), 'raw'),
                    format_value(sensor.get('address', 'PRIMARY_IMU_ADDRESS_ONE' if index == 0 else 'SECONDARY_IMU_ADDRESS_TWO'), 'number'),
                    format_value(sensor.get('rotation'), 'raw'),
                    f"DIRECT_WIRE({format_value(sensor.get('scl'), 'pin')}, {format_value(sensor.get('sda'), 'pin')})",
                    'false' if index == 0 else 'true',
                    f"DIRECT_PIN({format_value(sensor.get('int', 255), 'pin')})",
                    '0'
                ]
                sensor_list.append(f"SENSOR_DESC_ENTRY({','.join(params)})")
                add('PIN_IMU_SDA', sensor.get('sda'), 'pin')
                add('PIN_IMU_SCL', sensor.get('scl'), 'pin')

            if sensor.get('protocol') == 'SPI':
                params = [
                    format_value(sensor.get('imu'), 'raw'),
                    _format_chip_select(sensor.get('cs')),
                    format_value(sensor.get('rotation'), 'raw'),
                    spi_bus_expression,
                    'false' if index == 0 else 'true',
                    f"DIRECT_PIN({format_value(sensor.get('int', 255), 'pin')})",
                    '0'
                ]
                sensor_list.append(f"SENSOR_DESC_ENTRY({','.join(params)})")

            # serialcommands.cpp prints PIN_IMU_INT unconditionally, and add() skips
            # None, so a sensor without an `int` produced a config that fails to build.
            if index == 0: # FIXME: fix the CONFIG serial command so it use the sensor list
                add('PIN_IMU_INT', sensor.get('int', 255), 'pin')
            elif index == 1:
                add('PIN_IMU_INT_2', sensor.get('int', 255), 'pin')
        # The I2C scanner and the CONFIG serial command still read these globals. On a
        # chain-only board there is no local I2C sensor to take them from, so point them
        # at the node chain's bus rather than leaving them at 255.
        if remote_cs and args.get('PIN_IMU_SDA', {}).get('value') == 255:
            add('PIN_IMU_SDA', remote_cs.get('sda'), 'pin')
            add('PIN_IMU_SCL', remote_cs.get('scl'), 'pin')

        add('SENSOR_DESC_LIST', f"'{' '.join(sensor_list)}'", 'raw')


    battery = values.get('BATTERY')
    if battery:
        add('BATTERY_MONITOR', battery.get('type'), 'raw')
        add('PIN_BATTERY_LEVEL', battery.get('pin', 255), 'pin')
        add('BATTERY_SHIELD_RESISTANCE', battery.get('shieldR', 180), 'number')
        add('BATTERY_SHIELD_R1', battery.get('r1', 100), 'number')
        add('BATTERY_SHIELD_R2', battery.get('r2', 220), 'number')

    parts: List[str] = []
    for key, meta in args.items():
        formatted = format_value(meta["value"], meta["type"], key)
        parts.append(f"-D{key}={formatted}")

    return parts


def build_boards(
    schema_obj,
    defaults_obj,
    board_name: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Validate defaults.json against board-defaults.schema.json using jsonschema,
    and return { board_name: [list of -D flags] }.
    """
    validator = Draft202012Validator(schema_obj)
    errors = sorted(validator.iter_errors(defaults_obj), key=lambda e: e.path)

    if errors:
        print("✖ JSON Schema validation failed:")
        for err in errors:
            path = "/".join(map(str, err.path)) or "(root)"
            print(f"  • Path: {path}")
            print(f"    Error: {err.message}")
            if err.context:
                for ctx in err.context:
                    print(f"      ↳ {ctx.message}")
        raise ValueError(f"{len(errors)} schema validation errors found.")

    out: Dict[str, List[str]] = {}
    if board_name:
        out[board_name] = _build_board_flags(defaults_obj, board_name)
    else:
        for name in defaults_obj.get("defaults", {}).keys():
            out[name] = _build_board_flags(defaults_obj, name)

    return out

schema_obj = _load_json("./board-defaults.schema.json")
defaults_obj = _load_json("./board-defaults.json")
slime_board = env.GetProjectOption("custom_slime_board", None)
if slime_board:
    if 'SLIMEVR_OVERRIDE_DEFAULTS' in os.environ and slime_board in defaults_obj['defaults']:
        print(">>> OVERIDING BOARD DEFAULTS ", os.environ['SLIMEVR_OVERRIDE_DEFAULTS'])
        defaults_obj['defaults'][slime_board]['values'] = json.loads(os.environ['SLIMEVR_OVERRIDE_DEFAULTS'])

    output_flags = build_boards(
        schema_obj,
        defaults_obj,
        slime_board,
    )
    output_flags = output_flags.get(slime_board, []) if isinstance(output_flags, dict) else []

    separator = '\n  '
    print(f">>> Appending build flags:\n  {separator.join(output_flags)}")
    env.Append(BUILD_FLAGS=output_flags)
else:
    print(">>> custom_slime_board not set - skipping")

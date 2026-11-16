import json
import re
import os
from pathlib import Path
from typing import Union, Optional, Dict, Any, List

Import("env")

try:
    import jsonschema
except ImportError:
    # Install into a project-local directory with the interpreter running this script,
    # then import from there. $PYTHONEXE is not enough: pioarduino runs build scripts
    # with its own virtualenv's paths (~/.platformio/penv), so a package installed into
    # PlatformIO's Python stays invisible here. --target works whichever interpreter or
    # sys.path is in use, and the running interpreter picks wheels that match it.
    import importlib
    import sys

    _deps = os.path.join(env.subst("$PROJECT_DIR"), ".pio", "pydeps")
    sys.path.insert(0, _deps)
    try:
        import jsonschema  # installed there by an earlier board's build
    except ImportError:
        env.Execute(
            env.VerboseAction(
                f'"{sys.executable}" -m pip install --quiet --upgrade --target "{_deps}" '
                '"jsonschema==4.22.0"',
                "Installing jsonschema for validation",
            )
        )
        importlib.invalidate_caches()

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
LEGACY_SPI_CLOCK = 24000000

# Clock for a board "SPI" block that does not set one: safe on cable (I2SPI.md §3.2).
SPI_DEFAULT_CLOCK = 4000000

# Fastest SPI clock any supported SPI magnetometer accepts (MMC5983MA and LIS3MDL: 10 MHz).
MAG_SPI_MAX_CLOCK = 10000000


# The chain address is defined once, in ATTinyCSProtocol.h, which the node firmware also
# builds against. Read it from there: separate copies here, in globals.h and in the node
# build once disagreed (0x30 against 0x13), and a hub built that way finds no nodes.
PROTOCOL_HEADER = Path("./src/sensorinterface/ATTinyCSProtocol.h")
_chain_protocol_cache: Optional[tuple] = None


def _chain_protocol() -> tuple:
    """(default address, whitelist) as declared in ATTinyCSProtocol.h."""
    global _chain_protocol_cache
    if _chain_protocol_cache is None:
        text = PROTOCOL_HEADER.read_text()
        default = re.search(r"DefaultBaseAddress\s*=\s*(0x[0-9A-Fa-f]+)", text)
        whitelist = re.search(r"AddressWhitelist\[\]\s*=\s*\{([^}]*)\}", text)
        if not default or not whitelist:
            raise ValueError(f"Chain address constants not found in {PROTOCOL_HEADER}")
        _chain_protocol_cache = (
            int(default.group(1), 16),
            [int(a, 16) for a in whitelist.group(1).split(",") if a.strip()],
        )
    return _chain_protocol_cache


def _chain_address(chain: dict) -> int:
    """A chain's I2C address, defaulted and checked against the protocol whitelist."""
    default, whitelist = _chain_protocol()
    addr = chain.get('baseAddress', default)
    if addr not in whitelist:
        raise ValueError(
            f"chain address {addr:#04x} is not in ATTinyCS::AddressWhitelist "
            f"({', '.join(f'{a:#04x}' for a in whitelist)}). Nodes listen on "
            f"{default:#04x} unless built with -DBASE_ADDRESS; pick a whitelisted "
            "address and build the nodes to match."
        )
    return addr


def _format_chip_select(cs: Any, chains: Optional[dict] = None) -> str:
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

        # A named chain resolves to the explicit form, which carries its own pins and
        # address rather than falling back to the REMOTE_CS_* defaults.
        chain = cs.get('chain')
        if chain:
            c = chains[chain]
            channel = cs.get('channel', 0)
            return (
                f"ATTINY_CS_ON({format_value(c.get('scl'), 'pin')}, "
                f"{format_value(c.get('sda'), 'pin')}, "
                f"{format_value(_chain_address(c), 'number')}, "
                f"{format_value(c.get('strobe', -1), 'number')}, "
                f"{format_value(node, 'number')}, "
                f"{format_value(channel, 'number')})"
            )

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


def _spi_buses(values: dict) -> dict:
    """Board SPI config, normalised to a name -> settings map.

    Accepts a single object (the common case, name "default") or a map of named buses,
    so a board with two SPI peripherals can declare both. Sensors pick one with "bus".
    """
    spi = values.get('SPI')
    if not spi:
        return {'default': None}
    if any(k in spi for k in ('sck', 'miso', 'mosi', 'clock', 'bitOrder', 'mode')):
        return {'default': spi}
    return spi


def _chains(values: dict) -> dict:
    """Chain config, normalised the same way. Sensors pick one with "chain"."""
    chains = values.get('REMOTE_CS')
    if not chains:
        return {}
    if any(k in chains for k in ('scl', 'sda', 'strobe', 'baseAddress')):
        return {'default': chains}

    # Chains sharing an I2C bus must not share an address. They all hear each other's
    # frames, so an ARM meant for one would arm nodes on the other: differing strobes
    # keep chip selects safe, but a gated I2C sensor on the unintended chain would
    # ungate and answer. Invisible at runtime, so refuse it here.
    seen = {}
    for name, c in chains.items():
        bus = (str(c.get('scl')), str(c.get('sda')))
        addr = _chain_address(c)
        key = (bus, addr)
        if key in seen:
            raise ValueError(
                f"chains {seen[key]!r} and {name!r} share I2C bus "
                f"SCL {bus[0]}/SDA {bus[1]} and address {addr:#04x}; "
                "give each chain its own address from ATTinyCS::AddressWhitelist"
            )
        seen[key] = name
    return chains


def _format_spi_bus(spi: Optional[dict]) -> str:
    """Build the bus descriptor for the SENSOR_DESC_ENTRY list."""
    if not spi:
        return LEGACY_SPI_BUS

    clock = spi.get('clock', SPI_DEFAULT_CLOCK)
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


def _format_mag(mag: dict, spi_buses: dict, chains: dict) -> str:
    """A magnetometer on its own SPI chip select, as the descriptor's last argument."""
    bus_name = mag.get('bus', 'default')
    if bus_name not in spi_buses:
        raise ValueError(f"magnetometer names SPI bus {bus_name!r}, which SPI does not define")
    # Same pins as the IMU's bus, but the mag's own settings: the supported parts
    # (MMC5983MA, LIS3MDL) take 10 MHz at most, while an IMU bus may run faster (the
    # legacy default is 24 MHz). SPISettings are applied per transaction, so both
    # share one SPIClass safely.
    #
    # Mode follows the bus unless the mag overrides it. Both parts specify mode 3, but
    # SparkFun found the MMC5983MA works only in mode 0 in practice, and keeping the
    # bus's mode avoids flipping SCK's idle level between the IMU's and the mag's
    # transactions.
    configured = spi_buses.get(bus_name)
    bus = dict(configured or {})
    limit = int(mag.get('clock', MAG_SPI_MAX_CLOCK))
    if limit > MAG_SPI_MAX_CLOCK:
        raise ValueError(f"magnetometer clock {limit} exceeds {MAG_SPI_MAX_CLOCK} Hz")
    # The bus's own clock when unset is what _format_spi_bus would use for it.
    bus_clock = int(bus.get('clock', SPI_DEFAULT_CLOCK if configured else LEGACY_SPI_CLOCK))
    bus['clock'] = min(bus_clock, limit)
    bus['mode'] = mag.get('mode', bus.get('mode', 'SPI_MODE3'))
    bus['bitOrder'] = 'MSBFIRST'
    return (
        f"SPI_MAG({_format_spi_bus(bus)}, "
        f"{_format_chip_select(mag.get('cs'), chains)})"
    )


# MagDriver::AxisMapIdentity: IMU X, Y, Z take mag X, Y, Z.
MAG_AXES_IDENTITY = (0 << 0) | (1 << 3) | (2 << 6)


def _mag_axes(axes: str) -> int:
    """Encode "+Y-X+Z" (IMU X = +mag Y, IMU Y = -mag X, IMU Z = +mag Z) the way
    MagDriver::setAxisMap() reads it: per IMU axis, 3 bits = mag axis | negate << 2.

    Both chips are right-handed, so a valid mapping is a rotation. A mirror image
    (determinant -1) means one sign or axis is wrong, and would make the fusion fight
    the magnetometer, so it is refused rather than built."""
    m = re.fullmatch(r"([+-])([XYZ])([+-])([XYZ])([+-])([XYZ])", axes or "")
    if not m:
        raise ValueError(f"magnetometer axes {axes!r}: expected three signed axes, e.g. '+Y-X+Z'")
    pairs = [(m.group(2 * i + 1), "XYZ".index(m.group(2 * i + 2))) for i in range(3)]
    if sorted(src for _, src in pairs) != [0, 1, 2]:
        raise ValueError(f"magnetometer axes {axes!r}: each of X, Y and Z must appear once")
    matrix = [[0] * 3 for _ in range(3)]
    for row, (sign, src) in enumerate(pairs):
        matrix[row][src] = -1 if sign == "-" else 1
    det = (matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
           - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
           + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0]))
    if det != 1:
        raise ValueError(
            f"magnetometer axes {axes!r} describe a mirror image, not a rotation; "
            "flip one sign")
    return sum((src | (4 if sign == "-" else 0)) << (3 * i) for i, (sign, src) in enumerate(pairs))


def _desc_entry(params: List[str], sensor: dict, spi_buses: dict, chains: dict) -> str:
    """SENSOR_DESC_ENTRY(...), with the magnetometer arguments appended when the sensor
    has a "mag": SPI_MAG(...) for one on its own chip select (or nullptr for one behind
    the IMU's aux port), then the encoded axis map if it is not the identity.
    params must already hold all seven positional arguments, extraParam included."""
    mag = sensor.get('mag')
    if mag:
        if mag.get('cs') is None and any(k in mag for k in ('bus', 'clock', 'mode')):
            raise ValueError("magnetometer bus, clock and mode need a cs; without one the "
                             "entry only maps the axes of the IMU's aux-port mag")
        interface = _format_mag(mag, spi_buses, chains) if mag.get('cs') is not None else 'nullptr'
        axes = _mag_axes(mag['axes']) if 'axes' in mag else MAG_AXES_IDENTITY
        params = [*params, interface]
        if axes != MAG_AXES_IDENTITY:
            params.append(str(axes))
    return f"SENSOR_DESC_ENTRY({','.join(params)})"


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

        spi_buses = _spi_buses(values)
        chains = _chains(values)
        remote_cs = chains.get('default')

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
            add('REMOTE_CS_BASE_ADDR', _chain_address(remote_cs), 'number')
            # -1 means "no strobe conductor", i.e. drive CS over I2C instead. Slow.
            add('REMOTE_CS_STROBE', remote_cs.get('strobe', -1), 'number')

        for index, sensor in enumerate(sensors):
            if sensor.get('protocol') == 'I2C' and 'node' in sensor:
                # An I2C sensor on a chain node: the node gates its SCL, so its address
                # need not be unique across the chain. See DEC-016. Keyed on "node", not
                # "chain": a board with one unnamed chain never names it.
                c = chains[sensor.get('chain', 'default')]
                # Same shape as a local I2C entry - (imu, address, rotation, interface,
                # optional, int, extra) - with the chain interface in place of DIRECT_WIRE.
                # This once emitted the interface in the address slot and dropped the
                # address, which cannot compile; sim/check_desc_list.py now type-checks
                # every generated entry against sensorDescEntry's signature.
                params = [
                    format_value(sensor.get('imu'), 'raw'),
                    format_value(sensor.get('address', 'PRIMARY_IMU_ADDRESS_ONE'), 'number'),
                    format_value(sensor.get('rotation'), 'raw'),
                    f"I2SPI_WIRE_ON({format_value(c.get('scl'), 'pin')}, "
                    f"{format_value(c.get('sda'), 'pin')}, "
                    f"{format_value(_chain_address(c), 'number')}, "
                    f"{format_value(c.get('strobe', -1), 'number')}, "
                    f"{format_value(sensor.get('node'), 'number')}, "
                    f"{format_value(sensor.get('channel', 0), 'number')})",
                    'false' if index == 0 else 'true',
                    f"DIRECT_PIN({format_value(sensor.get('int', 255), 'pin')})",
                    '0'
                ]
                sensor_list.append(_desc_entry(params, sensor, spi_buses, chains))
                continue

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
                sensor_list.append(_desc_entry(params, sensor, spi_buses, chains))
                add('PIN_IMU_SDA', sensor.get('sda'), 'pin')
                add('PIN_IMU_SCL', sensor.get('scl'), 'pin')

            if sensor.get('protocol') == 'SPI':
                params = [
                    format_value(sensor.get('imu'), 'raw'),
                    _format_chip_select(sensor.get('cs'), chains),
                    format_value(sensor.get('rotation'), 'raw'),
                    _format_spi_bus(spi_buses[sensor.get('bus', 'default')]),
                    'false' if index == 0 else 'true',
                    f"DIRECT_PIN({format_value(sensor.get('int', 255), 'pin')})",
                    '0'
                ]
                sensor_list.append(_desc_entry(params, sensor, spi_buses, chains))

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

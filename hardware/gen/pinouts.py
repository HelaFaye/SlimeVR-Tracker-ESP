"""
Pinouts for the parts KiCad 7 does not ship symbols for.

**Read this before using the generated library.**

Every pinout below carries a `verified` flag. `False` means the pin numbering was written
from general knowledge of the package and family, NOT read off the datasheet. A schematic
built on an unverified pinout looks completely correct and is completely wrong, and the
error does not surface until a board comes back from fab.

The generator refuses to emit a library containing unverified parts unless you pass
`--allow-unverified`, and stamps every unverified symbol's datasheet field with a warning
so it is visible in KiCad too.

To verify one: open the datasheet, check every pin number against the table, then flip the
flag and note the document revision you checked against.
"""

from dataclasses import dataclass


@dataclass
class Pinout:
    name: str
    description: str
    package: str
    # (pin number, pin name, electrical type)
    pins: list
    verified: bool
    checked_against: str = ""


# ESP32-C5-WROOM-1 and QMC6309 now come from the vendored libraries in
# hardware/lib/vendor rather than from these tables - see PROVENANCE.md there. The
# entries below are kept only for the parts still needing a locally generated symbol.

ICM45686 = Pinout(
    name="ICM-45686",
    description="6-axis IMU, SPI host (AP) interface + AUX1 I2C master",
    package="LGA-14_2.5x3mm_P0.5mm",
    pins=[
        ("1", "AP_SDO", "output"),  # AP_AD0 in I2C/I3C mode
        ("2", "AUX1_SDIO", "bidirectional"),  # MAS_DA in I2C master mode
        ("3", "AUX1_SCLK", "output"),  # MAS_CLK in I2C master mode
        ("4", "INT1", "output"),
        ("5", "VDDIO", "power_in"),
        ("6", "GND", "power_in"),
        ("7", "RESV", "passive"),  # NC, or tie to VDDIO or GND
        ("8", "VDD", "power_in"),
        ("9", "INT2", "output"),  # FSYNC / CLKIN alternate
        ("10", "AUX1_CS", "output"),
        ("11", "AUX1_SDO", "input"),
        ("12", "AP_CS", "input"),
        ("13", "AP_SCLK", "input"),  # AP_SCL in I2C mode
        ("14", "AP_SDI", "input"),  # AP_SDA in I2C mode
    ],
    verified=True,
    checked_against="TDK InvenSense ICM-45686 datasheet DS-000577 Rev 1.0 "
    "(2024-08-02), section 'Pin Out Diagram and Signal Description'.",
)

QMC6309 = Pinout(
    name="QMC6309",
    description="3-axis magnetometer, I2C, fixed device id 0x7c",
    package="DFN-6_1.6x1.6mm_P0.5mm",
    pins=[
        ("1", "SCL", "input"),
        ("2", "GND", "power_in"),
        ("3", "SDA", "bidirectional"),
        ("4", "VDD", "power_in"),
        ("5", "NC", "no_connect"),
        ("6", "DRDY", "output"),
    ],
    verified=False,
)

ESP32_C5_WROOM = Pinout(
    name="ESP32-C5-WROOM-1",
    description="Dual-band Wi-Fi 6 module. GPIO16-22 flash, 13-14 USB-JTAG",
    package="ESP32-C5-WROOM-1",
    pins=(
        [("1", "GND", "power_in"), ("2", "3V3", "power_in"), ("3", "EN", "input")]
        + [(str(4 + i), f"IO{i}", "bidirectional") for i in range(0, 13)]
        + [("17", "USB_D-", "bidirectional"), ("18", "USB_D+", "bidirectional")]
        + [(str(19 + i), f"IO{23 + i}", "bidirectional") for i in range(0, 2)]
        + [("21", "IO24", "bidirectional"), ("22", "IO25", "bidirectional")]
        + [("23", "TXD0", "output"), ("24", "RXD0", "input")]
        + [("25", "GND", "power_in"), ("26", "GND", "power_in")]
    ),
    verified=False,
)

# Only parts we still have to generate a symbol for. QMC6309 and ESP32-C5-WROOM-1 are
# sourced from vendored libraries instead.
ALL = {"ICM45686": ICM45686}

SOURCED = {
    "ESP32-C5-WROOM-1": "vendor/Espressif.kicad_sym (Espressif official)",
    "QMC6309": "vendor/Mumo.kicad_sym (4-pad WLCSP: A1/A2/B1/B2)",
}


def unverified():
    return [p for p in ALL.values() if not p.verified]

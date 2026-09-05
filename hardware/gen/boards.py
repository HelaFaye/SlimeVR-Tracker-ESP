"""The two board definitions: components and the net attached to each pin.

Nets are named, not drawn. The generator emits a global label on every pin, which is a
legitimate schematic style and the only one that produces readable output without a
routing algorithm. Anything with the same label is the same net.
"""
from dataclasses import dataclass


@dataclass
class Comp:
    ref: str
    part: str          # key into parts.ALL_PARTS
    value: str
    pins: dict         # pin number -> net name
    note: str = ""


# --------------------------------------------------------------- sensor node board
#
# ATtiny412 chip-select controller, gated sensor VCC, two RJ45s on the same shared bus.

NODE_BOARD = [
    Comp("J1", "RJ45", "RJ45-IN", {
        "1": "VBUS", "2": "GND", "3": "SPI_SCK", "4": "SPI_MOSI",
        "5": "SPI_MISO", "6": "CS_STROBE", "7": "CHAIN_SDA", "8": "CHAIN_SCL",
    }, "chain in"),
    Comp("J2", "RJ45", "RJ45-OUT", {
        "1": "VBUS", "2": "GND", "3": "SPI_SCK", "4": "SPI_MOSI",
        "5": "SPI_MISO", "6": "CS_STROBE", "7": "CHAIN_SDA", "8": "CHAIN_SCL",
    }, "chain out - wired pin-for-pin in parallel with J1, zero-length stub"),

    Comp("U1", "ATTINY412", "ATtiny412", {
        "1": "VBUS", "2": "UPDI", "3": "CHAIN_SDA", "4": "CHAIN_SCL",
        "5": "SENSOR_PWR_G", "6": "CS_STROBE", "7": "CS_IMU", "8": "GND",
    }, "I2SPI controller"),

    Comp("Q1", "MOSFET_P", "DMG2305UX", {
        "1": "SENSOR_PWR_G", "2": "VBUS", "3": "VSENSOR",
    }, "high-side pass FET: gate low = sensor powered"),
    Comp("R1", "R", "100k", {"1": "SENSOR_PWR_G", "2": "VBUS"},
         "gate pull-up: sensor OFF whenever the ATtiny is not driving"),

    Comp("U2", "ICM45686", "ICM-45686", {
        "1": "AUX_SCL", "2": "AUX_SDA", "3": "NC", "4": "NC",
        "5": "VSENSOR", "6": "GND", "7": "NC", "8": "VSENSOR",
        "9": "SPI_MISO", "10": "CS_IMU", "11": "SPI_SCK", "12": "SPI_MOSI",
        "13": "NC", "14": "GND",
    }, "gated supply; INT pins deliberately unconnected, see DEC-004"),

    Comp("U3", "QMC6309", "QMC6309", {
        "1": "AUX_SCL", "2": "GND", "3": "AUX_SDA",
        "4": "VSENSOR", "5": "NC", "6": "NC",
    }, "on the IMU AUX1 bus, not the chain"),

    Comp("R2", "R", "4k7", {"1": "AUX_SDA", "2": "VSENSOR"}, "AUX1 pull-up"),
    Comp("R3", "R", "4k7", {"1": "AUX_SCL", "2": "VSENSOR"}, "AUX1 pull-up"),
    Comp("R4", "R", "4k7", {"1": "UPDI", "2": "VBUS"}, "UPDI pull-up"),

    Comp("C1", "C", "100n", {"1": "VBUS", "2": "GND"}, "ATtiny decoupling"),
    Comp("C2", "C", "100n", {"1": "VSENSOR", "2": "GND"}, "IMU decoupling"),
    Comp("C3", "C", "100n", {"1": "VSENSOR", "2": "GND"}, "mag decoupling"),
    Comp("C4", "C", "10u", {"1": "VBUS", "2": "GND"},
         "bulk - node is at the end of up to 850mm of thin cable"),
    Comp("C5", "C", "1u", {"1": "VSENSOR", "2": "GND"},
         "gated-rail bulk; sets the ramp the 10ms settle delay waits for"),

    Comp("TP1", "TESTPAD", "UPDI", {"1": "UPDI"}, "programming pad"),
]

# ------------------------------------------------------------------- hub board

HUB_BOARD = [
    Comp("U1", "ESP32_C5", "ESP32-C5-WROOM-1", {
        "1": "GND", "2": "3V3", "3": "EN",
        "4": "BOOT", "5": "VBAT_SENSE", "6": "IO2", "7": "CS_LOCAL",
        "8": "CHAIN_SCL", "9": "CHAIN_SDA", "10": "CS_STROBE", "11": "IO7",
        "12": "LED", "13": "IMU_INT", "14": "SPI_SCK", "15": "SPI_MISO",
        "16": "SPI_MOSI", "17": "USB_DM", "18": "USB_DP",
        "19": "USB_CC1", "20": "USB_CC2", "25": "GND", "26": "GND",
    }, "dual-band; band selected explicitly at runtime, see DEC-002"),

    Comp("U2", "ICM45686", "ICM-45686", {
        "1": "AUX_SCL", "2": "AUX_SDA", "3": "NC", "4": "NC",
        "5": "3V3", "6": "GND", "7": "NC", "8": "3V3",
        "9": "SPI_MISO", "10": "CS_LOCAL", "11": "SPI_SCK", "12": "SPI_MOSI",
        "13": "IMU_INT", "14": "GND",
    }, "hub's own IMU - NOT power gated, and its CS never leaves the board"),

    Comp("U3", "QMC6309", "QMC6309", {
        "1": "AUX_SCL", "2": "GND", "3": "AUX_SDA",
        "4": "3V3", "5": "NC", "6": "NC",
    }),

    Comp("J1", "RJ45", "RJ45-CHAIN", {
        "1": "3V3", "2": "GND", "3": "SCK_T", "4": "MOSI_T",
        "5": "SPI_MISO", "6": "STROBE_T", "7": "CHAIN_SDA", "8": "CHAIN_SCL",
    }, "to the sensor chain"),

    # Source termination at the hub end. Highest-value SI measure on ribbon cable.
    Comp("R1", "R", "33", {"1": "SPI_SCK", "2": "SCK_T"}, "series termination"),
    Comp("R2", "R", "33", {"1": "SPI_MOSI", "2": "MOSI_T"}, "series termination"),
    Comp("R3", "R", "33", {"1": "CS_STROBE", "2": "STROBE_T"}, "series termination"),

    # Chain I2C pull-ups live only here. Nodes must not populate their own.
    Comp("R4", "R", "2k2", {"1": "CHAIN_SDA", "2": "3V3"}, "chain pull-up, hub only"),
    Comp("R5", "R", "2k2", {"1": "CHAIN_SCL", "2": "3V3"}, "chain pull-up, hub only"),

    Comp("R6", "R", "4k7", {"1": "AUX_SDA", "2": "3V3"}, "AUX1 pull-up"),
    Comp("R7", "R", "4k7", {"1": "AUX_SCL", "2": "3V3"}, "AUX1 pull-up"),

    Comp("U4", "LDO", "AP2112K-3.3", {
        "1": "VBAT", "2": "GND", "3": "VBAT", "4": "NC", "5": "3V3",
    }),
    Comp("U5", "CHARGER", "MCP73831", {
        "1": "VUSB", "2": "GND", "3": "VBAT", "4": "PROG", "5": "STAT",
    }),
    Comp("R8", "R", "2k", {"1": "PROG", "2": "GND"}, "500mA charge current"),
    Comp("J2", "CONN_BATT", "LiPo", {"1": "VBAT", "2": "GND"}),

    # Divider matches BAT_EXTERNAL r1=100k r2=220k in board-defaults.json.
    Comp("R9", "R", "100k", {"1": "VBAT", "2": "VBAT_SENSE"}, "battery divider"),
    Comp("R10", "R", "220k", {"1": "VBAT_SENSE", "2": "GND"}, "battery divider"),

    Comp("D1", "LED", "LED", {"1": "LED", "2": "R11_A"}),
    Comp("R11", "R", "1k", {"1": "R11_A", "2": "GND"}),

    Comp("C1", "C", "100n", {"1": "3V3", "2": "GND"}),
    Comp("C2", "C", "100n", {"1": "3V3", "2": "GND"}),
    Comp("C3", "C", "10u", {"1": "3V3", "2": "GND"}),
    Comp("C4", "C", "22u", {"1": "VBAT", "2": "GND"}),

    # Module reset. Without the RC the C5 can boot before its supply is stable.
    Comp("R12", "R", "100k", {"1": "EN", "2": "3V3"}, "EN pull-up"),
    Comp("SW1", "CONN_BATT", "BOOT", {"1": "BOOT", "2": "GND"}, "boot mode button"),
    Comp("R16", "R", "10k", {"1": "IO2", "2": "GND"},
         "IO2 is a strapping pin: hold it defined"),
    Comp("R17", "R", "10k", {"1": "IO7", "2": "3V3"},
         "IO7 is a strapping pin: hold it defined"),
    Comp("C5", "C", "100n", {"1": "EN", "2": "GND"}, "EN delay"),

    Comp("J3", "CONN_USB", "USB-C", {
        "A4": "VUSB", "A9": "VUSB", "A1": "GND", "A12": "GND",
        "A6": "USB_DP", "A7": "USB_DM",
    }, "charge and flash"),
    Comp("R13", "R", "5k1", {"1": "USB_CC1", "2": "GND"}, "USB-C sink"),
    Comp("R14", "R", "5k1", {"1": "USB_CC2", "2": "GND"}, "USB-C sink"),

    Comp("D2", "LED", "CHG", {"1": "3V3", "2": "STAT_A"}, "charge status"),
    Comp("R15", "R", "1k", {"1": "STAT_A", "2": "STAT"}),
]

BOARDS = {
    "node": {
        "title": "SlimeVR I2SPI sensor node",
        "comps": NODE_BOARD,
        "size_mm": (26.0, 20.0),
        "description": "ATtiny412 + gated ICM-45686 + QMC6309, two RJ45 jacks",
    },
    "hub": {
        "title": "SlimeVR I2SPI hub (ESP32-C5)",
        "comps": HUB_BOARD,
        "size_mm": (45.0, 30.0),
        "description": "ESP32-C5, local IMU, battery, one chain port",
    },
}

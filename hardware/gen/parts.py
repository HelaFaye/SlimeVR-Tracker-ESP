"""
Part library for the SlimeVR I2SPI boards.

Every entry names a real KiCad 7 symbol and footprint, plus an LCSC part number so the
generated BOM can go straight to JLCPCB assembly. Symbols are verified against the
installed libraries by `verify.py` rather than trusted.

**LCSC part numbers are deliberately absent.** An earlier revision of this file carried
specific numbers that were fabricated rather than looked up - the one that could be
checked (ICM-45686-P) was wrong: JLCPCB lists it as C9900251359, not the C5457057 that
had been written here. A wrong-but-plausible part number in a BOM sent to assembly gets
the wrong component soldered to every board, so they are now `None` until someone looks
each one up on jlcpcb.com. The BOM exports an empty LCSC column, which fails loudly at
upload rather than quietly at assembly.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Part:
    ref_prefix: str
    # "Library:Symbol", or several separated by "|" tried in order. KiCad's stock
    # libraries reorganise between major versions - a symbol that exists in 7 may have
    # moved or been renamed by 10 - so parts that are likely to drift list alternatives
    # rather than pinning one name that will rot.
    symbol: str
    footprint: str  # "Library:Footprint", same "|" convention
    value: str
    lcsc: Optional[str] = None
    description: str = ""
    # Pin name -> net name, filled in per instance by the board definitions.
    default_nets: dict = field(default_factory=dict)


# --------------------------------------------------------------------- active parts

ESP32_C5 = Part(
    ref_prefix="U",
    # KiCad 7 ships no C5, ICM-45686 or QMC6309 symbol - all three are too new. They
    # come from the project library that mklib.py generates. See pinouts.py for the
    # verification status of each.
    symbol="Espressif:ESP32-C5-WROOM-1",
    footprint="Espressif:ESP32-C5-WROOM-1",
    value="ESP32-C5-WROOM-1",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="Dual-band Wi-Fi 6 RISC-V module",
)

ICM45686 = Part(
    ref_prefix="U",
    symbol="slimevr-i2spi:ICM-45686",
    footprint="slimevr-i2spi:LGA-14_2.5x3mm_P0.5mm",
    value="ICM-45686",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="6-axis IMU, SPI + AUX1 I2C master",
)

QMC6309 = Part(
    ref_prefix="U",
    symbol="Mumo:QMC6309",
    footprint="Mumo:QMC6309",
    value="QMC6309",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="3-axis magnetometer, on the IMU AUX1 bus",
)

ATTINY412 = Part(
    ref_prefix="U",
    symbol="MCU_Microchip_ATtiny:ATtiny412-SS",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    value="ATtiny412",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="I2SPI chip-select controller",
)

MOSFET_P = Part(
    ref_prefix="Q",
    # Q_PMOS_GSD is present in KiCad 7 but absent in 10; the pin-order variants and the
    # part-specific symbol are the plausible replacements. Whichever resolves, check the
    # pin order against the DMG2305UX datasheet before laying out - G/S/D ordering is
    # exactly the kind of thing that silently differs.
    symbol="Device:Q_PMOS_GSD|Device:Q_PMOS_GDS|Device:Q_PMOS_DGS|Transistor_FET:DMG2305UX",
    footprint="Package_TO_SOT_SMD:SOT-23",
    value="DMG2305UX",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="P-channel high-side switch for gated sensor VCC",
)

OR_GATE = Part(
    ref_prefix="U",
    symbol="74xGxx:74LVC1G32",
    footprint="Package_TO_SOT_SMD:SOT-353_SC-70-5",
    value="74LVC1G32",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="CS = CS_STROBE OR ARMED_N (EXTERNAL_CS_GATE variant only)",
)

RJ45 = Part(
    ref_prefix="J",
    symbol="Connector:Conn_01x08_Pin",
    footprint="Connector_RJ:RJ45_Amphenol_54602-x08_Horizontal",
    value="RJ45",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="8P8C jack, straight-through",
)

LDO = Part(
    ref_prefix="U",
    symbol="Regulator_Linear:AP2112K-3.3",
    footprint="Package_TO_SOT_SMD:SOT-23-5",
    value="AP2112K-3.3",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="3V3 LDO, 600 mA",
)

CHARGER = Part(
    ref_prefix="U",
    symbol="Battery_Management:MCP73831-2-OT",
    footprint="Package_TO_SOT_SMD:SOT-23-5",
    value="MCP73831",
    lcsc=None,  # TODO look up on jlcpcb.com
    description="Single-cell LiPo charger",
)

# --------------------------------------------------------------------- passives

R = Part("R", "Device:R", "Resistor_SMD:R_0402_1005Metric", "R", None, "resistor")
C = Part("C", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "C", None, "capacitor")
LED = Part(
    "D",
    "Device:LED",
    "LED_SMD:LED_0603_1608Metric",
    "LED",
    None,  # TODO look up on jlcpcb.com
    "status indicator",
)
CONN_BATT = Part(
    "J",
    "Connector:Conn_01x02_Pin",
    "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
    "LiPo",
    None,
    "battery connector",
)
TESTPAD = Part(
    "TP",
    "Connector:TestPoint",
    "TestPoint:TestPoint_Pad_D1.0mm",
    "UPDI",
    None,
    "UPDI programming pad",
)


CONN_USB = Part(
    "J",
    "Connector:USB_C_Receptacle",
    "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
    "USB-C",
    None,  # TODO look up on jlcpcb.com
    "charge and flash port",
)


ALL_PARTS = {
    name: value
    for name, value in list(globals().items())
    if isinstance(value, Part)
}

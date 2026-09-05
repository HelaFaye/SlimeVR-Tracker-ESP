"""Emit hardware/lib/slimevr-i2spi.kicad_sym for the parts KiCad 7 doesn't ship.

Symbols are laid out mechanically: inputs left, outputs right, power top/bottom. Not
pretty, but electrically correct and readable, which is what a generated symbol needs
to be.
"""
import argparse
import sys
from pathlib import Path

import pinouts

LIB = Path(__file__).resolve().parents[1] / "lib" / "slimevr-i2spi.kicad_sym"

LEFT = {"input", "power_in", "passive"}


def emit_symbol(p):
    warn = "" if p.verified else "  *** PINOUT NOT VERIFIED AGAINST DATASHEET ***"
    left = [x for x in p.pins if x[2] in LEFT]
    right = [x for x in p.pins if x[2] not in LEFT]
    rows = max(len(left), len(right))
    height = max(rows * 2.54 + 5.08, 12.7)
    half = height / 2
    width = 25.4

    out = [
        f'  (symbol "{p.name}" (pin_names (offset 1.016)) (in_bom yes) (on_board yes)',
        f'    (property "Reference" "U" (at 0 {half + 2.54:.2f} 0)',
        "      (effects (font (size 1.27 1.27)))",
        "    )",
        f'    (property "Value" "{p.name}" (at 0 {-half - 2.54:.2f} 0)',
        "      (effects (font (size 1.27 1.27)))",
        "    )",
        f'    (property "Footprint" "slimevr-i2spi:{p.package}" (at 0 0 0)',
        "      (effects (font (size 1.27 1.27)) hide)",
        "    )",
        f'    (property "Datasheet" "{p.description}{warn}" (at 0 0 0)',
        "      (effects (font (size 1.27 1.27)) hide)",
        "    )",
        f'    (symbol "{p.name}_0_1"',
        f"      (rectangle (start {-width / 2:.2f} {half:.2f}) "
        f"(end {width / 2:.2f} {-half:.2f})",
        "        (stroke (width 0.254) (type default)) (fill (type background))",
        "      )",
        "    )",
        f'    (symbol "{p.name}_1_1"',
    ]

    for i, (num, name, etype) in enumerate(left):
        y = half - 2.54 * (i + 1)
        out += [
            f'      (pin {etype} line (at {-width / 2 - 5.08:.2f} {y:.2f} 0) '
            f"(length 5.08)",
            f'        (name "{name}" (effects (font (size 1.27 1.27))))',
            f'        (number "{num}" (effects (font (size 1.27 1.27))))',
            "      )",
        ]
    for i, (num, name, etype) in enumerate(right):
        y = half - 2.54 * (i + 1)
        out += [
            f'      (pin {etype} line (at {width / 2 + 5.08:.2f} {y:.2f} 180) '
            f"(length 5.08)",
            f'        (name "{name}" (effects (font (size 1.27 1.27))))',
            f'        (number "{num}" (effects (font (size 1.27 1.27))))',
            "      )",
        ]

    out += ["    )", "  )"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-unverified", action="store_true")
    args = ap.parse_args()

    bad = pinouts.unverified()
    if bad and not args.allow_unverified:
        print("Refusing to emit: these pinouts have not been checked against a datasheet:")
        for p in bad:
            print(f"  - {p.name} ({p.package})")
        print("\nCheck them and set verified=True in pinouts.py, or pass")
        print("--allow-unverified to generate anyway for layout trials.")
        return 1

    LIB.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(emit_symbol(p) for p in pinouts.ALL.values())
    LIB.write_text(
        '(kicad_symbol_lib (version 20220914) (generator slimevr_i2spi_gen)\n'
        f"{body}\n)\n"
    )
    print(f"wrote {LIB}")
    make_footprints()
    if bad:
        print(f"WARNING: {len(bad)} unverified pinout(s) included:")
        for p in bad:
            print(f"  - {p.name}")
    return 0


# --------------------------------------------------------------------- footprints
#
# Land patterns generated from package geometry. Dimensions are nominal for the package
# family; the same verification caveat as the pinouts applies, and for footprints the
# consequence of getting it wrong is a board you cannot assemble.

PRETTY = LIB.parent / "slimevr-i2spi.pretty"


def pad(num, x, y, w, h):
    return (
        f'  (pad "{num}" smd rect (at {x:.3f} {y:.3f}) (size {w:.2f} {h:.2f}) '
        f"(layers F.Cu F.Paste F.Mask))"
    )


def emit_footprint(name, pads, body_w, body_h):
    lines = [
        f'(footprint "{name}" (version 20221018) (generator slimevr_i2spi_gen)',
        "  (layer F.Cu)",
        "  (attr smd)",
        f'  (fp_text reference "REF**" (at 0 {-body_h / 2 - 1:.2f}) (layer F.SilkS)',
        "    (effects (font (size 0.8 0.8) (thickness 0.12))))",
        f'  (fp_text value "{name}" (at 0 {body_h / 2 + 1:.2f}) (layer F.Fab)',
        "    (effects (font (size 0.8 0.8) (thickness 0.12))))",
        f"  (fp_rect (start {-body_w / 2:.2f} {-body_h / 2:.2f}) "
        f"(end {body_w / 2:.2f} {body_h / 2:.2f}) (layer F.Fab) "
        "(stroke (width 0.1) (type default)) (fill none))",
    ]
    lines += pads
    lines.append(")")
    return "\n".join(lines)


def dual_row(count, pitch, row_span, pad_w, pad_h):
    """Standard two-row SMD land pattern, pin 1 bottom-left, counter-clockwise."""
    per_side = count // 2
    out = []
    start = -(per_side - 1) * pitch / 2
    for i in range(per_side):  # left column, top to bottom
        out.append(pad(i + 1, -row_span / 2, start + i * pitch, pad_w, pad_h))
    for i in range(per_side):  # right column, bottom to top
        out.append(
            pad(count - i, row_span / 2, start + i * pitch, pad_w, pad_h)
        )
    return out


def make_footprints():
    PRETTY.mkdir(parents=True, exist_ok=True)

    fps = {
        # ICM-45686: 14-pad LGA, 2.5 x 3.0 mm, 0.5 mm pitch
        "LGA-14_2.5x3mm_P0.5mm": (
            dual_row(14, 0.5, 2.2, 0.6, 0.28),
            2.5,
            3.0,
        ),
        # QMC6309: DFN-6, 1.6 x 1.6 mm, 0.5 mm pitch
        "DFN-6_1.6x1.6mm_P0.5mm": (
            dual_row(6, 0.5, 1.4, 0.5, 0.28),
            1.6,
            1.6,
        ),
        # ESP32-C5-WROOM-1: castellated module, 0.8 mm pitch, 18 x 25.5 mm
        "ESP32-C5-WROOM-1": (
            dual_row(26, 0.8, 16.0, 1.5, 0.9),
            18.0,
            25.5,
        ),
    }

    for name, (pads, w, h) in fps.items():
        (PRETTY / f"{name}.kicad_mod").write_text(emit_footprint(name, pads, w, h))
    print(f"wrote {len(fps)} footprints to {PRETTY}")


if __name__ == "__main__":
    sys.exit(main())

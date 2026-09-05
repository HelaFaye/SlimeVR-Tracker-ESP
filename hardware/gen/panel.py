"""KiKit panel configuration for a V-scored JLCPCB panel.

V-scoring is what makes the boards snap apart. It needs straight cuts all the way across
the panel, so boards are arranged in a grid of uniform cells rather than nested tightly -
that costs some panel area and buys a panel you can actually break by hand.
"""
import json
from pathlib import Path

import boards

# JLCPCB V-scoring constraints.
V_CUT_CLEARANCE_MM = 0.4
PANEL_RAIL_MM = 5.0
MAX_PANEL_MM = (400, 500)


def cell_size(selection):
    """One uniform cell, because V-cuts must run the full width and height."""
    w = max(boards.BOARDS[k]["size_mm"][0] for k in selection)
    h = max(boards.BOARDS[k]["size_mm"][1] for k in selection)
    return w + V_CUT_CLEARANCE_MM, h + V_CUT_CLEARANCE_MM


def layout(selection):
    total = sum(selection.values())
    cw, ch = cell_size(selection)
    usable = MAX_PANEL_MM[0] - 2 * PANEL_RAIL_MM
    cols = max(1, min(total, int(usable // cw)))
    rows = (total + cols - 1) // cols
    return cols, rows, cw, ch


def describe(selection):
    cols, rows, cw, ch = layout(selection)
    total = sum(selection.values())
    w = cols * cw + 2 * PANEL_RAIL_MM
    h = rows * ch + 2 * PANEL_RAIL_MM
    lines = [
        f"  {total} boards in a {cols} x {rows} grid, {cw:.1f} x {ch:.1f} mm cells",
        f"  panel {w:.1f} x {h:.1f} mm including {PANEL_RAIL_MM:.0f} mm rails",
    ]
    if w > MAX_PANEL_MM[0] or h > MAX_PANEL_MM[1]:
        lines.append("  WARNING: exceeds the assumed JLCPCB maximum; split the order")
    if rows * cols > total:
        lines.append(
            f"  {rows * cols - total} empty cell(s): V-cuts need a full grid, so the "
            "spare positions are free boards if you fill them"
        )
    return "\n".join(lines)


def write_config(selection, outdir):
    cols, rows, cw, ch = layout(selection)
    cfg = {
        "_comment": "kikit panelize --preset :this file. See hardware/README.md.",
        "layout": {
            "type": "grid",
            "rows": rows,
            "cols": cols,
            "hspace": f"{V_CUT_CLEARANCE_MM}mm",
            "vspace": f"{V_CUT_CLEARANCE_MM}mm",
        },
        "tabs": {"type": "full"},
        "cuts": {
            "type": "vcuts",
            "clearance": f"{V_CUT_CLEARANCE_MM}mm",
            "layer": "Cmts.User",
        },
        "framing": {
            "type": "railstb",
            "width": f"{PANEL_RAIL_MM}mm",
            "space": f"{V_CUT_CLEARANCE_MM}mm",
        },
        "tooling": {"type": "3hole", "hoffset": "2.5mm", "voffset": "2.5mm",
                    "size": "1.5mm"},
        "fiducials": {"type": "3fid", "hoffset": "5mm", "voffset": "2.5mm",
                      "coppersize": "1mm", "opening": "2mm"},
        "post": {"millradius": "1mm"},
        "_selection": {k: v for k, v in selection.items()},
    }
    path = Path(outdir) / "panel.json"
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    return path

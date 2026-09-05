"""Build wizard: pick boards and quantities, emit projects, BOM and a panel config.

    python3 hardware/gen/wizard.py                 # interactive
    python3 hardware/gen/wizard.py --preset 18point
    python3 hardware/gen/wizard.py --node 8 --hub 5
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import boards
import mksch
import parts
import pinouts

OUT = Path(__file__).resolve().parents[1] / "out"

PRESETS = {
    "18point": {"hub": 5, "node": 8, "why": "5 hubs + 8 extensions (15 sites, 18 points)"},
    "18point-palms": {"hub": 5, "node": 10, "why": "as above plus two palm nodes"},
    "single": {"hub": 1, "node": 2, "why": "one chain for bring-up"},
    "spares": {"hub": 0, "node": 4, "why": "extension spares only"},
}


def bom(selection):
    """Aggregate across every board instance. JLCPCB wants one row per part number."""
    rows = Counter()
    meta = {}
    for board_key, qty in selection.items():
        for comp in boards.BOARDS[board_key]["comps"]:
            part = parts.ALL_PARTS[comp.part]
            key = (part.value if part.lcsc else comp.value, part.footprint, part.lcsc)
            rows[key] += qty
            meta.setdefault(key, []).append(f"{board_key}:{comp.ref}")
    return rows, meta


def write_bom(selection, path):
    rows, meta = bom(selection)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC", "Qty"])
        for (value, footprint, lcsc), qty in sorted(
            rows.items(), key=lambda kv: -kv[1]
        ):
            refs = ",".join(sorted(set(meta[(value, footprint, lcsc)])))
            w.writerow([value, refs, footprint, lcsc or "", qty])
    return sum(rows.values())


def prompt(selection):
    print("Presets:")
    for name, p in PRESETS.items():
        print(f"  {name:<16} {p['why']}")
    print()
    choice = input("preset name, or blank to choose per board: ").strip()
    if choice in PRESETS:
        return {k: v for k, v in PRESETS[choice].items() if k != "why"}

    for key, board in sorted(boards.BOARDS.items()):
        print(f"\n  {key}: {board['description']}")
        raw = input(f"  how many {key} boards? [0] ").strip()
        selection[key] = int(raw) if raw.isdigit() else 0
    return selection


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", choices=sorted(PRESETS))
    for key in sorted(boards.BOARDS):
        ap.add_argument(f"--{key}", type=int, default=None, metavar="N")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    selection = {}
    if args.preset:
        selection = {k: v for k, v in PRESETS[args.preset].items() if k != "why"}
    elif any(getattr(args, k) is not None for k in boards.BOARDS):
        selection = {k: (getattr(args, k) or 0) for k in boards.BOARDS}
    else:
        selection = prompt(selection)

    selection = {k: v for k, v in selection.items() if v > 0}
    if not selection:
        print("Nothing selected.")
        return 1

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    print("\nSelected:")
    for key, qty in sorted(selection.items()):
        print(f"  {qty} x {key:<6} {boards.BOARDS[key]['description']}")

    print("\nSchematics:")
    for key in sorted(selection):
        path = mksch.generate(key, outdir / key)
        print(f"  {key:<6} -> {path.relative_to(outdir.parent)}")

    bom_path = outdir / "bom-jlcpcb.csv"
    total = write_bom(selection, bom_path)
    print(f"\nBOM: {total} placements -> {bom_path.relative_to(outdir.parent)}")

    import panel
    cfg = panel.write_config(selection, outdir)
    print(f"Panel: {cfg.relative_to(outdir.parent)}")
    print(panel.describe(selection))

    unverified = pinouts.unverified()
    if unverified:
        print("\n" + "!" * 68)
        print("These pinouts have NOT been checked against a datasheet:")
        for p in unverified:
            print(f"  - {p.name} ({p.package})")
        print("A schematic on a wrong pinout looks correct and is not.")
        print("Check them in hardware/gen/pinouts.py before ordering.")
        print("!" * 68)

    print("\nNext: open the schematics, run ERC, lay out each board, then panelise.")
    print("Layout is NOT generated - see hardware/README.md for why.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

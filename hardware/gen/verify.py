"""Check every symbol and footprint named in parts.py against the installed libraries.

Run this before trusting anything the generator emits. A wrong lib_id produces a
schematic that opens with broken symbols, which is a slow way to find a typo.
"""
import sys
from pathlib import Path

import parts

PROJECT_LIB = Path(__file__).resolve().parents[1] / "lib"
VENDOR_LIB = PROJECT_LIB / "vendor"
SYM_DIRS = [PROJECT_LIB, VENDOR_LIB, Path("/usr/share/kicad/symbols"),
            Path.home() / ".local/share/kicad/symbols"]
FP_DIRS = [PROJECT_LIB, VENDOR_LIB, Path("/usr/share/kicad/footprints"),
           Path.home() / ".local/share/kicad/footprints"]


def symbol_exists(lib_id):
    lib, name = lib_id.split(":", 1)
    for d in SYM_DIRS:
        f = d / f"{lib}.kicad_sym"
        if f.exists():
            text = f.read_text(encoding="utf-8", errors="replace")
            if f'(symbol "{name}"' in text:
                return True, "ok"
            return False, f"library {lib} has no symbol {name}"
    return False, f"no such symbol library: {lib}"


def footprint_exists(lib_id):
    lib, name = lib_id.split(":", 1)
    for d in FP_DIRS:
        f = d / f"{lib}.pretty" / f"{name}.kicad_mod"
        if f.exists():
            return True, "ok"
        if (d / f"{lib}.pretty").exists():
            return False, f"library {lib} has no footprint {name}"
        continue
    return False, f"no such footprint library: {lib}"


def main():
    bad = 0
    for name, part in sorted(parts.ALL_PARTS.items()):
        ok_s, msg_s = symbol_exists(part.symbol)
        ok_f, msg_f = footprint_exists(part.footprint)
        status = "ok  " if (ok_s and ok_f) else "FAIL"
        print(f"  [{status}] {name:<12} {part.symbol}")
        if not ok_s:
            print(f"           symbol:    {msg_s}")
            bad += 1
        if not ok_f:
            print(f"           footprint: {msg_f}")
            bad += 1
    print(f"\n{len(parts.ALL_PARTS)} parts, {bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

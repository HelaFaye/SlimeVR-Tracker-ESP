"""Check every symbol and footprint named in parts.py against the installed libraries.

Run this before trusting anything the generator emits. A wrong lib_id produces a
schematic that opens with broken symbols, which is a slow way to find a typo.
"""
import re
import sys
from pathlib import Path

import parts

import os

PROJECT_LIB = Path(__file__).resolve().parents[1] / "lib"
VENDOR_LIB = PROJECT_LIB / "vendor"

# Distributions disagree about where KiCad's libraries live, and the KiCad major version
# is part of the path on some of them. Search the common locations; override with
# KICAD_SYMBOL_DIR / KICAD_FOOTPRINT_DIR if yours is somewhere else.
#   Arch:   /usr/share/kicad/{symbols,footprints}   (package: kicad-library)
#   Debian: /usr/share/kicad/{symbols,footprints}   (package: kicad-symbols, kicad-footprints)
#   macOS:  /Applications/KiCad/KiCad.app/Contents/SharedSupport/{symbols,footprints}
_PREFIXES = [
    Path("/usr/share/kicad"),
    Path("/usr/local/share/kicad"),
    Path.home() / ".local/share/kicad",
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport"),
]


def _dirs(kind, env):
    override = os.environ.get(env)
    found = [Path(override)] if override else []
    found += [p / kind for p in _PREFIXES]
    return [PROJECT_LIB, VENDOR_LIB] + found


SYM_DIRS = _dirs("symbols", "KICAD_SYMBOL_DIR")
FP_DIRS = _dirs("footprints", "KICAD_FOOTPRINT_DIR")


def _search_all_symbols(needle):
    """Names in the installed libraries that look like what was asked for."""
    hits = []
    for d in SYM_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.kicad_sym")):
            text = f.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'\(symbol "([^"]+)"', text):
                n = m.group(1)
                # Skip KiCad's internal unit sub-symbols (Name_0_1, Name_2_1, ...).
                if re.search(r'_\d+_\d+$', n):
                    continue
                if needle.lower() in n.lower():
                    hits.append(f"{f.stem}:{n}")
    return sorted(set(hits))[:8]


def symbol_exists(lib_id):
    """Accepts alternatives separated by '|'; the first that resolves wins."""
    if "|" in lib_id:
        tried = []
        for candidate in lib_id.split("|"):
            ok, msg = symbol_exists(candidate)
            if ok:
                return True, f"resolved to {candidate}"
            tried.append(candidate)
        return False, "none of the candidates exist: " + ", ".join(tried)

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
    if "|" in lib_id:
        for candidate in lib_id.split("|"):
            ok, _ = footprint_exists(candidate)
            if ok:
                return True, f"resolved to {candidate}"
        return False, "none of the candidates exist"

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
        shown = part.symbol.split("|")[0]
        note = ""
        if ok_s and msg_s.startswith("resolved to"):
            shown = msg_s.split("resolved to ")[1]
            if shown != part.symbol.split("|")[0]:
                note = "  (fallback)"
        print(f"  [{status}] {name:<12} {shown}{note}")
        if not ok_s:
            print(f"           symbol:    {msg_s}")
            # A missing symbol is nearly always a rename between KiCad versions, so say
            # what IS installed rather than leaving the reader to grep for it.
            stem = part.symbol.split("|")[0].split(":")[1]
            needle = stem.split("_")[1] if "_" in stem else stem
            near = _search_all_symbols(needle)
            if near:
                print(f"           candidates installed here: {', '.join(near)}")
            bad += 1
        if not ok_f:
            print(f"           footprint: {msg_f}")
            bad += 1
    print(f"\n{len(parts.ALL_PARTS)} parts, {bad} problems")
    if bad and not any(d.exists() for d in SYM_DIRS[2:]):
        print(
            "\nNo system KiCad symbol library found. Install one:\n"
            "  Arch:   sudo pacman -S kicad kicad-library\n"
            "  Debian: sudo apt install kicad-symbols kicad-footprints\n"
            "or point KICAD_SYMBOL_DIR / KICAD_FOOTPRINT_DIR at yours."
        )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

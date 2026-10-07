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


def _pin_sort(num):
    return (0, int(num)) if num.isdigit() else (1, num)


def symbol_pins(lib_id):
    """number -> pin name for one symbol, or None if it isn't installed."""
    lib, name = lib_id.split(":", 1)
    for d in SYM_DIRS:
        f = d / f"{lib}.kicad_sym"
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        pins = {}
        # Pins live in the unit sub-symbols (Name_0_1, Name_1_1, ...), not the parent.
        for m in re.finditer(re.escape(f'(symbol "{name}_'), text):
            start, depth, j = m.start(), 0, m.start()
            while True:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            block = text[start:j + 1]
            for pm in re.finditer(
                r'\(pin\s+\S+\s+\S+\s*\(at[^)]*\)\s*\(length[^)]*\)\s*'
                r'\(name\s+"([^"]*)".*?\(number\s+"([^"]*)"',
                block,
                re.S,
            ):
                pins.setdefault(pm.group(2), pm.group(1))
        return pins or None
    return None


def pins_match(lib_id, required):
    """True when every required pin number carries the required function."""
    pins = symbol_pins(lib_id)
    if pins is None:
        return False, "symbol not installed"
    wrong = {
        num: (fn, pins.get(num, "<absent>"))
        for num, fn in required.items()
        if pins.get(num, "").upper() != fn.upper()
    }
    if wrong:
        detail = ", ".join(
            f"pin {n} should be {want} but is {got}" for n, (want, got) in wrong.items()
        )
        return False, detail
    return True, "pin functions match"


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


def symbol_exists(lib_id, required_pins=None):
    """Accepts alternatives separated by '|'.

    With required_pins, a candidate must both exist AND have matching pin functions -
    existence alone is not enough, because a renamed symbol with a different pin order
    resolves cleanly and is wrong.
    """
    if "|" in lib_id:
        existed_but_wrong = []
        for candidate in lib_id.split("|"):
            ok, _ = symbol_exists(candidate)
            if not ok:
                continue
            if required_pins:
                good, detail = pins_match(candidate, required_pins)
                if not good:
                    existed_but_wrong.append(f"{candidate} ({detail})")
                    continue
            return True, f"resolved to {candidate}"
        if existed_but_wrong:
            return False, (
                "candidates exist but none has the required pin order: "
                + "; ".join(existed_but_wrong)
            )
        return False, "none of the candidates exist: " + lib_id.replace("|", ", ")

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
        ok_s, msg_s = symbol_exists(part.symbol, part.pin_functions)
        ok_f, msg_f = footprint_exists(part.footprint)

        # A single pinned symbol still has to satisfy its pin map; fold that into the
        # status before printing, so the headline never says ok next to a failure.
        pin_msg = None
        if ok_s and part.pin_functions and "|" not in part.symbol:
            good, detail = pins_match(part.symbol, part.pin_functions)
            if not good:
                pin_msg = detail

        status = "ok  " if (ok_s and ok_f and pin_msg is None) else "FAIL"
        shown = part.symbol.split("|")[0]
        note = ""
        if ok_s and msg_s.startswith("resolved to"):
            shown = msg_s.split("resolved to ")[1]
            if shown != part.symbol.split("|")[0]:
                note = "  (fallback)"
            if part.pin_functions:
                note += "  [pin order verified]"
        print(f"  [{status}] {name:<12} {shown}{note}")
        if not ok_s:
            print(f"           symbol:    {msg_s}")
            # A missing symbol is nearly always a rename between KiCad versions, so say
            # what IS installed rather than leaving the reader to grep for it.
            stem = part.symbol.split("|")[0].split(":")[1]
            needle = stem.split("_")[1] if "_" in stem else stem
            near = _search_all_symbols(needle)
            if near:
                print("           installed symbols matching "
                      f"{needle!r}, with their pin maps:")
                for cand in near:
                    pins = symbol_pins(cand)
                    if pins:
                        shown = ", ".join(
                            f"{n}={pins[n]}" for n in sorted(pins, key=_pin_sort)
                        )
                        print(f"             {cand}  [{shown}]")
                    else:
                        print(f"             {cand}")
                if part.pin_functions:
                    want = ", ".join(
                        f"{n}={f}" for n, f in sorted(part.pin_functions.items())
                    )
                    print(f"           this part needs: [{want}]")
            bad += 1
        if not ok_f:
            print(f"           footprint: {msg_f}")
            bad += 1
        if pin_msg:
            print(f"           PIN ORDER: {pin_msg}")
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


def have_system_libs():
    """True when a system KiCad symbol library is reachable.

    SYM_DIRS[:2] are this project's own libraries, which are always present; a
    system library beyond them is what the stock-symbol checks need. VERIFY.sh
    probes this so it can skip those suites instead of reporting an uninstalled
    KiCad as a dozen schematic defects.
    """
    return any(d.exists() for d in SYM_DIRS[2:])


if __name__ == "__main__":
    if "--have-libs" in sys.argv:
        sys.exit(0 if have_system_libs() else 1)
    sys.exit(main())

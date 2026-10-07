#!/usr/bin/env bash
# Every automated check in this project, in one place.
#
#   ./VERIFY.sh
#
# Needs no PlatformIO toolchain, no megaTinyCore and no hardware. Suites whose tools are
# missing are skipped with a note rather than failing, so a partial toolchain still gets
# you partial coverage. See docs/dev/SETUP.md for per-distribution package names.
#
# Overrides: CXX, AVR_GCC, CLANG_FORMAT, KICAD_SYMBOL_DIR, KICAD_FOOTPRINT_DIR.
set -uo pipefail
cd "$(dirname "$0")"

CXX=${CXX:-g++}
AVR_GCC=${AVR_GCC:-avr-gcc}
export CXX AVR_GCC

# clang-format's output changes between major versions, and CI pins 17. A different
# version will report violations that are not violations, so prefer a pinned binary and
# warn rather than fail if only another version is available.
pick_clang_format() {
  if [ -n "${CLANG_FORMAT:-}" ]; then echo "$CLANG_FORMAT"; return; fi
  for c in clang-format-17 clang-format; do
    command -v "$c" >/dev/null 2>&1 && { echo "$c"; return; }
  done
}
CLANG_FORMAT=$(pick_clang_format)

fail=0
skipped=()

have() { command -v "$1" >/dev/null 2>&1; }
run() {
  local title=$1; shift
  echo; echo "=== $title ==="
  "$@" || fail=1
}
skip() { skipped+=("$1 -- $2"); echo; echo "=== $1 ==="; echo "  skipped: $2"; }

if have "$CXX"; then
  run "Chain simulation (real bus sources vs a modelled chain)" sim/run.sh
else
  skip "Chain simulation" "no $CXX (Arch: base-devel, Debian: g++)"
fi

run "Numeric verification (docs vs recomputed values)" python3 sim/check_numbers.py

if have "$AVR_GCC"; then
  run "Node firmware, every build variant" extras/attiny-cs-node/test/compile-check.sh
else
  skip "Node firmware" "no $AVR_GCC (Arch: avr-gcc avr-libc, Debian: gcc-avr avr-libc)"
fi

# Both of these resolve stock KiCad symbols by pin function. Without an installed
# symbol library every part is unresolvable, and the pin-order guard's cases cannot
# fail for the reason they are testing either -- so they report environment, not
# defects. Skip them rather than turn an uninstalled KiCad into 24 schematic errors.
if python3 hardware/gen/verify.py --have-libs; then
  run "KiCad symbols and footprints" bash -c 'cd hardware/gen && python3 verify.py'
  run "Symbol pin-order guard" python3 hardware/gen/test_pin_order.py
else
  skip "KiCad symbols and footprints" \
    "no KiCad symbol library (Arch: kicad kicad-library, Debian: kicad-symbols kicad-footprints)"
  skip "Symbol pin-order guard" "needs the KiCad symbol library above"
fi
run "I2C address collisions" python3 hardware/gen/i2c_address_map.py --check

run "Board config generation" python3 -c '
import json, types
src = open("scripts/preprocessor.py").read().replace("Import(\"env\")", "pass")
src = src.split("schema_obj = _load_json")[0]
m = types.ModuleType("pp"); exec(compile(src, "pp", "exec"), m.__dict__)
n = len(m.build_boards(json.load(open("board-defaults.schema.json")),
                       json.load(open("board-defaults.json"))))
print(f"  {n} boards generate their flags")'

if [ -n "$CLANG_FORMAT" ]; then
  ver=$("$CLANG_FORMAT" --version | grep -oE '[0-9]+' | head -1)
  fmt_files=(src/sensorinterface/*.cpp src/sensorinterface/*.h
             src/sensors/SensorBuilder.cpp extras/attiny-cs-node/src/main.cpp)
  if [ "$ver" = "17" ]; then
    run "Formatting (clang-format 17)" "$CLANG_FORMAT" --dry-run --Werror "${fmt_files[@]}"
  else
    # A different major version reports differences that are not violations, so this
    # is advisory: shown, but it does not fail the run. Only the pinned 17 gates.
    echo; echo "=== Formatting (clang-format $ver, advisory) ==="
    echo "  CI pins 17 and the two disagree, so differences below may not be real."
    echo "  For a pinned copy: pipx install clang-format==17.0.6"
    "$CLANG_FORMAT" --dry-run --Werror "${fmt_files[@]}" \
      && echo "  no differences" \
      || echo "  differences above are not counted as failures (version mismatch)"
  fi
else
  skip "Formatting" "no clang-format (Arch: clang, Debian: clang-format-17)"
fi

echo
for s in ${skipped+"${skipped[@]}"}; do echo "SKIPPED: $s"; done
[ $fail -eq 0 ] && echo "ALL CHECKS PASSED" || echo "FAILURES ABOVE"
exit $fail

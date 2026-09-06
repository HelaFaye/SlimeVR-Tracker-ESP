#!/usr/bin/env bash
# Every automated check in this project, in one place.
#
#   ./VERIFY.sh
#
# Needs: g++, clang-format 17, python3, gcc-avr, and KiCad's symbol/footprint libraries.
# Does NOT need: a PlatformIO toolchain, megaTinyCore, or any hardware.
set -uo pipefail
cd "$(dirname "$0")"
fail=0
run() { echo; echo "=== $1 ==="; shift; "$@" || fail=1; }

run "Chain simulation (real bus sources vs a modelled chain)" sim/run.sh
run "Numeric verification (docs vs recomputed values)" python3 sim/check_numbers.py
run "Node firmware, every build variant" extras/attiny-cs-node/test/compile-check.sh
run "KiCad symbols and footprints" bash -c 'cd hardware/gen && python3 verify.py'
run "Board config generation" python3 -c '
import json, types
src = open("scripts/preprocessor.py").read().replace("Import(\"env\")", "pass")
src = src.split("schema_obj = _load_json")[0]
m = types.ModuleType("pp"); exec(compile(src, "pp", "exec"), m.__dict__)
n = len(m.build_boards(json.load(open("board-defaults.schema.json")),
                       json.load(open("board-defaults.json"))))
print(f"  {n} boards generate their flags")'
run "Formatting" clang-format --dry-run --Werror \
  src/sensorinterface/*.cpp src/sensorinterface/*.h \
  src/sensors/SensorBuilder.cpp extras/attiny-cs-node/src/main.cpp

echo
[ $fail -eq 0 ] && echo "ALL CHECKS PASSED" || echo "FAILURES ABOVE"
exit $fail

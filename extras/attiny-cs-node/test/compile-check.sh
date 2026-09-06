#!/usr/bin/env bash
# Syntax-check every node firmware build variant with avr-gcc, and confirm the
# compile-time guards reject invalid configurations.
#
# Needs only `apt install gcc-avr avr-libc` - no megaTinyCore, no hardware. The stubs
# stand in for the core's Arduino/Wire/Logic/Event headers, so this checks OUR code, not
# the core's. A clean run here does not mean it links against megaTinyCore; it means the
# firmware is free of syntax and type errors in every configuration we ship.
set -uo pipefail
cd "$(dirname "$0")"
SRC=../src/main.cpp
INC="-I stubs -I ../../../src/sensorinterface"
CC="avr-gcc -std=gnu++17 -mmcu=attiny412 -Os -Wall -Wextra -fsyntax-only $INC"
fail=0

VALID=(
  "-DNODE_ID=1"
  "-DNODE_ID=15"
  "-DNODE_ID=1 -DEXTERNAL_CS_GATE"
  "-DNODE_ID=1 -DNO_DIGITAL_WRITE_FAST"
  # Braces quoted: unquoted, bash expands {1,2,3} into three separate words.
  "-DNODE_ID=3 -DEXTERNAL_CS_GATE -DNUM_CHANNELS=3 -DARMED_N_PINS={1,2,3}"
  "-DNODE_ID=1 -DBASE_ADDRESS=0x40"
)
# Each of these must be refused by an #error, not silently built.
INVALID=(
  "-DNODE_ID=0"
  "-DNODE_ID=16"
  "-DNODE_ID=1 -DNUM_CHANNELS=3"   # multi-channel needs the external gate
  ""                                # no NODE_ID at all
)

echo "Valid configurations:"
for v in "${VALID[@]}"; do
  # shellcheck disable=SC2086  # deliberate word splitting; braces are protected below
  read -ra args <<<"$v"
  if out=$($CC "${args[@]}" -x c++ $SRC 2>&1) && [ -z "$out" ]; then
    echo "  [ok]   $v"
  else
    echo "  [FAIL] $v"; echo "$out" | head -5; fail=1
  fi
done

echo
echo "Configurations that must be refused:"
for v in "${INVALID[@]}"; do
  # Capture first, then grep. Piping the compiler straight into grep under
  # `set -o pipefail` makes the pipeline inherit the compiler's non-zero exit, which
  # inverts the test: every correctly-refused config reads as accepted.
  read -ra args <<<"$v"
  out=$($CC "${args[@]}" -x c++ $SRC 2>&1 || true)
  if grep -q error <<<"$out"; then
    echo "  [ok]   refused: ${v:-no NODE_ID}"
  else
    echo "  [FAIL] accepted: ${v:-no NODE_ID}"; fail=1
  fi
done

echo
[ $fail -eq 0 ] && echo "PASS" || echo "FAIL"
exit $fail

#!/usr/bin/env bash
# Host unit test for SoftFusion::MagDriver against modelled MMC5983MA and LIS3MDL.
set -euo pipefail
cd "$(dirname "$0")"
SRC=../src
out=$(mktemp -d)
trap 'rm -rf -- "$out"' EXIT
"${CXX:-g++}" -std=gnu++2a -O1 -Wall -Wextra -g \
  -I stubs -I stubs/logging -I "$SRC" -I "$SRC/sensorinterface" \
  test_magdriver.cpp "$SRC/sensors/softfusion/magdriver.cpp" logstub_quiet.cpp \
  -o "$out/test_magdriver"
"$out/test_magdriver"

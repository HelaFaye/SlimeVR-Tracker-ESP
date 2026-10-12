#!/usr/bin/env bash
# Host build of the I2SPI chain simulation. No toolchain, no hardware.
set -euo pipefail
cd "$(dirname "$0")"
SRC=../src
g++ -std=gnu++2a -O1 -Wall -Wextra -Wshadow -Wnon-virtual-dtor -Wold-style-cast -Wconversion -g \
  -I stubs -I stubs/logging -I "$SRC" -I "$SRC/sensorinterface" -I ../lib/bno080 \
  main.cpp chain_model.cpp logstub.cpp \
  "$SRC/sensorinterface/ATTinyCSInterface.cpp" \
  "$SRC/sensorinterface/DirectSPIInterface.cpp" \
  "$SRC/sensorinterface/DirectPinInterface.cpp" \
  -o /tmp/i2spi-sim
exec /tmp/i2spi-sim

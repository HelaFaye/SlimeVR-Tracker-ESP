#!/usr/bin/env bash
# Exhaustive sweep of every I2SPI chain topology: arming, one-hot, address isolation,
# per-node reachability.
#
#   sim/sweep.sh                 # all 3^15 topologies
#   sim/sweep.sh --nodes 10      # smaller topology space (3^10) for a quick pass
#
# The range-of-motion half (the server: assignment, skeleton solve, constraints, palm FK)
# moved with the synthetic tracker to HelaFaye/SlimeVR-Server, tools/synthetic-tracker/.
set -uo pipefail
cd "$(dirname "$0")"

NODES=15
while [ $# -gt 0 ]; do
  case "$1" in
    --nodes) NODES=$2; shift 2;;
    *) echo "unknown option: $1"; exit 2;;
  esac
done

CXX=${CXX:-g++}
BIN=/tmp/i2spi-topology-sweep
fail=0

echo "=== Topology sweep: 3^$NODES configurations ==="
$CXX -std=gnu++2a -O2 \
  -I stubs -I stubs/logging -I ../src -I ../src/sensorinterface -I ../lib/bno080 \
  topology_sweep.cpp chain_model.cpp logstub_quiet.cpp \
  ../src/sensorinterface/ATTinyCSInterface.cpp \
  ../src/sensorinterface/DirectSPIInterface.cpp \
  ../src/sensorinterface/DirectPinInterface.cpp \
  -o "$BIN" || exit 1
"$BIN" --nodes "$NODES" || fail=1

echo
[ $fail -eq 0 ] && echo "SWEEP PASSED" || echo "FAILURES ABOVE"
exit $fail

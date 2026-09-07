#!/usr/bin/env bash
# Full sweep: every I2SPI topology, then full range of motion against the FBT simulator.
#
#   sim/sweep.sh                 # exhaustive topologies, then a ROM pass with no server
#   sim/sweep.sh --nodes 10      # smaller topology space (3^10) for a quick pass
#   sim/sweep.sh --host 127.0.0.1  # also stream ROM at a running SlimeVR server
#
# The two halves cover different things and neither substitutes for the other:
#   topology  - the chain: arming, one-hot, address isolation, per-node reachability
#   motion    - the server: assignment, skeleton solve, constraints, palm FK
set -uo pipefail
cd "$(dirname "$0")"

NODES=15
HOST=""
RATE=100
DURATION=0
while [ $# -gt 0 ]; do
  case "$1" in
    --nodes) NODES=$2; shift 2;;
    --host) HOST=$2; shift 2;;
    --rate) RATE=$2; shift 2;;
    --duration) DURATION=$2; shift 2;;
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
echo "=== Range of motion ==="
# Each ROM pose visits every joint's extremes; rom-all combines them, which is where
# inter-bone constraints break rather than any single joint.
for pose in rom rom-all; do
  echo "--- $pose ---"
  if [ -n "$HOST" ]; then
    dur=${DURATION:-0}
    [ "$dur" = "0" ] && dur=95     # one full cycle of pose_rom: 15 parts x 3 axes x 2 s
    python3 synthetic_tracker.py --host "$HOST" --pose "$pose" \
      --rate "$RATE" --duration "$dur" || fail=1
  else
    # No server: validate the pose generator itself rather than pretending to stream.
    python3 - "$pose" <<'PY' || fail=1
import math, sys
sys.path.insert(0, ".")
import synthetic_tracker as st

pose = sys.argv[1]
fn = st.POSES[pose]
samples = 0
extremes = {}
for i in range(8000):
    t = i * 0.0125
    rot = st.build_rotations(fn, t)
    for part, q in rot.items():
        n = math.sqrt(sum(c * c for c in q))
        assert abs(n - 1.0) < 1e-9, f"{part} quaternion not unit: {n}"
        samples += 1
    for part, ang in fn(t).items():
        lo, hi = extremes.get(part, (999.0, -999.0))
        m = max(abs(a) for a in ang)
        extremes[part] = (min(lo, m), max(hi, m))
print(f"  {samples} quaternions, all unit length")
print(f"  {len(extremes)} parts driven; peak excursions "
      f"{min(v[1] for v in extremes.values()):.0f}-"
      f"{max(v[1] for v in extremes.values()):.0f} deg")
PY
  fi
done

echo
[ $fail -eq 0 ] && echo "SWEEP PASSED" || echo "FAILURES ABOVE"
exit $fail

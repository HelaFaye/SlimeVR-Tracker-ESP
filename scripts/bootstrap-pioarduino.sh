#!/usr/bin/env bash
# Make the pioarduino (ESP32-C5) builds work where the PlatformIO registry is unreachable
# but GitHub is, as in Claude Code cloud sessions. Everything pioarduino needs is on GitHub
# except two things PlatformIO still asks the registry for:
#
#   1. tool-scons: PlatformIO core wants platformio/tool-scons. pioarduino publishes the
#      same SCons 4.11.1 on GitHub; install it under core's expected name.
#   2. Adafruit BusIO: a dependency of the MCP23017 library, resolved from the registry.
#      Install it from GitHub into each C5 env first (--no-save keeps platformio.ini).
#
#   scripts/bootstrap-pioarduino.sh            # then: pio run -e BOARD_ESP32C5_DEVKITC1
#
# With registry access (CI, most desks) none of this is needed.
set -euo pipefail
cd "$(dirname "$0")/.."

SCONS_URL=https://github.com/pioarduino/scons/releases/download/4.11.1/scons-local-4.11.1.tar.gz
SCONS_SHA256=e405de1fcd3307fa80d624f0290c7cd30fbb47f67e135a9f56d7e46b6b895311
SCONS_STUB=https://github.com/pioarduino/registry/releases/download/0.0.1/scons-4.11.1.zip
PKG=${PLATFORMIO_CORE_DIR:-$HOME/.platformio}/packages/tool-scons

if [ ! -f "$PKG/scons.py" ]; then
  echo "== tool-scons from GitHub"
  pio pkg install -g -t "$SCONS_STUB"
  tmp=$(mktemp -d)
  trap 'rm -rf -- "$tmp"' EXIT
  curl -sSL -o "$tmp/scons.tgz" "$SCONS_URL"
  echo "$SCONS_SHA256  $tmp/scons.tgz" | sha256sum -c -
  tar -xzf "$tmp/scons.tgz" -C "$PKG"
  # Record it as platformio/tool-scons so core does not try the registry for it.
  python3 - "$PKG/.piopm" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["spec"] = {"owner": "platformio", "id": None, "name": "tool-scons",
             "requirements": "~4.41101.0", "uri": None}
json.dump(d, open(p, "w"))
PY
fi

for env in $(sed -n 's/^\[env:\(BOARD_.*C5.*\)\]$/\1/p' platformio.ini); do
  echo "== Adafruit BusIO for $env"
  pio pkg install -e "$env" --no-save -l "https://github.com/adafruit/Adafruit_BusIO.git"
done
echo "Done. Build with: pio run -e BOARD_ESP32C5_DEVKITC1"

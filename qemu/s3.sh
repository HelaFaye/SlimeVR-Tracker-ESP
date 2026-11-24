#!/bin/sh
# This checkout on an emulated ESP32-S3 SuperMini, with sensors, Wi-Fi and a stand-in
# server, using HelaFaye/qemu_esp32 (a patch series on Espressif's QEMU) at the commit
# pinned in qemu/QEMU_ESP32:
#   1. clone qemu_esp32 and build its QEMU into WORKDIR/qemu-dist (skipped if
#      QEMU_XTENSA is set; QEMU_BIOS then names its ROMs' directory, if not beside it);
#   2. build BOARD_ESP32S3_SUPERMINI from this checkout: once as it is (two ICM-45686s
#      on I2C), and once per I2SPI configuration in qemu/i2spi/ (SLIMEVR_OVERRIDE_DEFAULTS);
#   3. check_tracker.py on the first, check_i2spi.py on the rest.
# Builds use the pioarduino platform (Arduino-ESP32 3.3, as the C5 boards do) and the
# emulated access point's open network, "Open Wifi", without touching platformio.ini.
#
#   qemu/s3.sh [WORKDIR]            (default .pio/qemu-s3)
#   S3_CHECKS="tracker" or "i2spi" runs one half; I2SPI_SCENARIOS="rj45-hub ..." a subset;
#   QEMU_ESP32=DIR uses your own qemu_esp32 checkout instead of the pinned one.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
WORK=$(mkdir -p "${1:-$ROOT/.pio/qemu-s3}" && cd "${1:-$ROOT/.pio/qemu-s3}" && pwd)
ENV=BOARD_ESP32S3_SUPERMINI
PLATFORM=https://github.com/pioarduino/platform-espressif32/releases/download/55.03.312-1/platform-espressif32.zip
CHECKS=${S3_CHECKS:-tracker i2spi}

# 1. qemu_esp32 and its QEMU
# QEMU_ESP32=/path/to/your/qemu_esp32 uses your own checkout as it is (to try a QEMU
# change against this firmware) instead of the pinned clone.
if [ -z "${QEMU_ESP32:-}" ]; then
    read -r QURL QCOMMIT < "$HERE/QEMU_ESP32"
    QEMU_ESP32="$WORK/qemu_esp32"
    if [ ! -d "$QEMU_ESP32/.git" ]; then
        git init -q "$QEMU_ESP32"
        git -C "$QEMU_ESP32" remote add origin "$QURL"
    fi
    git -C "$QEMU_ESP32" fetch -q --depth 1 origin "$QCOMMIT"
    git -C "$QEMU_ESP32" checkout -q -f "$QCOMMIT"
fi
QEMU_ESP32=$(cd "$QEMU_ESP32" && pwd)
export QEMU_ESP32
if [ -z "${QEMU_XTENSA:-}" ]; then
    # The binary and its ROMs, in qemu-dist: all a run needs, and what CI caches
    "$QEMU_ESP32/patches/espressif-qemu/build.sh" "$WORK/esp-qemu"
    mkdir -p "$WORK/qemu-dist/bios"
    cp "$WORK/esp-qemu/build/qemu-system-xtensa" "$WORK/qemu-dist/"
    cp "$WORK"/esp-qemu/pc-bios/esp32* "$WORK/qemu-dist/bios/"
    QEMU_XTENSA="$WORK/qemu-dist/qemu-system-xtensa"
    QEMU_BIOS="$WORK/qemu-dist/bios"
    export QEMU_BIOS
fi
export QEMU_XTENSA

# 2. Images
INI="$WORK/platformio.ini"
python3 - "$ROOT/platformio.ini" "$INI" "$ENV" "$PLATFORM" <<'PY'
import re, sys
src, dst, env, platform = sys.argv[1:]
s = open(src).read()
head = "[env:%s]\n" % env
start = s.index(head) + len(head)
end = s.find("\n[", start)
section = s[start:end]
section = re.sub(r"^platform = .*$", "platform = " + platform, section, count=1, flags=re.M)
section = re.sub(r"^platform_packages =\n(  .*\n)*", "", section, flags=re.M)
s = s[:start] + section + s[end:]
s = s.replace("  -std=gnu++2a\n",
              "  -std=gnu++2a\n  -DWIFI_CREDS_SSID='\"Open Wifi\"'\n  -DWIFI_CREDS_PASSWD='\"\"'\n", 1)
open(dst, "w").write(s)
PY

image() {   # image NAME [BOARD.json]
    if [ $# -ge 2 ]; then
        SLIMEVR_OVERRIDE_DEFAULTS=$(cat "$2")
        export SLIMEVR_OVERRIDE_DEFAULTS
    else
        unset SLIMEVR_OVERRIDE_DEFAULTS || true
    fi
    echo "== image $1"
    (cd "$ROOT" && pio run -c "$INI" -e "$ENV")
    B="$ROOT/.pio/build/$ENV"
    mkdir -p "$WORK/images/$1"
    python3 -m esptool --chip esp32s3 merge-bin --flash-mode dio --flash-size 4MB \
        --pad-to-size 4MB -o "$WORK/images/$1/flash.bin" \
        0x0 "$B/bootloader.bin" 0x8000 "$B/partitions.bin" 0x10000 "$B/firmware.bin"
    cp "$B/firmware.elf" "$WORK/images/$1/"
}

FAIL=0
for c in $CHECKS; do
    case $c in
    tracker)
        image tracker
        python3 "$HERE/check_tracker.py" "$WORK/images/tracker/flash.bin" "$WORK/run/tracker" || FAIL=1
        ;;
    i2spi)
        for cfg in "$HERE"/i2spi/*.json; do
            image "$(basename "$cfg" .json)" "$cfg"
        done
        # shellcheck disable=SC2086
        python3 "$HERE/check_i2spi.py" "$WORK/images" "$WORK/run/i2spi" ${I2SPI_SCENARIOS:-} || FAIL=1
        ;;
    esac
done
exit $FAIL

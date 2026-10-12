#!/usr/bin/env bash
# Boot tracker firmware in Espressif's QEMU fork and check it comes up cleanly.
#
#   qemu/run.sh BOARD_WROOM32                 # stock board config
#   qemu/run.sh BOARD_ESP32S3_SUPERMINI chain # with qemu/scenarios/chain.json swapped in
#   qemu/run.sh --all                         # every scenario in qemu/scenarios.txt
#
# What this proves: the image boots, setup() completes, and the firmware survives
# missing hardware (no Wi-Fi, no I2C/SPI devices) without panicking or boot-looping.
# What it cannot: Espressif's QEMU models ESP32, ESP32-S3 and ESP32-C3 only (no C5 or
# C6), and none of Wi-Fi, I2C or SPI peripherals. Sensor and chain behaviour is covered
# by sim/ instead. See qemu/README.md.
#
# Needs: PlatformIO (pio), Espressif's QEMU (qemu-system-xtensa / qemu-system-riscv32,
# https://github.com/espressif/qemu), and the esptool PlatformIO installs.
#
# Env: QEMU_TIMEOUT (seconds of emulated run, default 40), QEMU_XTENSA, QEMU_RISCV32.
set -uo pipefail
cd "$(dirname "$0")/.."

TIMEOUT=${QEMU_TIMEOUT:-40}
QEMU_XTENSA=${QEMU_XTENSA:-qemu-system-xtensa}
QEMU_RISCV32=${QEMU_RISCV32:-qemu-system-riscv32}
OUT=.pio/qemu

run_one() {
  local env=$1 scenario=${2:-}
  local tag=$env${scenario:+-$scenario}
  local dir=$OUT/$tag
  mkdir -p "$dir"
  echo "=== $tag ==="

  # A scenario replaces the board's values in board-defaults.json for this build only,
  # through the generator's existing SLIMEVR_OVERRIDE_DEFAULTS hook.
  if [ -n "$scenario" ]; then
    local file=qemu/scenarios/$scenario.json
    [ -f "$file" ] || { echo "  no such scenario: $file"; return 1; }
    SLIMEVR_OVERRIDE_DEFAULTS=$(cat "$file") pio run -e "$env" >"$dir/build.log" 2>&1
  else
    pio run -e "$env" >"$dir/build.log" 2>&1
  fi || { echo "  build failed, see $dir/build.log"; tail -5 "$dir/build.log"; return 1; }

  local build=.pio/build/$env
  local mcu
  mcu=$(pio project config --json-output 2>/dev/null | python3 -c '
import json, sys, subprocess
env = sys.argv[1]
board = dict(dict(json.load(sys.stdin))["env:" + env])["board"]
info = json.loads(subprocess.check_output(["pio", "boards", "--json-output", board]))
print(info[0]["mcu"].lower())' "$env") || { echo "  could not determine the MCU"; return 1; }

  local machine qemu boot_off
  case $mcu in
    esp32)   machine=esp32;   qemu=$QEMU_XTENSA;  boot_off=0x1000 ;;
    esp32s3) machine=esp32s3; qemu=$QEMU_XTENSA;  boot_off=0x0 ;;
    esp32c3) machine=esp32c3; qemu=$QEMU_RISCV32; boot_off=0x0 ;;
    *) echo "  $mcu is not emulated by Espressif's QEMU (ESP32, ESP32-S3, ESP32-C3 only)"; return 2 ;;
  esac

  local boot_app0
  boot_app0=$(ls ~/.platformio/packages/framework-arduinoespressif32*/tools/partitions/boot_app0.bin 2>/dev/null | head -1)
  local esptool=~/.platformio/packages/tool-esptoolpy/esptool.py
  [ -f "$esptool" ] || { echo "  esptool not found at $esptool"; return 1; }

  # QEMU wants a flash image of exactly 2, 4, 8 or 16 MB.
  python3 "$esptool" --chip "$mcu" merge_bin --fill-flash-size 4MB -o "$dir/flash.bin" \
    "$boot_off" "$build/bootloader.bin" 0x8000 "$build/partitions.bin" \
    ${boot_app0:+0xe000 "$boot_app0"} 0x10000 "$build/firmware.bin" >"$dir/merge.log" 2>&1 \
    || { echo "  merge_bin failed, see $dir/merge.log"; return 1; }

  local extra=()
  if [ "$mcu" = esp32c3 ]; then
    # The C3 model needs an eFuse backing file; all-zero is a blank chip.
    [ -f "$dir/efuse.bin" ] || dd if=/dev/zero of="$dir/efuse.bin" bs=1 count=1024 status=none
    extra=(-icount 3 -drive "file=$dir/efuse.bin,if=none,format=raw,id=efuse"
           -global "driver=nvram.esp32c3.efuse,property=drive,value=efuse")
  fi

  timeout "$TIMEOUT" "$qemu" -nographic -machine "$machine" \
    -drive "file=$dir/flash.bin,if=mtd,format=raw" "${extra[@]}" \
    -serial "file:$dir/serial.log" -monitor none </dev/null >"$dir/qemu.log" 2>&1
  local rc=$?
  [ $rc -eq 124 ] || [ $rc -eq 0 ] || { echo "  qemu exited with $rc, see $dir/qemu.log"; return 1; }

  python3 qemu/check_log.py "$dir/serial.log" "qemu/scenarios/${scenario:-stock}.expect"
}

if [ "${1:-}" = "--all" ]; then
  fail=0
  while read -r env scenario; do
    case $env in ''|'#'*) continue ;; esac
    run_one "$env" "$scenario" || fail=1
  done < qemu/scenarios.txt
  [ $fail -eq 0 ] && echo "ALL QEMU SCENARIOS PASSED" || echo "QEMU FAILURES ABOVE"
  exit $fail
fi

[ $# -ge 1 ] || { sed -n '2,8p' "$0"; exit 2; }
run_one "$1" "${2:-}"

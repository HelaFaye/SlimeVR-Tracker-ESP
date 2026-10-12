#!/usr/bin/env python3
"""Check a QEMU serial log: one clean boot, no crash, and every expected line present.

    python3 qemu/check_log.py serial.log [expect-file]

The expect file holds one regular expression per line ('#' comments allowed); each must
match somewhere in the log.
"""

import re
import sys
from pathlib import Path

log = Path(sys.argv[1]).read_text(errors="replace")
expect = Path(sys.argv[2]) if len(sys.argv) > 2 else None

# Anything here means the firmware crashed or the chip reset itself.
CRASH = [
    r"Guru Meditation",
    r"abort\(\) was called",
    r"Backtrace:",
    r"Stack smashing",
    r"assert failed",
    r"CORRUPT HEAP",
    r"rst:0x[0-9a-f]+ \((?!POWERON)[A-Z_]+",
]

failures = []
for pat in CRASH:
    m = re.search(pat, log)
    if m:
        failures.append(f"crash signature {pat!r}: {m.group(0)!r}")

boots = len(re.findall(r"SlimeVR v\S* starting up", log))
if boots != 1:
    failures.append(f"expected exactly one boot banner, saw {boots}"
                    + (" (boot loop?)" if boots > 1 else ""))

if expect and expect.exists():
    for line in expect.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not re.search(line, log):
            failures.append(f"expected line not found: {line!r}")

for f in failures:
    print(f"  [FAIL] {f}")
if not failures:
    print(f"  [ok] booted once, no crash signatures, {len(log.splitlines())} log lines")
sys.exit(1 if failures else 0)

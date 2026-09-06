#!/usr/bin/env python3
"""
Regression test for symbol pin-order resolution.

The failure this guards against: KiCad renames or drops a stock symbol between major
versions, the resolver falls back to another one that exists, and that one has a
different pin order. Everything passes and the board is wired to the wrong pads. The
whole point of declaring `pin_functions` is to make that impossible, so it needs a test
that the guard actually fires.

Works by mutating parts.py, running verify.py, and restoring. Safe to interrupt: the
original is restored in a finally block.

    python3 hardware/gen/test_pin_order.py
"""

import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PARTS = HERE / "parts.py"
# Derived from parts.py rather than hardcoded. An earlier version pinned the exact
# candidate string, so widening the candidate list silently broke this test - which is
# the failure mode a test least ought to have.
import importlib
import re
import sys

sys.path.insert(0, str(HERE))
_parts = importlib.import_module("parts")
GOOD_SYMBOL = _parts.MOSFET_P.symbol
PIN_MAP_DICT = _parts.MOSFET_P.pin_functions
PREFERRED = GOOD_SYMBOL.split("|")[0]

cases = []


def case(name, mutate, expect_fail, expect_text):
    cases.append((name, mutate, expect_fail, expect_text))


case(
    "correct config passes",
    lambda s: s,
    False,
    "pin order verified",
)
case(
    "every candidate removed",
    lambda s: s.replace(PREFERRED, "Device:Q_PMOS_NOSUCH").replace(
        "Device:Q_PMOS_GDS", "Device:Q_PMOS_NOSUCH2"
    ).replace("Device:Q_PMOS_DGS", "Device:Q_PMOS_NOSUCH3").replace(
        "Device:Q_PMOS_DSG", "Device:Q_PMOS_NOSUCH4"
    ).replace("Device:Q_PMOS\"", "Device:Q_PMOS_NOSUCH5\""),
    True,
    "MOSFET_P",
)
def _pin_single_wrong(text):
    """Replace the MOSFET's whole symbol= expression with one wrongly-ordered symbol."""
    return re.sub(
        r'symbol=\((?:[^()]|\([^()]*\))*\),',
        'symbol="Device:Q_PMOS_GDS",',
        text,
        count=1,
    )


case(
    "single pinned symbol with the wrong pin order",
    _pin_single_wrong,
    True,
    "pin 2 should be S but is D",
)
case(
    "pin map itself edited wrongly",
    lambda s: s.replace('pin_functions={"1": "G", "2": "S", "3": "D"}',
                        'pin_functions={"1": "S", "2": "G", "3": "D"}'),
    True,
    "none has the required pin order",
)


def run_verify():
    # parts.py is imported, and CPython caches bytecode keyed on mtime and size. These
    # mutations are the same length and land inside the same second, so without clearing
    # the cache verify.py re-runs against the previous variant and the test lies.
    shutil.rmtree(HERE / "__pycache__", ignore_errors=True)
    r = subprocess.run(
        [sys.executable, "verify.py"], cwd=HERE, capture_output=True, text=True
    )
    return r.stdout + r.stderr


def main():
    original = PARTS.read_text()
    if PREFERRED not in original or PIN_MAP_DICT is None:
        print("parts.py no longer matches what this test mutates; update the test.")
        return 2

    failed = 0
    try:
        for name, mutate, expect_fail, expect_text in cases:
            PARTS.write_text(mutate(original))
            out = run_verify()
            did_fail = "0 problems" not in out
            text_ok = expect_text in out
            ok = (did_fail == expect_fail) and text_ok
            print(f"  [{'ok' if ok else 'FAIL'}] {name}")
            if not ok:
                print(f"        expected {'failure' if expect_fail else 'pass'}"
                      f" containing {expect_text!r}")
                for line in out.splitlines():
                    if "MOSFET" in line or "PIN ORDER" in line or "problems" in line:
                        print(f"        got: {line.strip()}")
                failed += 1
    finally:
        PARTS.write_text(original)
        shutil.rmtree(HERE / "__pycache__", ignore_errors=True)

    print(f"\n{len(cases)} cases, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

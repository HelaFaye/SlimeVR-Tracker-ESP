# Project audit

Static analysis, sanitizer runs, and a manual pass over the whole change set.

**Tools actually run** (not a checklist — these were executed):

- `g++ -Wall -Wextra -Wshadow -Wnon-virtual-dtor -Wold-style-cast -Wconversion` over the
  real firmware sources via the `sim/` host build.
- AddressSanitizer + UndefinedBehaviorSanitizer on the same build, all 29 scenarios.
- `cppcheck 2.13` (`warning,style,performance,portability`) over `src/sensorinterface/`,
  `src/sensors/SensorBuilder.cpp` and the node firmware.
- `ruff` over `scripts/preprocessor.py`.
- `jsonschema` validation of `board-defaults.json` against its schema, plus a
  cross-check that board ids, PlatformIO envs, defaults and the schema enum all agree.

**Not run:** any target compile. No toolchain, no registry access. That gap is unchanged.

---

## Fixed

### A1 — `byteCompare()` is not a strict weak ordering

`SensorInterfaceManager.cpp`. The loop returned `true` on the first byte where the left
operand was smaller, but **continued** when it was larger:

```cpp
for (size_t i = 0; i < sizeof(T); i++) {
    if (lhsBytes[i] < rhsBytes[i]) { return true; }
}
return false;
```

For `a = {5, 0}` and `b = {3, 9}`, both `byteCompare(a, b)` and `byteCompare(b, a)` return
`true`. A `std::map` keyed on a comparator that says `a < b` and `b < a` simultaneously has
undefined behaviour — in practice, lookups that should hit will miss and construct a second
interface for the same bus, calling `begin()` on hardware that is already up.

This is the `SPISettings` cache key, so it is live on every SPI board including
`BOARD_SLIMEVR_V1_2`. Now a proper lexicographic compare. Pre-existing; flagged in DEC-005
as deferred, fixed here because "deferred" was the wrong call for a correctness bug in the
key of a live cache.

### A2 — Dereference of an empty `std::optional`

`I2CWireSensorInterface.cpp:46`, ESP32 path:

```cpp
if (activeSCLPin && activeSCLPin) {          // typo: SCL twice
    gpio_set_direction((gpio_num_t)*activeSCLPin, GPIO_MODE_INPUT);
    gpio_set_direction((gpio_num_t)*activeSDAPin, GPIO_MODE_INPUT);   // may be empty
}
```

With SCL set and SDA unset, the second line dereferences an empty optional. Found by
cppcheck's `duplicateExpression`. Pre-existing, upstream, and worth reporting there.

### A3 — Arming as a side effect of releasing a chip select

`ATTinyCSBus::writeCs()` called `select()` unconditionally, including on release. After a
failed arm, the release path spent a second I2C write and armed a node as a side effect of
letting it go. Found by the `sim/` failure scenario, not by any tool. Fixed and covered by
a regression check.

### A4 — Implicit narrowing in `probe()`

Four `-Wconversion` warnings from `Wire.read()` (returns `int`, can be `-1`) into `uint8_t`.
Safe in context because `requestFrom()` already confirmed the byte count, but now explicit
so the warning budget stays at zero for new code.

---

## Found, deliberately not fixed

### A5 — Interfaces have virtual functions and public non-virtual destructors

`PinInterface`, `SensorInterface`, `RegisterInterface` and everything derived from them —
33 of the 38 warnings from the aggressive build.

Checked before dismissing: `grep` finds **no** `delete` through a base pointer and no
`unique_ptr<PinInterface>` anywhere in the tree. Interfaces are allocated by
`SensorInterfaceManager` and live for the life of the program. So this is latent, not
active.

Not fixed because adding virtual destructors touches every interface in the codebase
including upstream ones, which does not belong in this change. It is a one-line fix per
base class whenever someone wants it.

### A6 — `ATTinyCSPinInterface::digitalWrite()` does not null-check `m_bus`

The manager's validator guarantees a non-null bus, so this cannot fire through the normal
path. The class is publicly constructible though, so a direct construction with `nullptr`
would fault. Left as-is to match the surrounding style; noted so it is a decision rather
than an oversight.

### A7 — `m_lastLevel` is updated before the write is attempted

If the I2C write fails, `digitalRead()` reports the level that was requested rather than
the one in effect. Nothing reads it — `SPIImpl` only writes chip selects — and reporting
the intended level is arguably more useful than reporting a stale one. Noted.

### A8 — `import` order in `preprocessor.py`

Ruff's only complaint across the whole file. Pre-existing style, not a defect.

---

## Verified clean

- **Sanitizers.** ASan and UBSan report nothing across all 29 scenarios: no leaks, no
  undefined behaviour, no out-of-bounds.
- **cppcheck on new code.** Nothing in `ATTinyCSInterface`, `ATTinyCSProtocol`,
  `DirectSPIInterface`, `SPIImpl` or the node firmware. The remaining output is upstream
  noise, overwhelmingly uninitialised members in `lib/bno080`.
- **Board table consistency.** Every PlatformIO env has a board id and a defaults entry;
  every defaults entry is in the schema enum; nothing orphaned in either direction; and
  `board-defaults.json` validates against its schema. All four sets agree exactly.
- **No remaining reference-to-temporary.** The `SPIClass&` bug fixed in DEC-005 was the
  only instance; a sweep for the same pattern in the other interfaces found none.
- **Declaration order in the node firmware.** `writeChannel()` is defined before its use in
  both the CCL and `EXTERNAL_CS_GATE` branches.

---

## What the audit could not touch

The failure modes that matter most on this design are still unexamined, because they need
hardware or a target compile:

- Whether any of it compiles for the C5 or for an ATtiny.
- CCL propagation, strobe edge timing, cable signal integrity, I2C rise times at 85 cm.
- Whether `WiFi.setBandMode` and `WIFI_BAND_MODE_2G_ONLY` exist in the pioarduino build.
- Whether megaTinyCore's `Logic`/`Event` API names match.

Everything in `docs/dev/HARDWARE-RJ45-SPI-BUS.md`'s bring-up order still applies in full.
The value of this audit is that it clears the class of bug that would otherwise be
confused *with* those hardware problems during bring-up.

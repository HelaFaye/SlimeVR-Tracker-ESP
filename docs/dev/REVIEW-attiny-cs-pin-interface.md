# Review: `ATTinyCSPinInterface.{h,cpp}` and the `SPIImpl` changes

Reviewed at commit `a94c1e9` plus the uncommitted working-tree changes.

**Status: all findings resolved.** See the "Resolution" section at the end for what was
done to each. Decisions taken are recorded as DEC-011 and DEC-012.

**Scope reviewed**

- `src/sensorinterface/ATTinyCSPinInterface.h` (new, untracked)
- `src/sensorinterface/ATTinyCSPinInterface.cpp` (new, untracked)
- `src/sensorinterface/SPIImpl.h` (modified, +46 / -2)

**Verdict.** The `SPIImpl` presence-detection work is a real improvement over
`return true; // TODO` in principle, but as written it will reject a working ICM-45686.
The new pin interface is clean, well-commented code that is currently unreachable, and it
speaks a different wire protocol from the node firmware in `extras/attiny-cs-node/`. Two
of the findings below are correctness bugs that will present as "the sensor isn't there".

Formatting is clean — `clang-format` 17 with the repo's `.clang-format` passes on all
three files, so CI's format job is fine.

---

## B1 — `hasSensorOnBus()` will reject a healthy ICM-45686

**Severity: blocking. This is the finding that matters most.**

The probe reads registers `0x00`, `0x01`, `0x02`, `0x0F` and declares the bus dead if all
four return the same `0x00` or `0xFF`. The comment justifies it with "any real IMU has a
non-trivial WHO_AM_I or config byte somewhere in this range".

That is not true for the part this board is built around. From
`src/sensors/softfusion/drivers/icm45base.h`:

- `TempData = 0x0c`, so `0x00`–`0x0b` are the accel and gyro data registers, and `0x0F`
  is still inside the data block.
- `WhoAmI` is at **`0x72`**, value `0xe9` — outside the probed range entirely.

`hasSensorOnBus()` runs *before* the driver configures anything, while accel and gyro are
still in standby. All four probed registers are therefore data registers on an idle
sensor, which read back as zeros. Four identical `0x00` reads is exactly the pattern the
function treats as "no sensor".

Consequence, following `SensorBuilder.h:323`: sensor 0 is generated non-optional, so a
correctly wired ICM-45686 becomes an `ErroneousSensor` at boot with "Mandatory sensor 1
not found". The function's own comment says it "must never reject a sensor that is
present"; this violates that.

**Suggested fix.** Presence detection that must not false-negative shouldn't guess from
data registers. Either probe `0x72` (but then `SPIImpl` needs to know the IMU, which it
deliberately doesn't), or — better, and the reason the remote-CS design has an identity
block at all — ask the chip select whether its node answered. `ATTinyCSBus::probe()`
already knows. That needs either a small virtual on `PinInterface` or a `dynamic_cast`;
it's noted as an open item in `PROGRESS.md`.

If you want to keep a heuristic, at minimum drop the "all zeros" arm: a floating MISO
realistically reads `0xFF`, not `0x00`, and `0x00` is precisely what an idle IMU returns.

---

## B2 — The wire protocol doesn't match the node firmware

**Severity: blocking for anything on real hardware.**

`ATTinyCSPinInterface` defines its own single-byte format: bit 7 the level, bits 3–0 the
channel, sent to the ATtiny's own address. `extras/attiny-cs-node/src/main.cpp` implements
`ATTinyCSProtocol.h`: opcodes on a shared chain address `0x30` plus a unicast address, with
`Arm = 0x01` and `SetCs = 0x10`.

Nothing in the repo implements the new format. Traced against the current node firmware:

| Sent | Node decodes as | Result |
|---|---|---|
| `0x80` (channel 0, HIGH) | opcode `0x80` → not `< 0x10`, not `ResetAll` → `handleNodeCommand` → `default` | ignored |
| `0x00` (channel 0, LOW) | opcode `0x00` → `< 0x10` → `handleChainCommand` → not Arm/DisarmAll/ResetAll → `default` | ignored |

Both are silently dropped. CS never moves, every register read returns float, and B1 then
reports the sensor as missing. The two failures compound into a symptom with no obvious
cause.

Pick one protocol. If the new one is the intent, `ATTinyCSProtocol.h` and the node
firmware need to follow, and the design consequences in D1 apply.

---

## B3 — The class is unreachable; two classes now share a name

Nothing constructs `::ATTinyCSPinInterface`. `SensorInterfaceManager.h:115` still declares
`SensorInterface<ATTinyCSPinInterface, ATTinyCSBus*, uint8_t>`, and `SensorBuilder.cpp`'s
`ATTINY_CS` / `ATTINY_CS_ON` still route through it — both of which resolve to
`SlimeVR::ATTinyCSPinInterface` from `ATTinyCSInterface.h`, not to the new global-namespace
class. `ATTinyCSPinInterface.h` is included only by its own `.cpp`.

So the new files compile, ship in the binary, and do nothing.

It compiles today only because unqualified lookup inside `namespace SlimeVR` finds the
inner declaration first. That is a fragile reason for two same-named classes to coexist —
moving the new one into `namespace SlimeVR`, or adding a `using namespace` anywhere in the
lookup path, turns it into an ambiguity or ODR error. Delete one or rename one.

---

## D1 — Design: this drops the strobe and one-hot arming

The header comment is honest about the cost: "two I2C transactions per SPI transaction,
which at 400kHz is roughly 60us of overhead per register access". That is the
software-CS fallback from `DECISIONS.md` DEC-004, promoted from bring-up mode to the only
mode, and the strobe conductor on RJ45 pin 6 becomes dead copper.

Concretely: an ICM-45686 poll cycle is several register accesses plus a FIFO burst. At
~120 µs of I2C per access, four nodes at a few hundred Hz spends more time toggling chip
selects than reading sensors. The recommendation to run the bus at 1 MHz halves it but
doesn't change the shape, and 1 MHz over a metre of untwisted flat cable is optimistic —
see the capacitance note in `HARDWARE-RJ45-SPI-BUS.md`.

It also drops the one-hot broadcast arm (DEC-007). With per-node addressed writes there is
no longer any structural guarantee that only one CS is asserted: a dropped deassert leaves
two nodes selected, which means two IMUs driving MISO. That was a safety property, not
just an optimisation.

**Worth keeping from this design:** the multi-channel idea. One ATtiny driving up to 16 CS
lines via the low nibble is a genuinely useful capability the original protocol lacks — a
single node could serve a cluster of sensors instead of one. That's worth folding into
`ATTinyCSProtocol.h` regardless of which framing scheme wins.

---

## D2 — `digitalWrite()` swallows I2C failures

```cpp
if (Wire.endTransmission() == 0) {
    _lastValue = level;
}
```

On failure: no log, no error propagated, and the caller proceeds to clock an SPI
transaction with CS in an unknown state. The result is register data that looks plausible
and is wrong — the worst failure shape available here, and the reason `ATTinyCSBus::select`
invalidates its cached selection and logs on a failed write.

At minimum log the failure. Better, track a sticky error flag the register interface can
consult.

---

## M1 — `digitalRead()` performs a bus transaction

It issues a `requestFrom` and decodes an asserted-channel mask. Nothing calls it today —
`SPIImpl` only ever writes CS — but callers reasonably assume `digitalRead()` on a
`PinInterface` is cheap. `MCP23X17PinInterface` has the same property, so this is
consistent with the tree; worth a comment rather than a change.

## M2 — No logging at all

`init()` returns `false` silently for a bad address, a bad channel, or an unanswering
ATtiny. Since the manager caches `nullptr` on a failed `init()`, and B1 then reports the
sensor as absent, the operator gets "mandatory sensor not found" with nothing pointing at
the I2C address. Compare `ATTinyCSBus::init()`, which logs the address, magic mismatches,
and node-id mismatches specifically because those are the failures that are otherwise
impossible to diagnose in a suit.

## M3 — Macros where the rest of the module uses scoped constants

`ATTINY_CS_ADDRESS_MIN` / `_MAX` / `_MAX_CHANNELS` are unscoped `#define`s;
`ATTinyCSProtocol.h` uses `constexpr` inside `namespace SlimeVR::ATTinyCS`. The values
themselves are right (`0x08`–`0x77` correctly excludes both reserved I2C blocks).

## M4 — `SPIImpl`'s null-guard comment overstates what it does

> every access below is gated on `isUsable()`

Only `hasSensorOnBus()` is. `readReg`, `readReg16`, `writeReg`, `writeReg16`, `readBytes`
and `writeBytes` all call `m_spi->beginTransaction(m_csPin)` unguarded, and
`DirectSPIInterface::beginTransaction` dereferences the CS pin immediately.

This is not currently reachable — every construction path runs through
`buildSensor`'s `hasSensorOnBus()` check at `SensorBuilder.h:323`, which returns false when
`isUsable()` is false, so an unusable `SPIImpl` never sees a register access. But that
invariant lives entirely in one caller and isn't stated anywhere. One new call site and it
is a null dereference. Either gate the accessors or write the invariant down.

The early return in the constructor itself is correct and necessary — without it,
`spi->getSpiSettings()` and `csPin->pinMode()` would fault on the failure path that `init()`
returning `false` now makes reachable.

## M5 — `toString()` improvement is good

`"SPI(" + m_csPin->toString() + ")"` is a real usability win; every SPI sensor logging an
identical `"SPI"` was genuinely unhelpful on a multi-drop bus. No issues. Keep it
regardless of what happens to the rest.

---

## Suggested order of work

1. Decide which protocol is canonical (B2). Everything else depends on it.
2. Fix or remove the `hasSensorOnBus()` heuristic (B1) — as written it breaks the boards
   that currently work, not just the remote ones.
3. Delete or merge the duplicate class (B3).
4. Add failure logging (D2, M2).
5. Keep `toString()` (M5) and consider adopting the multi-channel idea (D1).


---

# Resolution

| # | Finding | Resolution |
|---|---|---|
| B1 | `hasSensorOnBus()` rejects a healthy ICM-45686 | Heuristic removed. `PinInterface::isPresent()` added (defaults to true); `SPIImpl` asks the chip select instead of guessing from MISO. `ATTinyCSBus` records which nodes answered its boot enumeration. DEC-012 |
| B2 | Wire protocol doesn't match the node firmware | Arm/strobe protocol kept as canonical; the addressed-write scheme dropped. Multi-channel adopted into protocol v2. DEC-011 |
| B3 | Dead code, duplicate class name | `ATTinyCSPinInterface.{h,cpp}` deleted; the surviving `SlimeVR::ATTinyCSPinInterface` gained the channel parameter and address-range validation |
| D1 | Drops strobe and one-hot arming | Both kept. The multi-channel capability was the part worth taking, and it is now in v2 |
| D2 | `digitalWrite()` swallows I2C failures | `ATTinyCSBus::writeCs` logs the failure and clears the armed target so the next access re-establishes state. A failed select no longer touches the strobe, which would otherwise assert some other node's CS |
| M1 | `digitalRead()` does bus I/O | Returns the cached level; no bus traffic |
| M2 | No logging | Bus logs address-range errors, empty chains, magic mismatches, protocol-version mismatches and node-id mismatches |
| M3 | Macros vs scoped constants | `AddressMin` / `AddressMax` / `MaxChannels` are `constexpr` in `namespace SlimeVR::ATTinyCS` |
| M4 | `SPIImpl` null-guard comment overstates | All six register accessors now gated on `isUsable()`; `readBytes` zeroes the caller's buffer rather than leaving stack garbage. Comment corrected |
| M5 | `toString()` improvement | Kept as-is |

## Verification

- `clang-format` 17 clean on every touched file.
- `scripts/preprocessor.py` generates all 18 boards; pre-existing boards unchanged.
- Compiled and **executed** against stubbed Arduino headers: `hasSensorOnBus()` returns
  true for a present chip select, false for an absent node, and false for a null one, with
  no dereference and the caller's buffer zeroed.
- Still not built for target hardware — no toolchain here. The usual caveats in
  `PROGRESS.md` apply.

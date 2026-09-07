# Progress log

Newest first. Each entry says what changed, what was verified, and what is still unproven.

---

## 2026-09-02r — I2C sensors on the chain, and the address problem that forced protocol v3

Asked for two things: I2C sensors on the chain alongside SPI ones, and an address
whitelist least likely to collide. The second turned out to force a protocol change.

### There was no window for the old scheme

`hardware/gen/i2c_address_map.py` computes the occupied address map by parsing the driver
sources — so it cannot drift from the code — then unions that with parts commonly found on
a hobbyist bus and the ranges the I2C spec reserves. Result:

```
  16 consecutive: NO CLEAR WINDOW
   9 consecutive: 0x0E-0x10
   1 address:     dozens of choices
```

v2 needed sixteen consecutive addresses. There is no such window. Worse, the base in use,
**`0x30`, collides outright with the MMC5983MA magnetometer**, and its span also covers an
SSD1306 display and an APDS9960.

Eight nodes would fit, in exactly one window three bases wide — one added display and it
breaks. So this was forced rather than chosen: **protocol v3 puts the whole chain on one
address**, `0x13`, six clear of the nearest occupied neighbour. Frames become a uniform
three bytes: opcode, target, value. DEC-015.

Costs ~25% more I2C time per sensor switch (90 µs vs 72 at 400 kHz), still a few percent
of a poll cycle. Buys, besides the addresses: the dual-address TWI requirement disappears,
which was the reason the node MCU list was short and the reason megaTinyCore's
dual-address semantics were flagged unverified. Any plain I2C slave now qualifies.

Not wire-compatible with v1/v2 and cannot be made so — an older node reads a v3 frame's
target byte as its payload. The host refuses to drive a node reporting an older version
rather than misdriving it.

### I2C sensors: gated SCL, and the property that falls out

`ATTinyCSWireInterface` arms a node in `swapIn()`; the node gates its sensor's SCL. Held
**low** when unarmed, so the sensor cannot even detect a START — held high it would see
STARTs it could not clock in, which is probably harmless but less certain. SCL rather than
SDA because SDA is bidirectional and gating it would break ACK; SCL rather than power
because cutting the rail loses the sensor's configuration on every deselect.

The consequence is the good bit: **chained I2C sensors consume no bus addresses at all.**
Six ICM-45686s all answering at `0x68` coexist, because only one can hear the clock.
Identical parts on a shared bus is the thing I2C is worst at, and gating removes it.

That is also why one address suffices for a whole chain — only the node controllers need
to be addressable, and they now share one.

New scenario proves it: four nodes each carrying a sensor at `0x68`, each reachable in
turn, every write reaching exactly one sensor, nothing answering when disarmed. 44 checks
now, up from 39.

### Also

- The sim's node model gained read arbitration and fails loudly if two nodes would answer
  a read — the same class of fault as two chip selects on MISO, and just as invisible.
- `i2c_address_map.py --check` is now the seventh suite in `VERIFY.sh`, and
  `check_numbers.py` fails if the configured address drifts off the whitelist.
- Node firmware collapsed to one dispatcher and `Wire.begin(BASE_ADDRESS)`. All six build
  variants still compile; all four invalid ones still refused.

### Unverified

The gate's behaviour at an armed/disarmed transition mid-transaction. The host only
re-arms between transactions so it should not arise, but it wants a scope on SCL at the
sensor during a switch at bring-up.

---

## 2026-09-02q — The magnetometer write path was issuing reads

The datasheet settled the `writeAux()` FIXME left open several entries ago, and the
answer was the bad one.

`I2CM_COMMAND_0` bits [5:4] (`R_W_0`) select the transaction type: **00 write**, 01 read
with register address, 10 read without, 11 reserved (DS-000577 Rev 1.0 §20.1). The code
had `01`, copied verbatim from `readAux()` along with its comments. So every auxiliary
write was issued as a *read*: the device profile and write-data registers were loaded
correctly and then the transaction fetched a byte instead of sending one.

Combined with the earlier finding that `MagInterface.writeByte` was an empty lambda, this
means **no magnetometer has ever been configured through this driver** — first the writes
went nowhere, and once wired up they would have gone out as reads. A QMC6309 would
enumerate cleanly on `WHO_AM_I` (a read, which works) and then sit in suspend returning
nothing.

`BURSTLEN_0` for a write is valid over 0001..0110; one byte is in range.
`I2CM_CONTROL` was already correct - restart off, fast mode, GO.

### One thing deliberately not changed

`readAux()` leaves `I2CM_RESTART_EN` at 0, so a register read is a write phase, a STOP,
then a fresh START. The QMC6309 datasheet §8.2.4 describes the repeated-START form, and
most parts tolerate the alternative, so 0 is probably fine.

But it is unproven in *either* direction: since no magnetometer was ever configured
through this driver, nobody has read live data through this path. Documented at the call
site as the first thing to try if a magnetometer enumerates and then returns nothing.
Changing the default would affect every magnetometer on every shipping board, so it wants
hardware evidence, not a plausible argument.

### Scope note

This is upstream firmware, not the I2SPI work - it affects any SlimeVR tracker pairing an
ICM-45686 with a magnetometer, not just chained ones. Worth reporting upstream
independently of everything else here.

---

## 2026-09-02p — Datasheets arrived. Four things were wrong.

All four uploaded datasheets read; **no unverified pinouts remain**.

### The ICM-45686 guess was wrong on 10 of 14 pins

TDK DS-000577 Rev 1.0 gives: `AP_SDO` on pin **1** (the guess said 9), `AP_CS` on **12**
(said 10), `AP_SCLK` on **13** (said 11), `AP_SDI` on **14** (said GND), `INT1` on **4**
(said INT2), `AUX1_SDIO`/`AUX1_SCLK` on **2/3** (said 1/2). Only the four power pins were
right by luck.

A board built to that guess would have had MISO, MOSI, SCLK and chip select all on the
wrong pads — an unassemblable design that passed every check we had, because nothing we
had could see a datasheet. This is exactly the failure the `verified` flag existed to
prevent, and the flag did its job: `mklib.py` refused to emit without
`--allow-unverified` throughout.

### The settle delay was too short

The QMC6309 datasheet gives PSUP (supply ramp) < 10 ms **plus** PORT (power-on-reset)
< 3 ms, so 13 ms before it accepts an I2C command. `SensorPowerOnSettleMillis` was 10 ms.
Raised to 15 ms. The symptom would have been a magnetometer that intermittently failed to
configure — and thanks to the `writeAux` situation, one that reported present and returned
nothing, which is the hardest kind of fault to chase.

### The magnetometer draws 4x what was estimated

Datasheet Table 2: at ODR 200 Hz with OSR1=8 the QMC6309 draws **2000 µA**, not the
0.5 mA estimated. The firmware does select that combination — `magdriver.cpp` writes
`0x0a=0x21` (OSR1=8, normal mode) and `0x0b=0x48` (200 Hz, 8 gauss). Per-node current is
5.4 mA, not 4; a two-node chain costs ~10% of hub runtime, not 8%.

### GPIO3 is a strapping pin, and the scan table was too optimistic

The module datasheet lists strapping as GPIO25/26/27/28, GPIO7, MTMS and **MTDI** — and
MTDI is GPIO3, which the ESP-IDF list names by signal rather than number, which is how it
was missed. The hub used GPIO3 for the local chip select; moved to GPIO0.

Also resolved **risk R1**: GPIO15 is `SPICS1` on modules with in-package PSRAM, so the
local IMU interrupt moved from GPIO15 to GPIO24. And **risk R2**: GPIO11/12 are the
module's console UART, so the scan table now excludes them. The C5 scan array is down
from 14 candidate pins to 9 genuinely safe ones, and the numeric checker now *fails* on
UART pins rather than noting them.

### Also

- Both boards re-pinned to the real module and sensor pin numbers. The hub's ESP32
  symbol had entirely invented pin numbers; the QMC6309 had numeric pins where the part
  is a 4-pad WLCSP (`A1` VSS, `A2` SCL, `B1` VDD, `B2` SDA — confirmed against both the
  datasheet and the Mumo symbol).
- Strapping pins that are now unused get defined levels; GPIO7 in particular is
  documented as needing a driven level rather than hi-Z.

### And a stale test, again

`test_pin_order.py` hardcoded the exact `symbol=` string from `parts.py`, so widening the
candidate list broke it. Now derived from the module by import. Third time a test has
been the broken thing; the pattern each time was a fixture duplicating something that
lives elsewhere.

---

## 2026-09-02o — The pin-order caveat is now automatic

The last entry left a manual caveat: if the symbol resolver falls back, check the MOSFET
pin order against the datasheet by hand. That was the one place the portability fix traded
a loud failure for a quiet one, and quiet failures are what this project keeps getting
caught by. Removed.

### Resolve on pin function, not on existence

Parts may declare `pin_functions` — for the DMG2305UX in SOT-23, `{1: G, 2: S, 3: D}`.
`verify.py` now reads the actual pin names out of each candidate symbol and accepts one
only if it both exists *and* matches. KiCad ships all four orderings (`Q_PMOS_GSD`, `GDS`,
`DGS`, `DSG`) with identical names and different pin numbers, so resolving on existence
alone will cheerfully pick one that drives the wrong pad. Resolving on pin function
cannot.

When nothing matches, the error names each candidate and says exactly which pins are
wrong: *"Device:Q_PMOS_GDS (pin 2 should be S but is D, pin 3 should be D but is S)"*.

### And a test that the guard actually fires

`test_pin_order.py` breaks the configuration four ways and asserts each is caught: the
correct config passing, the preferred symbol absent with wrong-order alternatives present
(the real KiCad 10 case), a single symbol pinned with the wrong order, and the pin map
itself mis-edited. Added to `VERIFY.sh`.

Given that the last two sessions each found a bug in a *test* rather than in the code, a
guard without a test for the guard did not seem like enough.

### Two bugs found while building it

- **The status line lied.** A single pinned symbol with a bad pin order printed `[ok  ]`
  on the headline and the pin-order failure underneath, because status was computed before
  the pin check ran. Folded in.
- **`__pycache__` made the test report false passes.** The mutations are the same length
  and land within the same second, and CPython keys bytecode on mtime plus size — so
  `verify.py` re-ran against the *previous* variant. The test now clears the cache between
  cases, with a comment saying why, because the symptom (a test that passes when it should
  fail) is indistinguishable from the guard working.

---

## 2026-09-02n — Portability: KiCad 10 on Arch broke one symbol lookup

Reported from a real Arch run: `VERIFY.sh` failed one check, `Device:Q_PMOS_GSD`. That
symbol exists in KiCad 7 and not in 10. (The formatting section in that report printed no
violations — `FAILURES ABOVE` came from the KiCad check alone.)

### Fixed structurally rather than by renaming

Guessing the new name is the exact mistake this project keeps paying for, and it would
break again at KiCad 11. Instead:

- `parts.py` entries may list alternatives separated by `|`. `verify.py` resolves the
  first that exists and marks it `(fallback)`.
- When nothing resolves, it greps every installed library for near-misses and prints them,
  so the fix is a copy-paste rather than a hunt.
- Library search covers Arch, Debian and macOS layouts, with `KICAD_SYMBOL_DIR` /
  `KICAD_FOOTPRINT_DIR` overrides.

Tested by deleting the KiCad 7 name from `parts.py` to simulate KiCad 10: the fallback
resolves to `Device:Q_PMOS_GDS`, and with every candidate removed the suggestion lists all
eight installed PMOS symbols.

**Carried caveat:** if the fallback fires, the pin order needs checking against the
DMG2305UX datasheet. GSD, GDS and DGS all "resolve" and only one is right — verification
passing is not the same as the schematic being correct here.

### And a bug in the checker itself, again

`_search_all_symbols` used `re` without `verify.py` importing it, so the suggestion path
raised `NameError` on every invocation. It went unnoticed because my test captured only
stdout while the traceback went to stderr. Second time in two sessions that a *test* was
the broken thing; both times the cause was discarding a stream.

### Arch specifics now documented

`docs/dev/SETUP.md` covers the package names (`avr-gcc`, `avr-libc`, `kicad`,
`kicad-library` — the library is a separate package), the externally-managed-Python
restriction, clang-format being far newer than the pinned 17, avr-gcc being 16.x versus the
7.3 developed against, and KiCad 10 silently migrating the KiCad 7 schematic format on
first open. `kikit` against KiCad 10 remains unverified.

---

## 2026-09-02m — Debug pass: everything quantifiable now recomputes

Added `VERIFY.sh` (runs everything), `sim/check_numbers.py` (recomputes every documented
number from source constants) and `extras/attiny-cs-node/test/compile-check.sh` (avr-gcc
across every build variant). Four bugs found.

### The node firmware had never been compiled. Now it has.

`apt install gcc-avr` was enough — with stub headers standing in for megaTinyCore, avr-gcc
targets the real ATtiny412. First compile found a genuine bug:

```c
#ifndef digitalWriteFast
#define digitalWriteFast digitalWrite   // wrong
#endif
```

megaTinyCore provides `digitalWriteFast` as a **function**, not a macro, so `#ifndef`
cannot see it. The guard always fires and aliases every call to `digitalWrite` — silently
substituting the slow path on the core it was written for, and expanding to an undeclared
name on cores that lack it. Replaced with an explicit `NO_DIGITAL_WRITE_FAST` opt-in.

All six valid configurations now compile clean, and all four invalid ones
(`NODE_ID=0`, `NODE_ID=16`, multi-channel without the gate, no `NODE_ID`) are correctly
refused by their `#error` guards.

### Two documented numbers were wrong

- **Software-CS cost.** Documented as ~60 µs per operation. A `SetCs` write is three bytes
  (address, opcode, payload) = 1 + 27 + 1 bits = **72.5 µs** at 400 kHz, so **145 µs** to
  frame one transaction, not 120. The bring-up mode is ~20% worse than claimed.
- **Supply drop.** Documented as 1.4 mV. Two errors cancelling badly: it used the old
  12 mA figure, and it counted only the supply conductor. Current flows out on VBUS and
  back on GND, so both drop. Correct value is **1.8 mV** — still negligible, but the
  method was wrong and would not have stayed negligible on a longer chain.

### And one in the test script itself

`compile-check.sh` reported every correctly-refused configuration as accepted. Cause:
`set -o pipefail` with `compiler | grep -q error` — the pipeline inherits the compiler's
non-zero exit, so the `if` takes the else branch even though grep matched. Capture first,
then grep. Worth recording because a test that passes when it should fail is worse than no
test.

### Verified and unchanged

36 numeric checks now recompute from source: addressing arithmetic (top address `0x3F`
inside the usable range, `packTarget` fitting a byte, 240 addressable sensors), every
timing budget, per-node current, cable capacitance against the I2C limit, parallel pull-up
resistance, settle times, BOM placement count, all four panel dimensions, and the C5 scan
array against Espressif's reserved-GPIO list.

The scan array check is worth keeping: it recomputes the forbidden set from the datasheet
facts rather than trusting the array, so if someone adds a pin it fails immediately.

---

## 2026-09-02l — Verification audit: four claims wrong, two of them live

Full write-up in `docs/dev/VERIFICATION-AUDIT.md`. Roughly thirty load-bearing factual
claims checked against primary sources.

**The CCL output pin was wrong, and the firmware had been coded against it.** PA7 on an
8-pin tinyAVR carries `LUT1-OUT`, not LUT0's alternate — `LUT0-OUT` is on PA4, which the
package does not have. The node firmware configured `Logic0`, whose output cannot reach a
pin, so the strobe pass-through that the whole performance argument rests on would not
have worked. Now `Logic1` / `ccl1_event_a`. DS40001911B Table 5-1.

**The LCSC part numbers were fabricated.** Every one. The single one checkable is wrong:
JLCPCB lists ICM-45686-P as C9900251359, not the C5457057 written here. Stripped to `None`
with TODOs, so the BOM fails loudly at upload rather than quietly at assembly. This is the
most expensive error in the project so far by potential consequence.

**ICM-45686 current was overstated ~6x.** 0.42 mA in 6-axis low-noise mode per TDK, not
the 2.5 mA guessed. Power budget corrected; the chain costs less than claimed.

Verified correct and unchanged: every ESP32-C5 GPIO restriction, the boot-mode pins, ADC1
placement, the ICM-45686 package and its AUX port, TWI having no alternate position on
8-pin parts, the ATtiny10 exclusion, the QEMU limitations, and every claim already read
from source (packet ids, tracker positions, toggle defaults, WHO_AM_I values).

### Two new risks

- **GPIO15 may not exist.** Espressif: on modules with SPI PSRAM that pin is SPICS1. The
  hub uses it for the local IMU interrupt. Degraded rather than fatal (the driver polls),
  but it should be a choice, not an accident.
- **`i2cscan` probes GPIO11/12**, which are the module's console UART. Harmless at chip
  level, confusing at a bench.

### The pattern worth naming

Both live failures were a *correct conclusion resting on wrong reasoning*. "PA7 is the CCL
output" is true; "because it is LUT0's alternate" is not — and the code followed the
reasoning, not the conclusion. Same shape as the `forceArmsFromHMD` polarity error: reading
a name instead of a definition.

The defences that keep catching this are the mechanical ones — `verify.py`, the
dangling-net check, the simulation's independent node model, the `verified` flags. None of
them depend on remembering to be careful.

---

## 2026-09-02k — Vendored libraries; one of them found a live bug

`docs/I2SPI.md` written: consolidated pinout and protocol specification.

### The ESP32-C5 pinout corrected a real firmware bug

Espressif's own `kicad-libraries` has an `ESP32-C5-WROOM-1` symbol, which is as
authoritative as a datasheet. Module pins 24 and 25 are `U0RXD/GPIO12` and
`U0TXD/GPIO11` — and `BOARD_SLIMEVR_C5_CHAIN_HUB` had SPI MISO on GPIO11 and MOSI on
GPIO12. That would have fought the console UART on every boot, with a symptom
(corrupted serial, unreliable SPI) that looks nothing like its cause.

Moved to GPIO9/GPIO8, INT to GPIO15, LED to GPIO23. All still inside the free set the
`i2cscan` work established: 0,1,3,4,5,6,8,9,10,15,23,24 after excluding flash, USB-JTAG,
strapping and now UART.

This is the second time an unverified assumption in this project turned out wrong, and the
second time the flag saved it. Worth keeping the habit.

### QMC6309 was not the package I guessed

The Mumo library has a real `QMC6309`: a **4-pad WLCSP** with pads `A1`, `A2`, `B1`, `B2`.
The generated placeholder assumed a DFN-6 with numeric pins — not a variation, a different
package with a different pad count. Now sourced rather than generated.

### Still unverified: ICM-45686

Neither upload has it. `Mumo.pretty/IMU.kicad_mod` is an LGA-14 land pattern, but its own
description cites the **BMI160** datasheet — a different part sharing the LGA-14
2.5 x 3.0 mm package. The land patterns may be interchangeable; "may be" is not
verification, and the pin functions certainly are not the same. It stays flagged, and it
is now the only part that is.

### Changed

- `hardware/lib/vendor/` with `PROVENANCE.md` recording what each library settled and what
  it did not.
- `parts.py` points at `Espressif:` and `Mumo:` for those two parts; `verify.py` searches
  the vendored directory. 15 parts, 0 problems.
- `board-defaults.json` GPIO reassignment as above. All 19 boards still generate.

---

## 2026-09-02j — Audit, and the synthetic tracker

Two outstanding items, both done. Findings in `docs/dev/AUDIT.md`; the new harness is
documented in `sim/README.md`.

### Audit: two real pre-existing bugs

Tools actually run, not a checklist: `-Wall -Wextra -Wshadow -Wnon-virtual-dtor
-Wold-style-cast -Wconversion` over the real sources via the sim build, ASan + UBSan on
all 29 scenarios, `cppcheck 2.13`, `ruff`, `jsonschema`, and a cross-check of board ids
against envs, defaults and the schema enum.

**`byteCompare()` was not a strict weak ordering.** It returned `true` on the first byte
where the left operand was smaller but *continued* when it was larger, so for `a = {5, 0}`
and `b = {3, 9}` both `byteCompare(a, b)` and `byteCompare(b, a)` are true. This is the
`SPISettings` cache key, so it is live on every SPI board including the shipping
`BOARD_SLIMEVR_V1_2`. A `std::map` on such a comparator has undefined behaviour, and the
practical symptom is a lookup that should hit missing and constructing a duplicate
interface that calls `begin()` on a bus already up. DEC-005 deferred this; that was the
wrong call for a correctness bug in a live cache key, so it is fixed.

**Dereference of an empty optional.** `I2CWireSensorInterface.cpp` had
`if (activeSCLPin && activeSCLPin)` — SCL twice — guarding a block that dereferences
`*activeSDAPin`. Found by cppcheck. Pre-existing and upstream; worth reporting there.

Clean otherwise: sanitizers report nothing, cppcheck finds nothing in any of the new
files, and all four board tables agree exactly with no orphans in either direction.

Deliberately not fixed and recorded with reasons: 33 `-Wnon-virtual-dtor` warnings on the
interface hierarchy. Checked before dismissing — there is no `delete` through a base
pointer and no `unique_ptr<PinInterface>` anywhere in the tree, so it is latent rather
than active, and fixing it touches every interface including upstream ones.

### Synthetic tracker

`sim/synthetic_tracker.py` stands up all five hubs and fifteen sensors against a real
server over UDP. Wire format taken from `packets.h` and `connection.cpp`, then checked
against `UDPPacket.kt`, which is what actually parses it.

Verified by capturing its own traffic on a loopback port and decoding it back: 5
handshakes, 15 sensor-info packets, 1125 rotation packets in 1.5 s at 50 Hz, handshake and
sensor-info fields decoding to the expected values, and quaternions unit-length to 1e-6.

Six poses. `palm-twist` is the one worth running: only the palms rotate, so if the
forearms swing with them the arm chain is mis-parented. That is precisely the confusion
that produced a wrong answer in these notes a few entries ago, and it is now a thing that
can be checked in ten seconds instead of reasoned about.

### The two harnesses together

`run.sh` runs the real bus sources against a modelled chain — everything below the
network. `synthetic_tracker.py` runs a fabricated body against the real server —
everything above it. Neither runs firmware on silicon, and nothing here reduces the
bring-up sequence in `HARDWARE-RJ45-SPI-BUS.md`. What they do is clear out the class of
bug that would otherwise be mistaken for a hardware fault during that bring-up.

---

## 2026-09-02i — Scope settled: palm only, no fingers

Requirement is palm rotation and position. That is Reading A from `GLOVE-OVER-I2SPI.md`:
back-of-hand trackers on `LEFT_HAND` / `RIGHT_HAND`, attaching as node 2 on the arm chains
that already declare an optional third sensor. **No firmware change, no server change, no
glove, no flex harness.** Build stands at 15 IMU sites / 18 tracked points.

The finger note is kept rather than deleted — the bus arithmetic and the "channels reduce
nodes, not traffic" point are worth having if per-finger comes up later.

### Worth being precise about "position"

SlimeVR IMU trackers are rotation-only; `Tracker.hasPosition` defaults to `false`. The palm
*position* is solved rather than measured. `HumanPoseManager.makeComputedTracker()` builds
`human://LEFT_HAND` with `hasPosition = true, hasRotation = true`, so downstream consumers
get a full 6-DoF palm pose — rotation from the IMU, position by forward kinematics down
shoulder → upper arm → lower arm → hand.

With all three arm segments measured, that chain is fully constrained, which is the best
case the solver gets. It also means the palm's positional accuracy depends on body
proportion calibration rather than on the sensor, so that is where to look if the palm
lands in the wrong place.

Same fact from the other direction, tying back to the arm FK correction two entries ago:
because the IMU carries no position, a palm tracker can never satisfy
`leftHandTracker.hasPosition` and therefore can never flip the skeleton into
controller-driven arms, whatever `forceArmsFromHMD` is set to.

---

## 2026-09-02h — "wrist" corrected to "hand/glove"

New note: `GLOVE-OVER-I2SPI.md`.

### The number 15 is doing double duty

`TrackerPosition` defines exactly **15 finger bones per hand** (thumb metacarpal/proximal/
distal plus proximal/intermediate/distal for four fingers), ids 21-35 left and 36-50 right.
So "15 points" reads either as 15 IMU sites on the body — the previous interpretation,
where the two extras are back-of-hand trackers and nothing changes — or as one full glove.
Flagged rather than assumed; the note covers both.

### Server support: complete

`HumanSkeleton` carries a bone and tracker slot for all 30 finger positions, plus
`hasLeftFingerTracker` / `hasRightFingerTracker` and `updateFingerTransforms()`.
`SkeletonConfigManager` divides total finger length over anatomical ratios.
`FirmwareConstants` already lists `GLOVE_IMU_SLIMEVR_DEV`. No patch needed.

The gap is assignment: board type arrives in the handshake but is informational, so 15
sensors per hand get assigned by hand in the UI. Thirty manual assignments across two
gloves is where wrong fingers come from. Server feature request, not a blocker.

### Changed

`board-defaults.schema.json` sensor ceiling 8 → 16, so a 15-finger-plus-palm config is
expressible. All 19 boards still generate.

### Where this lands, honestly

I2SPI is right for the forearm-to-glove link and questionable inside the glove. The chain
design solves "several sensors metres apart where one GPIO per CS is impossible"; a glove
has 20 cm runs, and `glove_default.h` already solves fan-out with a PCA9547 mux and ten
sensors using cheaper, smaller parts than an ATtiny per node.

Two things worth writing down before the channel feature gets oversold:

- **Channels reduce nodes, not bus traffic.** Five nodes × three channels costs exactly the
  same fifteen arm writes per cycle as fifteen single-channel nodes. The saving is board
  area, parts and power.
- **Multi-channel needs `EXTERNAL_CS_GATE`**, so three OR gates per finger node — fifteen
  extra parts per glove, mounted on fingers.

Bus arithmetic for 16 sensors is in the note: ~37% of a 200 Hz cycle at 400 kHz, ~11% at
1 MHz and 100 Hz. Fingers do not need 200 Hz, and the in-glove wiring is short enough that
Fast-mode Plus is much easier there than on the 85 cm body cable.

Also noted: the existing glove uses two sensors per finger, not three. The distal joint is
strongly coupled to the intermediate one, so the third segment is usually derived. Ten
sensors buys most of the fidelity of fifteen — worth deciding deliberately rather than
defaulting to one-per-bone because the enum has one per bone.

### The real blocker is mechanical

An RJ45 jack does not go on a finger and flat patch cable does not survive a knuckle. The
protocol travels into a glove; the connector and cable standard do not. Six signals plus
power to every finger segment, flexing at every joint — that flex harness is the hardest
engineering problem in this project, and the one with the least prior art in this repo.

---

## 2026-09-02g — Correction: the arm FK warning in the previous entry was wrong

The previous entry said `forceArmsFromHMD` defaults to `true` and that this causes the arm
trackers to be ignored, and advised turning it off. **That is backwards on both counts.**

From `SkeletonConfigToggles.java`:

```java
FORCE_ARMS_FROM_HMD(4, "Force arms from HMD", "forceArmsFromHMD", true),
```

and from `HumanSkeleton`:

```kotlin
get() = leftHandTracker != null && leftHandTracker!!.hasPosition && !forceArmsFromHMD
```

With the default `true`, `isTrackingLeftArmFromController` is false, and
`assembleSkeletonArms()` takes the branch that builds the arm downward from the shoulder —
every arm bone driven by the tracker on it. That is the mode this build wants. Turning the
toggle off, as previously advised, is what would have moved toward controller-driven arms.

The name misleads: "force arms from HMD" means the arm chain is anchored to the
HMD-referenced body and assembled from the shoulder down, not that the HMD supplies arm
rotations.

It is doubly a non-issue: `Tracker.hasPosition` defaults to `false` and SlimeVR IMU
trackers are rotation-only, so a wrist IMU assigned to `LEFT_HAND` cannot satisfy the
condition regardless of the toggle. Controller-driven arms need a positional hand tracker,
i.e. a SteamVR controller through the bridge.

**Switching between the two modes** is a live toggle — GUI Settings → General → FK
settings → Arm FK, or the same toggle over RPC. `updateToggleState()` calls
`assembleSkeletonArms(true)` and `computeDependentArmOffsets()`, re-parenting the bone tree
and recomputing offsets immediately, so it can be flipped while wearing the suit.

`EXAMPLE-18POINT-BUILD.md` has been corrected with the relevant source quoted, so the
wrong version does not survive in the docs.

### Lesson for the rest of this work

The mistake came from reading the condition at its use site (`if
(isTrackingLeftArmFromController)`) and inferring the polarity from the toggle's name
instead of reading its definition and default. Worth remembering for the remaining
server-side questions in `PLAN.md`, which are the same shape.

---

## 2026-09-02f — C5 band mode; wrist tracking checked against the server

### Fixed: the C5 will not start its radio without an explicit band

Arduino-ESP32 defaults a dual-band part to `WIFI_BAND_MODE_AUTO`, which faults when the
radio starts. `WiFiNetwork::setUp()` now calls `WiFi.setBandMode(WIFI_TRACKER_BAND_MODE)`
between `WiFi.mode(WIFI_STA)` and the first `WiFi.begin()`, which is the ordering the
reported workaround requires. Default is `WIFI_BAND_MODE_2G_ONLY`; override per build.

This amends DEC-002. Deferring 5 GHz was fine as a scope decision, but "leave the band
alone" was never an option on this silicon — the call is mandatory whichever band you end
up on. Without it the C5 boards would have failed at first boot in a way that looks like
a bad platform package rather than a missing API call.

The 5 GHz caveat stands and is now written down where someone will hit it: server
discovery is a UDP broadcast on the local subnet, so a 5 GHz-only tracker on an AP with a
separate 5 GHz SSID associates fine and then never finds the server.

### Note on the two conflicting platformio.ini recipes

The research handed over contains both `platform = espressif32@6.7.0` with
`board = esp32-c5-devkitc-1`, and a statement that stable `espressif32` has no C5 board
definitions. The second is right and the first cannot work — 6.7.0 predates the C5
entirely. Our envs already use pioarduino (DEC-001), which is the same conclusion the
research reaches in its Option 1. No change needed; recording it so the 6.7.0 snippet
doesn't get copied in later.

### Wrist tracking: no patch needed, on either side

Checked against the uploaded server source rather than from memory.

`TrackerPosition.kt` has 50 entries including `LEFT_HAND` (id 17) and `RIGHT_HAND` (18),
each with a `TrackerRole`, and `HumanSkeleton` gives them `leftHandBone`,
`leftHandTrackerBone` with a `COMPLETE` constraint, and a computed tracker. There is no
`WRIST` position and there does not need to be — a wrist-mounted tracker is assigned to
the hand position, which is what the skeleton is built around. "Wrist" exists in the
server only as an internal Unity/VMC armature node and VRChat OSC input paths.

Firmware needs nothing either: body position is assigned server-side, and the arm hubs
already declare an optional node 2 that currently finds nothing.

**The one thing that will bite:** `HumanSkeleton.forceArmsFromHMD` defaults to `true`.
While arms track from controllers, `BoneType.LEFT_LOWER_ARM` and `BoneType.LEFT_HAND` are
driven by the controller and the arm-chain trackers are ignored entirely. The symptom is
four sensors that connect, report, and visibly do nothing — which reads as a hardware
fault. Documented in the build doc.

### Point count resolved

15 IMU sites (13 + 2 wrists) is 18 tracked points with HMD and two controllers. Both
numbers describe the same build. `PLAN.md` open question closed.

### Not verified

The band mode call is written against the Arduino-ESP32 3.3 API and has not been compiled
— `WiFi.setBandMode` and `WIFI_BAND_MODE_2G_ONLY` need to exist under whatever pioarduino
build you land on. It's guarded by `#if defined(ESP32C5)` so it cannot affect other
boards.

---

## 2026-09-02e — Example build, hub board, board specs

### Added

- `docs/dev/EXAMPLE-18POINT-BUILD.md` — the 5-hub / 8-extension topology end to end:
  chain assignment, node id scheme, bus timing, power budget, bring-up order.
- `docs/hardware/BOARD-SPECS.md` — net-level specifications for the two PCBs.
- `BOARD_SLIMEVR_C5_CHAIN_HUB` (board id 30) plus its PlatformIO env. Three sensors: a
  local IMU on a direct chip select and nodes 1-2 on I2SPI, sharing one SPI bus.

The hub board is the first config to mix a direct GPIO chip select with remote ones on the
same bus, which is the case the `PinInterface` indirection was built for — `SPIImpl`
cannot tell them apart. Generated and checked; all 19 boards still build their flags and
pre-existing boards are unchanged.

Because sensor 0 is mandatory and the rest optional, the same image serves the arm hubs
(which have no node 2) and the chest/leg hubs. **Three firmware images cover thirteen
boards**: one hub, two node ids.

### Point count discrepancy, flagged not guessed

The listed sites are 13, which is 16 points counting HMD and two controllers, not 18. Two
shoulder nodes on the arm chains would close it with no firmware change — those chains
already declare a node 2 that currently finds nothing. Noted in `PLAN.md` under open
questions and called out in the build doc rather than silently assumed either way.

### kicad-happy

Looked it up rather than assumed. It's aklofas/kicad-happy, a suite of Claude Code skills
that **analyze** existing KiCad projects — schematic and layout review, EMC
pre-compliance, SPICE, datasheet extraction, BOM sourcing, fab prep. Two consequences:
it isn't available in this web session (no KiCad entry in the plugin catalog), and it
reviews rather than authors, so it can't take a description and produce boards.

`BOARD-SPECS.md` is therefore written as the *input* to schematic capture — nets named,
values fixed, constraints stated — with a list of the specific questions worth putting to
kicad-happy once the boards are drawn. The EMC pass on an unshielded 8-conductor cable
carrying a 4 MHz clock is the one I'd most want checked.

### Naming

I2SPI adopted as the project term (DEC-013), with the I²S-collision caveat recorded rather
than argued again.

### Not verified

Nothing new built or bench-tested. Power figures are estimates and labelled as such.
Cable lengths are nominal. The server's handling of three sensors on one tracker is still
unverified.

---

## 2026-09-02d — Review fixes; protocol v2

Audit of the incoming `ATTinyCSPinInterface.{h,cpp}` and `SPIImpl` changes is in
`REVIEW-attiny-cs-pin-interface.md`; all ten findings are now resolved.

### The one that would have hurt

`hasSensorOnBus()` had been changed from `return true; // TODO` to a heuristic that read
registers `0x00`, `0x01`, `0x02`, `0x0F` and declared the bus dead if all four matched at
`0x00` or `0xFF`. On the ICM-45686 those are all accel/gyro data registers — `TempData` is
at `0x0c` and `WHO_AM_I` is at `0x72`, outside the probed range — and the probe runs before
the driver leaves standby, so a healthy sensor reads four zeros and gets rejected. Sensor 0
is non-optional, so the symptom is "Mandatory sensor 1 not found" on correct hardware.

Replaced with `PinInterface::isPresent()` (DEC-012). SPI has no addressing and no ACK, so
there is nothing on the bus to infer presence *from*; what is knowable is whether the chip
select is reachable, and for a remote node `ATTinyCSBus` already had that answer from its
boot enumeration and wasn't using it.

### Protocol v2

Two chip-select designs had collided. Kept arm/strobe (the alternative cost ~60 µs per
register access and dropped one-hot arming, which is a bus-fight safety property, not an
optimisation), but took the multi-channel idea from the other: `Arm` and `SetCs` payloads
now pack `(nodeId << 4) | channel`, so one node can own up to 16 chip selects. v1 nodes
ignore the nibble and still work as single-channel nodes; the host warns when it sees one.
DEC-011.

Multi-channel needs one gated output per channel and an 8-pin tinyAVR has one usable CCL
output, so it requires the `EXTERNAL_CS_GATE` build — enforced with an `#error` rather than
failing quietly.

### Also

- Deleted the duplicate `::ATTinyCSPinInterface`. Two classes with the same name in
  different namespaces compiled only because unqualified lookup inside `namespace SlimeVR`
  found the inner one first.
- All six `SPIImpl` register accessors gated on `isUsable()`; `readBytes` zeroes the
  caller's buffer. The old comment claimed this was already true; only
  `hasSensorOnBus()` was.
- `ATTinyCSBus` validates that `base` through `base + MaxNodeId` stays inside the usable
  I2C range, logs failures throughout, and clears the armed target on a failed CS write. A
  failed select no longer pulses the strobe, which would have asserted whichever node was
  still armed.
- `channel` added to the board-defaults schema and generator (`ATTINY_CS_CH`).

### Verified

- All 18 boards still generate; pre-existing boards byte-identical.
- `clang-format` 17 clean.
- Compiled *and ran* the presence logic against stubs: present → true, absent node →
  false, null chip select → false, no dereference.

### Still not verified

No target build, no hardware. Unchanged from previous entries.

---

## 2026-09-02c — Node MCU survey; naming left open

### Added

`HARDWARE-RJ45-SPI-BUS.md` now carries a "Node MCU candidates" section: the two hard
requirements (a *hardware* I2C slave; three free I/O with the gate, four without), a
comparison table covering ATtiny 0/1/2-series, PIC16F18313/18323, CH32V003, STM32C011F
and PY32F002A, and two alternatives that came out of writing it:

- **The no-MCU option.** With the gate fitted, the node's whole job is "answer I2C, drive
  one pin" — a PCF8574 with strapped address does that with no firmware. What it costs is
  specific and worth naming: one-hot arming (DEC-007) degrades to two writes per sensor
  switch with a window where two nodes can be armed, and the identity block disappears, so
  a mis-strapped node goes silent instead of announcing itself. Those two properties are
  most of what the MCU is actually buying.
- **A single-address protocol (v2).** Noticed while checking which parts support two own
  addresses: every write already carries a node id, and since arming is one-hot, a read
  from the shared address could be answered by the armed node alone. That removes the
  dual-address requirement and opens the part list to anything with a plain I2C slave.
  Not implemented — v1 works — but it's the lever to pull if part supply gets awkward.

Worth flagging: PIC16F18313 has **PPS**, so its CLC output routes to any pin. That
removes the fixed PA6/PA7 pin map the ATtiny412 forces on us. The cost is a second
toolchain in a repo that is otherwise entirely PlatformIO.

### Open question recorded, not decided

Naming. `I2SPI` is now listed under "Open questions" in `PLAN.md` with the argument
against it (collides with I²S; implies a merged bus when SPI carries all the data and I2C
only the selection). Not renamed anything — that call isn't mine to make, and it's a
mechanical change whenever it's made.

### Not verified

Nothing new was built or tested. The table is compiled from datasheets and, for the
CH32V003 Arduino core's I2C slave support, from PlatformIO community reports rather than
first-hand use — treat that row as the least certain.

---

## 2026-09-02b — Node MCU requirements loosened; ATtiny10 still out

Follow-up to "can the ATtiny10 do the chip select like the ATtiny85". Answering it exposed
that DEC-009 had over-constrained the design: it said the node MCU needs CCL, when what
the design actually needs is *a combinational path from strobe to CS*. An external OR gate
provides that for two cents.

### Added: `EXTERNAL_CS_GATE` build variant

`extras/attiny-cs-node/` now builds two ways:

- **Default (CCL).** ATtiny412-class part, strobe gated on-chip. Unchanged.
- **`-DEXTERNAL_CS_GATE`.** Any MCU with a hardware I2C slave and three free pins, plus a
  74LVC1G32 wired `CS = CS_STROBE OR ARMED_N`. The node drives `ARMED_N`; the gate does
  the combinational work. Pin numbers are plain and overridable (`-DPIN_ARMED_N`), the
  megaTinyCore `Event`/`Logic` includes are compiled out, and `digitalWriteFast` falls
  back to `digitalWrite` on cores that lack it.

Software-CS mode needed no special case in the gate variant: with the host parking the
strobe low, `CS == ARMED_N`, so the existing `SetCs` path drives the same line.

The tracker firmware is unchanged and cannot tell the variants apart — the gate node is
just a strobe-mode node as far as `ATTinyCSBus` is concerned.

### ATtiny10: still no, for a narrower reason than before

The gate removes the CCL objection, and pin count is fine in software-CS mode (SDA, SCL,
CS = three, which the ATtiny10's three usable I/O covers). What remains is decisive:
ATtiny4/5/9/10 have **no serial peripheral of any kind** — no TWI, no USI, not even SPI.
The ATtiny85 has USI and can run the standard USI TWI slave; the ATtiny10 would need a
bit-banged I2C slave decoding two addresses in 1 KB of flash and 32 bytes of SRAM, stack
included, flashed over TPI. Done perfectly it caps near 100 kHz, which is ~270 µs per CS
edge — the bring-up-only performance tier, permanently.

Written up as DEC-010.

### Not verified

Neither variant has been compiled or bench-tested. The gate variant is the more likely of
the two to build first, since it has no core-specific peripheral API in it — worth trying
if the megaTinyCore `Event`/`Logic` setup fights back.

---

## 2026-09-02 — ICM-45686 + QMC6309 pass

Triggered by the question "can our I2C protocol identify the sensors, and can we use an
ATtiny10". Short answers: identification already works and needs no protocol change; the
ATtiny10 cannot do the job. Both written up as DEC-008 and DEC-009.

### Found: QMC6309 configuration writes are silently discarded

`softfusionsensor.h` built its `MagInterface` with

```cpp
.writeByte = [&](uint8_t address, uint8_t value) {},   // empty body
```

while `ICM45Base::writeAux()` sat there unused. So every register write in the QMC6309
`setup()` lambda — soft reset, 8 g range, 200 Hz, oversampling — went nowhere. The mag
would still be *detected*, because `WHO_AM_I` is a read and reads worked, and would then
sit in standby returning nothing. That is a nasty failure shape: the log says the mag was
found, and the data is silently absent.

Wired `writeByte` to `writeAux`. **Only half a fix.** `writeAux()` is a verbatim copy of
`readAux()` with `I2CMDevProfile0`/`I2CMWrData0` added — the transaction-type bits in
`I2CM_COMMAND_0` still say `0b01 << 4 // Read with register`, comments and all. That has
to be checked against AN-000478 / the ICM-45686 register map before mag configuration can
be trusted. Marked with a FIXME at the call site rather than guessed at.

### Changed

- `BOARD_ESP32C5_RJ45_HUB` now names `IMU_ICM45686` instead of `IMU_AUTO`. On a chain,
  `IMU_AUTO` probes every supported driver *per node* through remote chip select, which
  is a lot of arming and SPI traffic at boot for a build where the part is known.
- `docs/dev/DECISIONS.md`: DEC-008 (mag on AUX1), DEC-009 (node MCU requirements).
- `docs/dev/HARDWARE-RJ45-SPI-BUS.md`: node parts list now covers the mag.

### Unchanged, deliberately

The ATtiny protocol still identifies *nodes*, not sensors, and should stay that way. The
sensors identify themselves over the paths that already exist: the IMU by `WHO_AM_I`
(reg `0x72` == `0xE9`) over SPI through the selected node, the mag by `WHO_AM_I`
(reg `0x00` == `0x90`) over the IMU's AUX1 I2C master. Duplicating that into the node
firmware would create a second source of truth that can disagree with the hardware.

---

## 2026-09-01 — Initial implementation pass

### Done

**Documentation** (`docs/dev/`)
- `PLAN.md`, `DECISIONS.md`, `HARDWARE-RJ45-SPI-BUS.md`, `ATTINY-CS-PROTOCOL.md`, this file.

**Phase 1 — ESP32-C5**
- `src/consts.h`: `BOARD_ESP32C5_DEVKITC1` (28), `BOARD_ESP32C5_RJ45_HUB` (29).
- `platformio.ini`: two envs on the pioarduino platform, board `esp32-c5-devkitc-1`.
  `ci/build-matrix.py` derives the CI matrix from the ini's `[env:...]` sections, so both
  are covered automatically.
- `lib/i2cscan/i2cscan.cpp`: `ESP32C5` arm. Candidate pins are GPIO 0,1,3,4,5,6,8,9,10,
  11,12,15,23,24 — everything except flash/PSRAM (16–22), USB-JTAG (13–14), strapping
  (2, 7, 25, 27, 28) and boot mode (26). Cross-checked against the ESP-IDF C5 GPIO table.
- `board-defaults.json` + schema: `BOARD_ESP32C5_DEVKITC1` (two I2C ICM45686 on
  SCL 4 / SDA 5, battery on GPIO1 which is ADC1_CH0).

**Phase 2 — SPI**
- `DirectSPIInterface` now takes `SPIClass*` plus explicit `sck`/`miso`/`mosi`, with
  `PinDefault` (-1) meaning "core default for this SoC". `init()` is `#ifdef ESP32`-split
  because ESP8266's `begin()` takes no pins.
- `SensorInterfaceManager` caches SPI buses on `(SPIClass*, SPISettings, sck, miso, mosi)`.
  Removed `operator<(const SPIClass&)` — see DEC-005 for the dangling-reference bug this
  fixes.
- `SensorBuilder`: added `SPI_BUS(clock, bitOrder, mode, sck, miso, mosi)`.
  `DIRECT_SPI(clock, bitOrder, mode)` is now a thin wrapper over it and generates the same
  descriptor as before.
- `scripts/preprocessor.py`: optional `"SPI"` block in board values drives clock, bit
  order, mode and pins.

**Phase 3 — ATtiny remote chip select**
- `src/sensorinterface/ATTinyCSProtocol.h` — wire constants, shared verbatim with the node
  firmware so the two cannot drift.
- `src/sensorinterface/ATTinyCSInterface.{h,cpp}` — `ATTinyCSBus` (arming, enumeration,
  identity checks) and `ATTinyCSPinInterface` (a `PinInterface` that `SPIImpl` can't tell
  from a local pin).
- `SensorBuilder`: `ATTINY_CS(nodeId)` and `ATTINY_CS_ON(scl, sda, base, strobe, nodeId)`.
- `src/globals.h`: `REMOTE_CS_SCL` / `_SDA` / `_BASE_ADDR` / `_STROBE` defaults.
- `scripts/preprocessor.py` + schema: `"REMOTE_CS"` block and object-form `"cs"`.
- `extras/attiny-cs-node/` — node firmware, PlatformIO config, README.
- `BOARD_ESP32C5_RJ45_HUB` board default: four auto-detected SPI IMUs on nodes 1–4,
  bus on GPIO 10/11/12, chain I2C on 4/5, strobe on 6, 4 MHz.

### Verified

- `scripts/preprocessor.py` runs clean against the real schema for **all 18 boards**.
- `BOARD_SLIMEVR_V1_2`'s generated flags are **byte-identical** to before this change,
  which was the point of keeping `DIRECT_SPI` at its original arity (DEC-006). Same for
  every other pre-existing board.
- `clang-format` 17 (repo `.clang-format`) is clean on every touched and added file, so
  the CI format job should pass.

### Not verified — this is the important part

**Nothing has been compiled.** No PlatformIO toolchain in this environment and no network
route to the platform registries. Every call site was hand-checked against the interfaces
as they exist in this tree, but the first `pio run` is the real review.

Specific things to watch on first build:

1. `SPIClass::begin(sck, miso, mosi, ss)` — exists on ESP32 cores, guarded for ESP8266,
   guard untested.
2. pioarduino's C5 variant may not define `LED_BUILTIN`; `board-defaults.json` assumes it.
3. megaTinyCore's `Event`/`Logic` API names (`gen0::pin_pa6`, `user::ccl0_event_a`) drift
   between versions.
4. megaTinyCore `Wire.begin(addr, broadcast, second_address)` dual-address encoding.

Nothing has been on hardware. The bring-up order in `HARDWARE-RJ45-SPI-BUS.md` exists
because the failure modes here (a chain that half-works at 8 MHz, a node flashed with the
wrong id) are much easier to find one variable at a time.

### Open issues found along the way

- **`byteCompare` is not a strict weak ordering.** In `SensorInterfaceManager.cpp` it
  returns `false` on the first byte that isn't less-than instead of continuing while bytes
  are equal. Any `std::map` keyed with it can misbehave. Still used for `SPISettings`.
  Left alone deliberately: fixing it changes cache behaviour for shipping boards and
  belongs in its own change. (DEC-005)
- **`SPIImpl::hasSensorOnBus()` returns `true` unconditionally** (pre-existing `// TODO`).
  With remote nodes we could do better — `ATTinyCSBus::probe()` already knows whether the
  node answered. Would need `SPIImpl` to be able to ask its CS pin, which means either a
  new virtual on `PinInterface` or a `dynamic_cast`. Not done.
- **Sensor 0 is always generated as mandatory** (`'false' if index == 0`), so on a chain
  board node 1 must be present or the tracker reports an erroneous sensor. Probably right,
  but it should be expressible in the JSON.
- **The arming I2C write happens inside an open SPI transaction.**
  `DirectSPIInterface::beginTransaction()` calls `spi->beginTransaction()` and *then*
  `csPin->digitalWrite(LOW)`, which for a remote pin may do an I2C write. It only happens
  on the first transaction after a sensor switch, so it is not hot, but it holds the SPI
  bus mutex across an I2C transfer. Cleaner would be a `prepare()` hook on `PinInterface`
  called before `beginTransaction`.
- **`PIN_IMU_INT` was only emitted when a sensor declared an `int` pin**, but
  `serialcommands.cpp` prints it unconditionally. Now defaults to 255. This was latent —
  any board config without an `int` on sensor 0 would have failed to build.

### Next

1. Build both C5 envs. Fix whatever the toolchain says.
2. Flash `BOARD_ESP32C5_DEVKITC1` on a devkit with two I2C IMUs — proves the board support
   independently of the chain work.
3. Build one node board. Bring it up in software-CS mode first (`"strobe"` omitted from
   `REMOTE_CS`), which removes CCL from the equation entirely.
4. Switch that node to strobe mode, scope the CS edge at the IMU.
5. Walk the clock up, then add nodes.
6. Then, and only then, revisit 5 GHz (DEC-002).

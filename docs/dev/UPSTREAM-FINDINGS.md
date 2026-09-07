# Findings that affect upstream, not just I2SPI

Four bugs found here are in existing SlimeVR-Tracker-ESP code and affect boards that have
nothing to do with the chain work. Listed separately so they can be reported without
untangling them from everything else.

Each was found by a tool rather than by reading, which is noted because it says something
about which tools were worth building.

---

## 1. Magnetometer writes were issued as reads (severity: feature never worked)

`src/sensors/softfusion/drivers/icm45base.h`, `writeAux()`.

`I2CM_COMMAND_0` bits [5:4] select the transaction type — `00` write, `01` read with
register address (ICM-45686 datasheet DS-000577 Rev 1.0 §20.1). The code had `01`,
copied verbatim from `readAux()` including its comments.

Compounding it, `src/sensors/softfusion/softfusionsensor.h` built its `MagInterface` with

```cpp
.writeByte = [&](uint8_t address, uint8_t value) {},   // empty
```

while `writeAux()` sat unused.

**Consequence:** no magnetometer has ever been configured through this driver. A QMC6309
enumerates cleanly on `WHO_AM_I` — a read, which works — and then sits in suspend mode
returning nothing. The symptom is a magnetometer that reports present and contributes no
data, which is a hard fault to attribute.

Affects any tracker pairing an ICM-456xx with a magnetometer.

*Found by:* reading `writeAux` while wiring up `writeByte`, then confirmed against the
datasheet.

---

## 2. `byteCompare()` is not a strict weak ordering (severity: undefined behaviour)

`src/sensorinterface/SensorInterfaceManager.cpp`.

```cpp
for (size_t i = 0; i < sizeof(T); i++) {
    if (lhsBytes[i] < rhsBytes[i]) { return true; }
}
return false;
```

Returns `true` on the first byte where the left operand is smaller but **continues** when
it is larger, so for `a = {5, 0}` and `b = {3, 9}` both `byteCompare(a, b)` and
`byteCompare(b, a)` are true.

This is the comparator for the `SPISettings` cache key. A `std::map` keyed on a comparator
that says `a < b` and `b < a` simultaneously has undefined behaviour; in practice a lookup
that should hit can miss and construct a duplicate interface, calling `begin()` on a bus
that is already up.

Live on every SPI board, including `BOARD_SLIMEVR_V1_2`.

*Found by:* `cppcheck`.

---

## 3. Dereference of an empty `std::optional` (severity: crash, ESP32 only)

`src/sensorinterface/I2CWireSensorInterface.cpp`.

```cpp
if (activeSCLPin && activeSCLPin) {          // SCL tested twice
    gpio_set_direction((gpio_num_t)*activeSCLPin, GPIO_MODE_INPUT);
    gpio_set_direction((gpio_num_t)*activeSDAPin, GPIO_MODE_INPUT);   // may be empty
}
```

With SCL set and SDA unset, the second line dereferences an empty optional.

*Found by:* `cppcheck` (`duplicateExpression`).

---

## 4. `PIN_IMU_INT` was only emitted when a sensor declared one (severity: build break)

`scripts/preprocessor.py` emitted `PIN_IMU_INT` from `sensor.get('int')`, which is `None`
when absent, and `add()` skips `None`. But `src/serial/serialcommands.cpp` prints
`PIN_IMU_INT` unconditionally.

Latent rather than active — every board in `board-defaults.json` happens to declare an
`int` on sensor 0 — but any board config without one fails to build. Now defaults to 255.

*Found by:* adding the first such board.

---

## Reporting notes

1, 2 and 3 are independent of the I2SPI work and can be cherry-picked. 4 comes with the
schema change that made it reachable, but the one-line generator fix stands alone.

None of these have been verified on hardware. 1 is confirmed against the datasheet, 2 and
3 are provable by inspection, 4 is a compile-time fact.

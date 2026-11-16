# Drafts for upstream

Ready-to-post text for SlimeVR's own repositories. Nothing here has been posted: these go
out under your name, so review, edit and post them yourself. Re-check each target's state
first; it was last checked 2026-10-13.

---

## 1. Comment on SlimeVR/SlimeVR-Tracker-ESP#465 ("Mag Support (Continuation)")

Head checked: `2232649` (2025-11-29).

> Thanks for picking this up. Two things from running a fork on top of a similar pipeline:
>
> **1. The MagEnabled toggle can reapply the old value on BNO08x.** This PR emits the change
> from inside `SensorToggleState::setToggle()`, but `Sensor::setFlag()` only saves the new
> toggles to the configuration *after* `setToggle()` returns. The BNO08x listener reacts to
> `MagEnabled` by calling `motionSetup()`, which starts with
> `toggles = configuration.getSensorToggles(sensorId)`, so it reads the old value, sets the
> sensor up with it, and `setFlag()` then saves that old value back. The same assignment also
> replaces `toggles.callback` while that callback is running.
>
> What worked for us: keep `setToggle()` silent, and in `setFlag()` save first, then notify:
>
> ```cpp
> toggles.setToggle(toggle, state);
> configuration.setSensorToggles(sensorId, toggles);
> configuration.save();
> toggles.emitToggleChange(toggle, state);  // made public
> ```
>
> and in `emitToggleChange()`, call a copy of the callback (`auto listener = *callback;
> listener(toggle, state);`).
>
> **2. Magnetometers on their own SPI chip select.** We needed mags on IMUs whose aux master
> the firmware doesn't drive, so our `MagDriver` polls the mag itself at the driver's
> `MagTs` over either transport: the ICM-45 aux master (as here) or a plain SPI chip select.
> It supports MMC5983MA and LIS3MDL over SPI, maps the mag's axes into the IMU's frame from
> board config (`"axes": "+Y-X+Z"`), and adds a timeout to the I2CM busy-wait so a wedged aux
> bus can't hang the main loop now that mags are polled at run time.
>
> If that's useful, I'd like to offer it as a follow-up PR on top of this one once it lands,
> keeping your names (`scaleMagSample`, `isMagAttached`, the burst `readAux`), rather than
> as a competing PR. Code: https://github.com/HelaFaye/SlimeVR-Tracker-ESP (`src/sensors/softfusion/magdriver.*`,
> design notes in `docs/dev/DECISIONS.md` DEC-017).

---

## 2. To unlogisch04, about the ESP32-C5

Where: a GitHub Discussion on SlimeVR/SlimeVR-Tracker-ESP, or the SlimeVR Discord's
firmware channel, mentioning them. Their fork has an `esp32_tasmota` branch with a C5 test
build.

> Hi! I saw your `esp32_tasmota` branch has an ESP32-C5 test env. I've been working on C5
> support in a fork and wanted to compare notes before proposing anything upstream, so we
> don't duplicate effort.
>
> What I have, building in CI on pioarduino `55.03.312-1` (Arduino-ESP32 3.3.12):
> - C5 board definitions (devkit and two hub boards). The Wi-Fi handler sets the C5's band
>   mode explicitly, but to 2.4 GHz: 5 GHz is deliberately not exposed yet, since
>   provisioning and server discovery assume one band;
> - C5-specific bits: `BOARD_N<id>` names for the new ids, the I2C scanner's port table
>   avoiding the C5's strapping, flash and console pins, and `min_spiffs.csv` because the
>   3.3 image (~1.39 MB) overflows the default 1.25 MB app slot;
> - none of it has run on hardware yet.
>
> Questions:
> 1. Have you had a C5 running a tracker, on either band?
> 2. Would upstream want C5 support before or after #534 (the Wi-Fi strategy refactor)?
>    The band-mode call would move into `WiFiCommunication` either way.
> 3. Any objection to pinning a pioarduino release rather than `stable`?
>
> Fork: https://github.com/HelaFaye/SlimeVR-Tracker-ESP (see `docs/dev/DECISIONS.md`
> DEC-001/002 for the platform and band choices).

---

## 3. Not yet: a PR for the SPI magnetometer transport

Wait for #465 to land (or for an answer to draft 1), then rebase onto it as described in
`UPSTREAM-OVERLAP.md` §2.

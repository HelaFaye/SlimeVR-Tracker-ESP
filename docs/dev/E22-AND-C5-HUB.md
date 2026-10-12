# ESP32-E22 support, and the ESP32-C5 as a wireless hub

Written 2026-10-12, in response to two questions: can the firmware support the ESP32-E22 on
every host it runs on, and would an ESP32-C5 (optionally with an E22) make a good hub that
also routes, monitors interference and moves channel proactively?

Short answers:

1. **E22 on the tracker MCUs is not buildable today, on any of them.** There is no bus to
   attach it, and no MCU-sized host stack to drive it. Details and what *is* possible in §1.
2. **A C5 makes a good single-channel hub,** for ESP-NOW or a SoftAP, with chained
   extensions and its own sensors, and it has CPU to spare. It **cannot** serve 2.4 GHz and
   5 GHz at the same time, because it has one radio. Concurrent dual band needs a second
   radio, and that radio should be another ESP over SPI, not an E22. §2–§4.

Sources are listed at the end. Anything not measured is marked as an estimate.

---

## 1. ESP32-E22

### 1.1 What the part is

From Espressif's `esp32e22-fw` and `esp32e22-linux-driver` repositories (v0.6, supplied as
archives):

- A **Wi-Fi 6E** (2.4 / 5 / 6 GHz) and **Bluetooth 5.4 connectivity co-processor**. It runs
  one closed firmware image (Apache-2.0, binary only, `esp32e22-fw.bin`) loaded by the host.
- Host interfaces: **PCIe 2.1** (Wi-Fi), **SDIO 3.0** (Wi-Fi/BT), **USB** (BT), **UART**
  (BT).
- Linux driver status at v0.6: Wi-Fi STA over **PCIe only**. Wi-Fi over SDIO, AP mode,
  Bluetooth over UART, coexistence and suspend are all **"Not yet"**.

The decisive detail is in the Wi-Fi host driver, `espressif/esp-wifi-drv` (GPL-2.0 OR
BSD-3-Clause):

- It is a **SoftMAC driver**. It registers with Linux **mac80211** through `ieee80211_ops`
  (`mac.c`). The host runs the 802.11 MAC layer: association, management frames, power-save
  bookkeeping. **wpa_supplicant** on the host does WPA2/WPA3 authentication.
- The chip offloads rate control (`HAS_RATE_CONTROL`), hardware scan (`hw_scan`),
  aggregation and, via `set_key`, crypto. That is less than a full-MAC part like the
  ESP32's own Wi-Fi, where the chip does all of the above itself.

### 1.2 Against the hosts this firmware supports

| Host | PCIe | SDIO host | USB host | Usable E22 Wi-Fi link |
|---|---|---|---|---|
| ESP8266 | – | – | – | none |
| ESP32-C3 | – | – | – | none |
| ESP32-C5 | – | – | – | none |
| ESP32-C6 | – | – | – | none |
| ESP32 | – | yes | – | SDIO, once Espressif supports E22 Wi-Fi over SDIO |
| ESP32-S3 | – | yes | OTG (BT only on E22) | SDIO, same condition |

So the hardware can attach on ESP32 and ESP32-S3 only. Even there, using it would need:

1. E22 firmware support for Wi-Fi over SDIO: **not released**.
2. A **SoftMAC host stack on the MCU**: an 802.11 MLME (what mac80211 does), a WPA
   supplicant driving this chip's key interface, and glue into lwIP. ESP-IDF's
   wpa_supplicant is wired to Espressif's own full-MAC Wi-Fi blob, not to an external
   SoftMAC radio. No such MCU stack exists, and porting mac80211 into ~400–512 KB of SRAM
   is a project far larger than this firmware.
3. A reason to do it. Every tracker MCU above except the ESP8266 already has Wi-Fi on die,
   and the C5 already does 5 GHz.

**Recommendation: do not start E22 driver work in the tracker firmware.** What is worth
doing instead:

- **Make the transport pluggable**, following upstream PR #534 ("Move Wi-Fi code to strategy
  pattern", `CommunicationStrategy`), not a parallel abstraction. Any future radio (ESP-NOW,
  ESP-Hosted, an E22 if Espressif ever ships an MCU path) then lands as one strategy.
- **Put the E22 where its driver lives: on a Linux host.** A small Linux board with PCIe
  (Raspberry Pi CM4/CM5 class) running an E22 as a 6 GHz access point, once AP mode lands,
  gives trackers a clean band. That needs no tracker firmware changes beyond what the C5
  already does, plus a 6 GHz-capable tracker radio, which the C5 is not (§2).
- **Watch for:** E22 SDIO Wi-Fi support, AP mode, and any full-MAC or offload firmware
  variant. Any one of those changes the answer above.

---

## 2. What the ESP32-C5 brings

| | ESP32-C5 |
|---|---|
| CPU | One 32-bit RISC-V HP core, up to 240 MHz, plus a low-power RISC-V core |
| SRAM | 384 KB HP SRAM; optional in-package PSRAM on some modules |
| Wi-Fi | Wi-Fi 6, **dual-band 2.4 and 5 GHz, one radio**, one band at a time |
| Other radios | Bluetooth LE 5, IEEE 802.15.4 |
| Host links | SPI, I2C, UART, USB Serial/JTAG (device only); **no SDIO host, no USB host, no PCIe** |

"Dual-band" means it can operate on either band, not both at once. SoftAP plus STA share
one radio and so one channel.

---

## 3. The C5 as a hub

### 3.1 Topologies that work

**A. ESP-NOW gateway (recommended starting point).** The hub owns a channel. Trackers send
ESP-NOW frames to it, and it forwards everything to the PC over USB, or over Wi-Fi as STA
on the same channel. This is exactly what mitzey234's fork and ESP32-S3 receiver already do
on 2.4 GHz:

- pairing announcements;
- trackers hopping channels {2, 4, …, 14} to find the gateway;
- gateway-assigned tracker ids and polling rate;
- OTA triggered over ESP-NOW.

**Build on that, don't redesign it** (§6 of `UPSTREAM-OVERLAP.md`). On a C5 the same design
can sit on a 5 GHz channel, where the band is usually far quieter than 2.4 GHz. Whether
ESP-NOW is supported on 5 GHz channels in the ESP-IDF release this firmware pins is
**unverified**; check before committing to it.

**B. SoftAP hub.** Trackers join the hub's own AP using the existing SlimeVR UDP protocol
unchanged, and the hub forwards to the PC over USB. Simpler for trackers, heavier per packet
than ESP-NOW.

**C. Hub with chained extensions.** Orthogonal to A and B: the hub's own body site carries
I2SPI extensions (`BOARD_SLIMEVR_C5_CHAIN_HUB`). Nothing about being a gateway conflicts
with that. The chain is SPI and I2C, the radio is separate.

### 3.2 What does not work

- **Serving 2.4 GHz and 5 GHz trackers at once** from one C5. It would have to time-share
  one radio between bands, and every band switch is dead air for both sides.
- **Bridging a 2.4 GHz tracker network to a 5 GHz uplink** on one C5, for the same reason.
- **6 GHz.** The C5 has no 6 GHz radio; only the E22 would, and §1 rules that out on MCUs.

### 3.3 Concurrent dual band: add a radio, not an E22

Two ESP radios do what one cannot:

- A C5 (or P4) host running the gateway, plus a **second ESP as a Wi-Fi co-processor over
  SPI**. Espressif's ESP-Hosted-MCU is built for exactly this host-plus-co-processor split
  over SPI or SDIO. Confirm the C5 and the chosen host on its current supported-chip list.
- Or simply **two C5 gateways** on different bands, each on its own USB port. Crude, but it
  needs no new firmware beyond the gateway.

---

## 4. Interference monitoring and proactive channel moves

### 4.1 What the hub can observe

- **Per-packet RSSI and noise floor** in the received-packet metadata
  (`wifi_pkt_rx_ctrl_t`), on every frame it receives anyway.
- **Delivery statistics** it already has as gateway: per-tracker loss, sequence gaps, ESP-NOW
  send failures, latency jitter. These are the best early warning, because they measure
  what actually matters.
- **Off-channel scans** to survey alternatives. On one radio a scan leaves the working
  channel, typically tens of ms per channel scanned, during which trackers are not heard.
  Schedule dwell scans one channel at a time in gaps, or dedicate a cheap second ESP as a
  full-time monitor.
- **CSI** (channel state information) for finer-grained analysis, if needed.

### 4.2 Moving channel without dropping trackers

The hub must **own** the channel, so topology A or B, not STA on someone else's AP. A
tracker joined to a home router can't be moved, because the router decides.

Protocol sketch, modelled on 802.11h channel switch announcements:

1. Hub decides to move: loss or noise above threshold for N seconds, and the survey shows a
   clearly better channel.
2. Hub broadcasts `SWITCH {channel, at_sequence}` several times, piggybacked on its normal
   traffic.
3. At the agreed point everyone retunes. The hub listens on the new channel.
4. A tracker that missed the announcement falls back to the existing gateway search: hop
   channels until it hears a pairing or heartbeat frame, then resume. The ESP-NOW fork
   already has this loop.

On 5 GHz, prefer non-DFS channels (UNII-1 36–48, UNII-3 149–165). DFS channels need radar
detection and can force an unplanned move. Whether ESP-IDF supports DFS for an ESP-NOW or
SoftAP owner on the C5 is unverified.

### 4.3 Does a C5 have the horsepower?

Estimates, not measurements:

| Load | Estimate |
|---|---|
| Own sensors: hub IMU + 2 chained extensions at 200 Hz, fused | Small. Today's firmware fuses 1–2 IMUs on an 80 MHz ESP8266 |
| Gateway for 15 trackers at 100–200 Hz | 1,500–3,000 frames/s, ~50–100 KB/s. Well inside Wi-Fi and USB Full Speed CDC |
| Interference statistics | Negligible: counters and running averages |
| Dwell scans | Airtime, not CPU, is the cost |
| **Adding an E22** | Not a CPU question: no bus and no host stack (§1) |

The binding constraint for a C5 hub is **airtime on one radio**, not CPU or memory. A
second radio (§3.3) relieves it; a faster CPU would not.

---

## 5. Suggested next steps, in order

1. Decide the hub topology (A recommended). If A, start from mitzey234's ESP-NOW tracker
   and receiver, and port the receiver to the C5.
2. Verify on the pinned ESP-IDF: ESP-NOW on 5 GHz channels, SoftAP on 5 GHz, and channel
   change while trackers are attached.
3. Add the `SWITCH` announcement and loss/noise-triggered moves to the gateway, with the
   fallback search on trackers.
4. Do transport work on top of upstream PR #534's `CommunicationStrategy`.
5. Revisit the E22 if Espressif releases SDIO Wi-Fi, AP mode, or an offload firmware.

---

## Sources

- `esp32e22-fw` and `esp32e22-linux-driver` v0.6 (archives supplied by the user):
  README, `VERSIONING.md`, `docs/en/ARCHITECTURE.md`, `docs/en/FIRMWARE.md`
- [espressif/esp-wifi-drv](https://github.com/espressif/esp-wifi-drv): `README.md`,
  `mac.c` (`ieee80211_ops`), `core.c` (`ieee80211_hw_set` flags)
- [mitzey234/SlimeVR-Tracker-ESP](https://github.com/mitzey234/SlimeVR-Tracker-ESP),
  branch `esp-now` (`src/network/espnowhandler.h`, README) and its receiver,
  [mitzey234/SlimeVR-Receiver-ESP-Now](https://github.com/mitzey234/SlimeVR-Receiver-ESP-Now)
- Upstream SlimeVR-Tracker-ESP PR #534 ("Move Wi-Fi code to strategy pattern")
- ESP32-C5 capabilities as summarised in §2 are from Espressif's product material; confirm
  against the current datasheet before relying on a specific figure

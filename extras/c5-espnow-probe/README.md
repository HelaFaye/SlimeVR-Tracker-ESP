# ESP-NOW channel probe (ESP32-C5)

A test firmware for the open questions in `docs/dev/E22-AND-C5-HUB.md` §5, before any
hub firmware is written:

1. Does ESP-NOW work on **5 GHz** channels on the ESP-IDF release the tracker pins?
2. What loss and RSSI does a body-worn link see on each band?
3. Do peers follow an **announced channel switch** without dropping out?

## Use

Flash the same image on two or more ESP32-C5 boards:

```sh
pio run -d extras/c5-espnow-probe -t upload        # on each board
pio device monitor -b 115200
```

Each board broadcasts a numbered ping every 50 ms, starting on channel 36 (5 GHz,
non-DFS). Once a second it prints every peer it heard:

```
ch 36  sent 20 ok / 0 failed
  48:CA:43:xx:xx:xx     20 pkts  loss   0.0 %  rssi  -41 dBm
```

Serial commands:

| Command | Effect |
|---|---|
| `c <ch>` | Move this board to channel `ch` now (1–13; 36–48, 149–165) |
| `s <ch>` | Announce a switch: this board and every board that hears it move 1 s later |
| `?` | Print the current channel and band |

## What to record

- **Q1:** boards on channel 36 hear each other: ESP-NOW works on 5 GHz. If not, try 149,
  then 2.4 GHz (`c 6`) to rule out the boards themselves.
- **Q2:** loss and RSSI on 6 vs 36 vs 149 with the boards worn or placed at body
  distances, especially through the torso.
- **Q3:** `s 149` on one board: every peer should reappear in the report on 149 within
  about a second. A peer that missed all five announcements stays behind, and the hub
  design must handle that with a search (E22-AND-C5-HUB.md §4.2).

## Why a probe and not a hub port

mitzey234's ESP-NOW receiver (MIT/Apache-2.0) is the intended base for the hub, but it
reaches the PC as a **USB HID** device. The ESP32-C5 has no USB OTG, only USB
Serial/JTAG (`SOC_USB_OTG_SUPPORTED` is not set), so it cannot be that device. The hub's
PC link is a design decision; see E22-AND-C5-HUB.md §3.4. This probe's answers decide
whether a C5 hub is worth building at all.

Built here with the tracker's pinned pioarduino release; not yet run on hardware.

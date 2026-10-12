# ATtiny chip-select node

Firmware for the little board that sits next to each remote IMU on an RJ45 sensor chain.
Its entire job is to own that IMU's `CS` line.

- Protocol: `../../docs/I2SPI.md`
- Wiring and cable pinout: `../../docs/dev/HARDWARE-RJ45-SPI-BUS.md`
- Why this exists at all: `../../docs/dev/DECISIONS.md`, DEC-003 and DEC-004

## Requirements

- An ATtiny with **CCL** and a **TWI slave** — ATtiny412 is the reference. ATtiny402,
  ATtiny1614 and friends work with a pin-map change. Classic ATtiny85 has no CCL and can
  only run the slow software-CS fallback.
- [megaTinyCore](https://github.com/SpenceKonde/megaTinyCore), which PlatformIO pulls in
  with `platform = atmelmegaavr`.
- A UPDI programmer. A USB-serial adapter with a 4.7 kΩ resistor between TX and RX,
  RX to the UPDI pad, is enough.

## Build and flash

```sh
cd extras/attiny-cs-node
pio run -e node1 -t upload   # then node2 on the next board, and so on
```

The node id is baked into the image (`-DNODE_ID=n`). This keeps the node board free of
address jumpers, at the cost of having to know which image went on which board — label
them as you go. The tracker will tell you if you get it wrong: it enumerates the chain at
boot and logs an error when a node answering at one address reports a different id.

## Pin map (ATtiny412)

| Pin | Function |
|---|---|
| PA0 | UPDI (programming) |
| PA1 | SDA — cable pin 7 |
| PA2 | SCL — cable pin 8 |
| PA3 | Optional sensor reset / power gate |
| PA6 | CS_STROBE in — cable pin 6 |
| PA7 | CS out — to the IMU |

PA6/PA7 are not a free choice. On an 8-pin tinyAVR the only usable CCL output is LUT0's
alternate output on PA7, and the LUT's direct pin inputs (PA0–PA2) are UPDI and TWI — so
the strobe reaches the LUT through the event system from PA6.

`SCK`, `MOSI` and `MISO` do not touch the ATtiny. They run from the cable straight to the
IMU. A hung node can fail to select; it cannot corrupt SPI data.

## How arming works

1. The host writes `ARM <id>` to the shared chain address (`0x13`, from
   `ATTinyCSProtocol.h`). Every node sees it.
2. The node whose id matches enables its CCL LUT, which passes `CS_STROBE` through to
   `CS` combinationally. Every other node disables its LUT and its port holds `CS` high.
3. The host then frames each SPI transaction by toggling one ordinary GPIO.

So I2C traffic scales with how often the host switches sensors, not with how many SPI
transactions it does. That distinction is what makes the whole topology viable — see
DEC-004.

## Untested

None of this has been on hardware yet. Known soft spots:

- The `Event`/`Logic` library API names drift between megaTinyCore versions
  (`gen0::pin_pa6`, `user::ccl0_event_a`). If it doesn't compile, that is the first place
  to look.
- `Wire.begin(addr, broadcast, second_address)` dual-address support and the
  `(addr << 1) | 1` encoding needs confirming against the core version you build with.
- The truth table (`0b00000010`) assumes inputs 1 and 2 are masked to 0.

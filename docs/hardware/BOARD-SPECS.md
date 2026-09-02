# Board specifications: I2SPI hub and extension node

Two boards cover the whole 18-point build. This document is the input to schematic
capture, not output from it — see "On kicad-happy" at the end.

Nets are named as they should appear in the schematic so that later analysis has
something consistent to grip.

---

## Board A — `slimevr-c5-hub`

Battery-powered tracker worn on chest, thigh or upper arm. One local IMU, one I2SPI chain
port. Five identical boards in this build.

### Block diagram

```
  LiPo ──┬── charger (MCP73831) ──┬── 3V3 LDO ──┬── ESP32-C5
         │                        │             ├── ICM-45686 (local)
         └── divider ── GPIO1     │             └── RJ45 3V3 (pin 1)
                                  │
   ESP32-C5 ── SPI ──┬── local IMU CS (GPIO3)
                     └── RJ45 SCK/MOSI/MISO
              I2C ───── RJ45 SDA/SCL
              GPIO6 ─── RJ45 CS_STROBE
```

### Net list

| Net | ESP32-C5 | Goes to |
|---|---|---|
| `SPI_SCK` | GPIO10 | Local IMU SCLK, RJ45 pin 3 (via 33 Ω) |
| `SPI_MOSI` | GPIO12 | Local IMU SDI, RJ45 pin 4 (via 33 Ω) |
| `SPI_MISO` | GPIO11 | Local IMU SDO, RJ45 pin 5 |
| `CS_LOCAL` | GPIO3 | Local IMU CS only — does **not** leave the board |
| `CS_STROBE` | GPIO6 | RJ45 pin 6 (via 33 Ω) |
| `CHAIN_SDA` | GPIO5 | RJ45 pin 7, 2.2 kΩ pull-up to 3V3 |
| `CHAIN_SCL` | GPIO4 | RJ45 pin 8, 2.2 kΩ pull-up to 3V3 |
| `IMU_INT` | GPIO9 | Local IMU INT1 |
| `VBAT_SENSE` | GPIO1 | Divider, 100 k / 220 k |
| `LED` | GPIO8 | Status LED + 1 kΩ |
| `AUX_SDA` / `AUX_SCL` | — | Local IMU AUX1 ↔ local QMC6309, 4.7 kΩ pull-ups |

Reserved, do not use: GPIO16–22 (flash/PSRAM), GPIO13–14 (USB-JTAG), GPIO2/7/25/27/28
(strapping), GPIO26 (boot mode).

### Notes that matter

**The local chip select never reaches the connector.** `CS_LOCAL` is a board-local net. If
it were bussed out, every extension IMU would see it and the one-hot property would be
broken by construction.

**Series terminators go here, at the source.** 33 Ω in series with `SPI_SCK`, `SPI_MOSI`
and `CS_STROBE`, placed at the hub end of the connector. This is the single highest-value
signal-integrity measure on ribbon cable and costs three resistors. `SPI_MISO` gets no
series resistor at the hub — it's an input here; if you terminate it, do so at each node's
driver.

**I2C pull-ups exist only on this board.** 2.2 kΩ, hub only. Nodes must not populate
pull-ups: two nodes at 4.7 kΩ each already parallel down to 1.5 kΩ, and a full chain would
be below what many parts can pull low.

**The magnetometer is on AUX1, not on the chain I2C.** The QMC6309's device id is fixed at
`0x7c` with no address strap, so several on one bus would collide. On AUX1 each sits on a
private bus behind its own IMU, and its samples arrive in the IMU FIFO at no extra bus
cost. See DEC-008.

**Battery divider.** 100 k / 220 k with a 180 Ω shield resistance matches the
`BAT_EXTERNAL` values in `board-defaults.json`. GPIO1 is ADC1, which is required — the C5's
ADC2 is not usable while Wi-Fi is active.

### Connector

Single vertical shielded RJ45 jack. Shield to chassis ground through a 1 MΩ / 10 nF RC to
signal ground rather than a hard tie — a hard tie makes the cable shield a ground loop
between two battery-powered boards.

---

## Board B — `slimevr-i2spi-node`

The extension. Two RJ45 jacks wired pin-for-pin in parallel for daisy chaining. Eight
built for this example.

### Block diagram

```
  RJ45 in ══╦══ RJ45 out        (all 8 conductors straight through)
            ║
   3V3 ─────╬── ATtiny412 ── CS ──┐
   GND      ║       │             │
   SCK ─────╬───────┼─────────────┼──> ICM-45686 SCLK
   MOSI ────╬───────┼─────────────┼──> ICM-45686 SDI
   MISO <───╬───────┼─────────────┼─── ICM-45686 SDO
   SDA ─────╬───────┤             └──> ICM-45686 CS
   SCL ─────╬───────┤
   STROBE ──╩───────┘             ICM-45686 AUX1 ── QMC6309
```

### Net list

| Net | ATtiny412 | Notes |
|---|---|---|
| `CHAIN_SDA` | PA1 | From cable pin 7. No pull-up on this board |
| `CHAIN_SCL` | PA2 | From cable pin 8. No pull-up on this board |
| `CS_STROBE` | PA6 | From cable pin 6, input |
| `CS_IMU` | PA7 | To the IMU's CS. CCL LUT0 alternate output |
| `SENSOR_AUX` | PA3 | Optional IMU reset or power gate |
| `UPDI` | PA0 | Programming pad, 4.7 kΩ to 3V3 |

`SPI_SCK`, `SPI_MOSI` and `SPI_MISO` run from the cable **straight to the IMU** and do not
touch the ATtiny.

### Notes that matter

**The ATtiny is not in the SPI data path.** It gates one chip select and nothing else. A
hung node can fail to select; it cannot corrupt anyone's data. Keep it that way — the
temptation to route SPI through the MCU "for buffering" would put a 20 MHz part in a 4 MHz
signal path and make every node a single point of failure for the whole chain.

**PA6/PA7 is not a free choice.** On an 8-pin tinyAVR the only usable CCL output is LUT0's
alternate on PA7, and the LUT's direct pin inputs (PA0–PA2) are UPDI and TWI — so the
strobe reaches the LUT through the event system from PA6. If you move to a 14-pin part or
a PIC with PPS, this constraint disappears.

**Gate variant.** For a node MCU without CCL, fit a 74LVC1G32 wired
`CS_IMU = CS_STROBE OR ARMED_N` and build with `-DEXTERNAL_CS_GATE`. Same timing, one more
part, and the tracker cannot tell the difference. See DEC-010.

**Two jacks, wired in parallel.** Not in and out through the MCU — straight through, so a
node in the middle of a chain is electrically a zero-length stub. The last node's spare
jack is left unpopulated or capped.

**Decoupling.** 100 nF at every supply pin of every part, plus 10 µF bulk per node. This
matters more than usual: the node is at the end of up to 85 cm of unshielded wire with a
single ground return, so its local supply has to be locally stiff.

**No hot-plug.** Powering a node while the bus is live can latch up the IMU through its
I/O pins. Nothing on the board prevents this; it's a procedure, and it belongs in the
assembly notes.

---

## Open hardware questions

- **Mechanical, and the biggest risk in the build.** Flat RJ45 patch cable is not rated
  for repeated flexing, and four of these cables cross a joint — two knees, two ankles,
  two elbows. Options: leave a service loop and treat cables as consumables; splice a
  short silicone-jacketed flexible section at the joint; or move to a different cable and
  give up "off the shelf". Whichever, strain-relieve at both jacks.
- **Shield grounding** between two battery-powered boards. The RC scheme above is a
  starting point, not a verified answer.
- **ESD.** The connector is exposed and worn on a body that accumulates charge on carpet.
  TVS on the four host-driven signals at minimum.
- **Whether the node needs the ATtiny at all** for this build, given none of the eight
  extensions use the power gate or reset. A PCF8574 plus the OR gate would do it — at the
  cost of one-hot arming and the identity block. See the node MCU section in
  `HARDWARE-RJ45-SPI-BUS.md`.

---

## On kicad-happy

I looked it up rather than assume: `kicad-happy` (aklofas/kicad-happy) is a suite of
Claude Code skills — schematic analysis, PCB layout review, EMC pre-compliance, SPICE,
datasheet extraction, BOM sourcing across DigiKey/Mouser/LCSC, and fab prep. It is
installed as a Claude Code plugin and run against an existing KiCad project directory.

Two things follow:

1. **It is not available in this session.** This is the web chat interface; the plugin
   catalog here has no KiCad entry. So nothing in this document came from kicad-happy, and
   I've labelled the estimates as estimates rather than passing them off as tool output.
2. **It analyzes, it doesn't author.** Even in Claude Code it reviews schematics and
   layouts you have already drawn. So the workflow is: capture these two boards in KiCad,
   then point kicad-happy at the project.

Which is what this document is for. It's written as the input to that capture — nets
named, values fixed, constraints stated — so that when the schematic exists there is
something to check it against. The specific things worth asking kicad-happy about once
the boards are drawn:

- Power tree and the divider ratio against the C5's ADC input range.
- Pull-up sizing against real bus capacitance for the 85 cm chain.
- The EMC pass on an 8-conductor unshielded cable carrying a 4 MHz clock — this is the
  part of the design I'd least like to be wrong about, and it's exactly what its
  pre-compliance rules are for.
- LCSC sourcing for the ATtiny412 and 74LVC1G32, since node cost times thirteen is the
  number that decides whether the gate variant is worth it.

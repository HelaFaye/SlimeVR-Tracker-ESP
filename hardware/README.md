# Hardware generator

Generates KiCad projects, a JLCPCB BOM and a V-scored panel configuration for the two
I2SPI boards.

```sh
python3 hardware/gen/verify.py                    # check every symbol and footprint
python3 hardware/gen/mklib.py --allow-unverified  # build the project symbol library
python3 hardware/gen/wizard.py --preset 18point   # pick boards, emit everything
```

## What it generates

| Output | Status |
|---|---|
| `lib/slimevr-i2spi.kicad_sym` + `.pretty` | Symbols and footprints KiCad 7 doesn't ship |
| `out/<board>/*.kicad_sch` + `.kicad_pro` | Schematics, verified to parse |
| `out/bom-jlcpcb.csv` | Aggregated across all selected boards, with LCSC numbers |
| `out/panel.json` | KiKit config for a V-scored panel |

## What it does not generate, and why

**PCB layout.** Not placement, not routing, not copper pours. This is the honest limit of
the approach: auto-routing a two-layer board with a 4 MHz SPI bus, a switched supply rail
and an RF module to manufacturable quality is not something a script does well, and a
generator that emitted a plausible-looking layout would be worse than one that emits
nothing — you would trust it.

So the flow is: generate schematics → open in KiCad → ERC → lay out by hand → then
`kikit panelize --preset :out/panel.json` across the finished boards.

**Wires.** Connections are global labels, not drawn nets. Same reason in miniature:
labelling every pin is mechanical and correct, auto-placing readable wires is not.
Anything sharing a label is one net, and ERC and netlist export both understand that.

## The verification gap that matters

KiCad 7 ships no symbol for the ESP32-C5, the ICM-45686 or the QMC6309 — all three are
newer than the library. `mklib.py` generates them from `pinouts.py`, and **those pinouts
were not read off a datasheet.** They are written from package and family knowledge.

`mklib.py` refuses to run without `--allow-unverified`, and the wizard prints a banner,
because a schematic built on a wrong pinout looks entirely correct and stays wrong until
boards come back from fab. Check each one, then set `verified=True` and record the
datasheet revision you checked against.

The footprints carry the same caveat with worse consequences: a wrong land pattern is a
board you cannot assemble.

## Panel notes

V-scoring needs straight cuts running the full width and height of the panel, so boards go
in a **uniform grid** rather than being nested tightly. That wastes some area and buys a
panel you can snap by hand. Cell size is the largest board in the selection plus clearance,
so mixing a 45 mm hub with a 26 mm node makes every cell 45 mm.

If the grid has empty cells, they are free boards — fill them with spares rather than
paying for panel area that comes back blank.

## Design provenance

Net names, terminator values, pull-up placement and the power-gating topology all come
from `docs/dev/BOARD-SPECS.md` and the decision records. Two that are easy to undo by
accident when editing the layout:

- **`CS_LOCAL` never leaves the hub board.** If it reached the connector, every extension
  IMU would see it and the one-hot property would be broken by construction.
- **Chain I2C pull-ups exist only on the hub.** Nodes must not populate their own; several
  in parallel drop below what the parts can pull low.

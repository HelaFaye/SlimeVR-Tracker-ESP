# How flexible is this, actually?

An audit of what the I2SPI addition can and cannot express. Written because "is it
flexible enough" is easy to answer optimistically and the answer is checkable.

## What it can do now

| Axis | Limit | Where enforced |
|---|---|---|
| Nodes per chain | 15 | `MaxNodeId`, nibble-packed target |
| Channels per node | 16 | `MaxChannels`, low nibble |
| Sensors per chain | 240 | product of the two |
| Chains per board | unlimited | named map under `REMOTE_CS`; each gets its own pins, address and strobe |
| SPI buses per board | unlimited | named map under `SPI`; sensors pick with `"bus"` |
| Sensor bus | SPI **or** I2C, per node and per channel | `ATTINY_CS*` vs `I2SPI_WIRE*` |
| Mixed buses on one node | yes | `I2C_CHANNELS` bitmask picks per channel |
| Local and remote on one SPI bus | yes | a direct GPIO chip select and remote ones coexist |
| Sensors per board | 16 | schema `maxItems`; the descriptor machinery has no limit |
| Chain address | any whitelisted address | `AddressWhitelist`, checked by two suites |

Two of those were only fixed by writing this document, which is the argument for writing
it.

## What was fixed while auditing

**The node firmware could not gate SCL.** The host gained `ATTinyCSWireInterface` and the
simulation grew a scenario proving four identical-address sensors coexist — but nothing in
`extras/attiny-cs-node` implemented the gating those relied on. The firmware now takes an
`I2C_CHANNELS` bitmask; the gating logic is identical to chip select, only the idle level
and the external gate differ (`OR` for CS which idles high, `AND` for SCL which idles low).

Worth naming the failure: **the simulation models the protocol, not the firmware.** It
catches a host and a node disagreeing about the wire format, because the node model is an
independent implementation of the spec. It cannot catch the firmware simply not
implementing part of the spec, because the model implements the spec correctly by
construction. That is a real limit of the harness and it should not be trusted past it.

**A board could only declare one chain and one SPI bus.** The interfaces always supported
several — the bus cache is keyed on `(scl, sda, base, strobe)` — but `preprocessor.py`
emitted a single `REMOTE_CS_*` set, so board JSON could not reach it. `SPI` and
`REMOTE_CS` now accept either a single object or a map of named ones, and sensors select
with `"bus"` / `"chain"`. The single-object form is unchanged, so no existing board moved.

## What is still inflexible, deliberately

**Node ids are compile-time.** One firmware image per node id, flashed over UPDI. The
alternative is strap resistors or an EEPROM-stored id, which puts configuration on the
node board. Reconsider if flashing 15 images ever becomes the bottleneck.

**One sensor's data path per channel.** A channel gates one signal. A node with an SPI
sensor and an I2C sensor needs two channels and two gates, not one channel doing both.

**No bulk transfer through a node.** Nodes gate; they do not buffer, translate or poll.
A node that read its own sensor and served samples would be a different design — see
DEC-003's note about where that stops being "an ATtiny that pulls CS".

**Fixed 8-conductor pinout.** The cable assignment is a hard constant, and adding a
signal means a different cable standard. This is the constraint the whole design is
shaped around (DEC-004).

## What is still inflexible, not deliberately

**`MAX_SENSORS_COUNT` is capped at 16 in the schema.** Arbitrary — the glove already runs
10 and the descriptor machinery has no limit. Raise it when something needs more.

**Chains sharing an I2C bus must not share an address** — and writing this section is how
that was found. Two chains may share SDA/SCL and differ only by strobe pin, which is what
the two-chain example does. But every node on both chains hears every frame, so an `ARM`
meant for the leg chain also arms the matching node id on the arm chain. Differing strobes
mean no chip select is asserted wrongly, but a **gated I2C sensor on the unintended chain
would ungate and answer**, which is a silent wrong-sensor read.

The example originally had both chains on `0x13`. Fixed to `0x13` and `0x12`, and
`preprocessor.py` now refuses the configuration outright, because it is invisible at
runtime:

```
chains 'legs' and 'arms' share I2C bus SCL 4/SDA 5 and address 0x13;
give each chain its own address from ATTinyCS::AddressWhitelist
```

The whitelist has seven entries, so seven chains can share one I2C bus. Beyond that, put
them on different pin pairs, or add a chain id to the frame — not done.

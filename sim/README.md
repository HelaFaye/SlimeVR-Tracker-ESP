# I2SPI chain simulation

Host build. No toolchain, no hardware, no emulator.

```sh
sim/run.sh
```

It compiles the real `ATTinyCSBus`, `ATTinyCSPinInterface`, `DirectSPIInterface`,
`DirectPinInterface` and `SPIImpl` sources against a modelled chain: ATtiny nodes that
implement `ATTinyCSProtocol.h` independently of the node firmware, and ICM-45686s that
answer at the transaction level.

## What it is for

Not "does the firmware run" — that is what hardware is for. It answers the questions that
are hard to observe on a bench and easy to get wrong in code:

- **Is exactly one chip select ever asserted?** Every I2C write and every SPI transfer is
  checked. Two asserted selects means two IMUs driving MISO, which is a bus fight rather
  than a glitch, and it is close to invisible on a scope unless you happen to be probing
  the right node at the right instant.
- **Does the cost model hold?** The DEC-004 claim is that I2C traffic scales with sensor
  switches, not SPI transactions. The simulation counts them.
- **Do the degraded paths degrade properly?** Missing node, NACKed arm write, node flashed
  with the wrong id.

Because the node model implements the protocol header independently, a host/node
disagreement about the wire format shows up here rather than on the bench — which is the
failure that cost the most time in this project so far.

## What it does not model

Timing, signal integrity, cable capacitance, CCL propagation delay, the ATtiny's TWI
peripheral, or anything analogue. Those need hardware. The bring-up order in
`docs/dev/HARDWARE-RJ45-SPI-BUS.md` still applies in full.

## Scenarios

| Scenario | Checks |
|---|---|
| Four-node chain | Enumeration, WHO_AM_I through nodes 1 and 4, one arm write per sensor |
| Repeated access | Zero I2C traffic while the armed target is unchanged |
| Missing node | Reports absent rather than garbage; no bus fight |
| Unconfigured sensor | An idle ICM-45686 reads `0x00` from its low registers and is still reported present (the DEC-012 regression) |
| Local + remote | A direct GPIO chip select and remote ones alternating on one bus |
| Protocol v2 channels | Six sensors on two nodes; demonstrates that channels save nodes, not arm writes |
| Failed arm write | Costs one write not two; no chip select left asserted; recovers on the next access |
| Mis-flashed node | Enumeration reports the id mismatch |

## Found by running it

`ATTinyCSBus::writeCs()` used to call `select()` unconditionally, including when
*releasing* a chip select. After a failed arm the release path would then issue a second
I2C write and arm a node as a side effect of letting it go. Now a release for a target
that is not the armed one just drives the strobe to its idle high state and returns.

The scenario also pinned down a distinction worth keeping straight: after a failed arm the
previously armed node stays *armed*, because the chain never saw the write. That is
harmless — assertion is the arm latch AND the strobe, and the strobe is idle high — but it
means "armed" and "asserted" are not the same thing, and code that conflates them will be
wrong in exactly this case.

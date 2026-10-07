# ATtiny chip-select node — I2C protocol

**Superseded.** This file described protocol v2: a shared chain address at `0x30` plus one
unicast address per node. The firmware speaks **v3**: one address for the whole chain
(`0x13` by default), with every frame three bytes long (opcode, target, value).

The current protocol is in [`docs/I2SPI.md`](../I2SPI.md), §3 (addressing) and §4
(commands and reads). The constants live in `src/sensorinterface/ATTinyCSProtocol.h`,
which the host and the node firmware both compile against. Why v3 replaced v2 is DEC-015
in `DECISIONS.md`. The v2 text is in git history if you need it.

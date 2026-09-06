# ATtiny chip-select node — I2C protocol

Version 2. Host = the ESP tracker. Node = one ATtiny owning one or more sensors' `CS`
lines.

**v2 changes:** `Arm` and `SetCs` payloads now carry a channel alongside the node id, so a
single node can own up to 16 chip selects. A v1 node ignores the channel nibble and
therefore still behaves correctly as a single-channel node; the host warns when it probes
one.

## Addressing

Every node listens on **two** 7-bit addresses:

| Address | Purpose |
|---|---|
| `0x30` (`ATTINY_CS_CHAIN_ADDR`) | Shared. All nodes on the chain listen. Used for one-hot arm. |
| `0x30 + nodeId` | Unicast. Used for identify, diagnostics, configuration. |

`nodeId` runs `1..15`. Node id `0` is reserved and means "no node armed" — writing it to
the chain address disarms everything, which is the defined idle state.

Default unicast range is therefore `0x31..0x3F`. This sits below the common IMU addresses
(`0x4A/0x4B` for BNO, `0x68/0x69` for most others) and above the `0x20`-block used by
MCP23X17 expanders, so a chain can share a bus with locally-wired I2C sensors. The base
is a compile-time constant (`ATTINY_CS_BASE_ADDR`) if it needs to move.

**Why two addresses instead of an I2C general call:** see DEC-007. Short version — general
call handling is inconsistent across ATtiny Arduino cores and overloaded with reset
semantics elsewhere; a plain second address is boring and portable.

## Commands

All commands are a one-byte opcode optionally followed by one payload byte.

### Write to the chain address (`0x30`)

| Opcode | Payload | Meaning |
|---|---|---|
| `0x01` `ARM` | `(nodeId << 4) \| channel` | The node whose id matches arms that channel; every other node, and every other channel on that node, disarms. `nodeId = 0` disarms all. |
| `0x02` `DISARM_ALL` | — | Equivalent to `ARM 0`. Sent on host shutdown/reset. |
| `0x7F` `RESET_ALL` | — | All nodes return to power-on state: disarmed, CS high, IMU released from reset. |

`ARM` is the hot path. It is 3 bytes on the wire (address + opcode + id) — about 70 µs at
400 kHz, 30 µs at 1 MHz — and is sent **once per sensor switch**, not once per SPI
transaction. The host skips the write entirely if the requested node is already armed.

### Write to a unicast address (`0x30 + nodeId`)

**The two opcode spaces are deliberately disjoint** — chain opcodes are `0x01`, `0x02`
and `0x7F`; unicast opcodes are `0x10`–`0x20`. This is not cosmetic. The Arduino TWI
slave drivers on the ATtiny cores do not report *which* of the node's two addresses was
matched, so the node cannot tell a chain write from a unicast write by address. Disjoint
opcodes make the address irrelevant to decoding. Keep them disjoint when extending the
protocol.

| Opcode | Payload | Meaning |
|---|---|---|
| `0x10` `SET_CS` | `(channel << 4) \| level`, level `0` = assert (low), `1` = deassert (high) | Software-CS fallback. Drives `CS` directly, ignoring the strobe. Only valid while the node is armed *on that channel* - a mismatched channel is refused, so a stale command cannot pull a chip select out from under the host. |
| `0x11` `SET_MODE` | `0` = software CS, `1` = strobe (CCL) | Persists until reset. Power-on default is strobe. |
| `0x12` `SET_SENSOR_POWER` | `0` = off, `1` = on | Optional; only meaningful if the node populates the power-gate FET. |
| `0x13` `SET_SENSOR_RESET` | `0` = release, `1` = hold | Optional; drives the IMU reset pin if wired. |
| `0x20` `IDENTIFY` | — | Sets the read pointer to the identity block. |

### Read from a unicast address

A read returns the 4-byte identity/status block:

| Byte | Meaning |
|---|---|
| 0 | Magic `0x5C` ("**S**lime **C**S") — lets the host tell a node from a random device |
| 1 | Protocol version, currently `0x02` |
| 2 | `nodeId` as the node believes it to be |
| 3 | Status bits: `bit0` armed, `bit1` strobe mode, `bit2` sensor powered, `bit3` sensor held in reset |

The host uses this at startup to enumerate the chain and to catch the two failure modes
that otherwise produce baffling symptoms: a node flashed with the wrong id, and two nodes
sharing an id.

## Multi-channel nodes

A node owning several chip selects addresses them by channel, `0`–`15`. Channel 0 is the
default and is what a single-sensor node uses.

The CCL build is single-channel by construction: an 8-pin tinyAVR has exactly one usable
CCL output. Multi-channel therefore requires the `EXTERNAL_CS_GATE` build with one OR gate
per channel, which the node firmware enforces with an `#error`. Set `-DNUM_CHANNELS=n` and
`-DARMED_N_PINS={...}` to match the board.

Arming is still strictly one-hot across the whole chain: arming (node 2, channel 1)
disarms node 3 entirely *and* channel 0 on node 2.

## Host state machine

```
                    ┌──────────────┐
   startup ────────▶│  disarm all  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐   armedNode == requested
   select(node) ───▶│ already armed├──────────────────────────▶ no I2C traffic
                    └──────┬───────┘
                           │ different
                    ┌──────▼───────┐
                    │ write ARM id │──▶ armedNode = id
                    └──────────────┘
```

The host must disarm on any I2C error and re-arm on the next transaction, because a
dropped `ARM` leaves the host's idea of the armed node wrong — and a wrong belief here
means talking to the *other* IMU, which produces plausible-looking but wrong data. Fail
loudly instead: `ATTinyCSBus` invalidates its cached selection whenever a write fails.

## Timing contract

- After `ARM`, the node's `CS` is valid within **2 µs** (one CCL reconfiguration plus port
  write). The host inserts a short guard delay before the first SPI transaction.
- In strobe mode the propagation from `CS_STROBE` to `CS` is combinational — CCL only,
  no CPU. Budget < 100 ns.
- In software-CS mode each assert and deassert is a full 3-byte I2C write, ~72 µs at
  400 kHz, so ~145 µs to frame one transaction. This is why it is a bring-up mode and not
  the default.

## Node firmware

See `extras/attiny-cs-node/`. The node id is set at compile time (`-DNODE_ID=n`) and
flashed via UPDI, one image per node id. Burning the id into the image rather than reading
it from a strap resistor keeps the node board free of configuration jumpers, at the cost
of needing to know which image goes on which board — label them.

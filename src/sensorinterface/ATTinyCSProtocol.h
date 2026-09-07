/*
	SlimeVR Code is placed under the MIT license
	Copyright (c) 2026 SlimeVR Contributors

	Permission is hereby granted, free of charge, to any person obtaining a copy
	of this software and associated documentation files (the "Software"), to deal
	in the Software without restriction, including without limitation the rights
	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the Software is
	furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in
	all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
	THE SOFTWARE.
*/
#pragma once

#include <stdint.h>

/*
 * Wire protocol between the tracker and the ATtiny chip-select nodes on an RJ45 sensor
 * chain. Shared verbatim by the tracker firmware and by extras/attiny-cs-node, so keep
 * this header free of Arduino and of anything the ATtiny toolchain can't compile.
 *
 * Full protocol description: docs/dev/ATTINY-CS-PROTOCOL.md
 */

namespace SlimeVR::ATTinyCS {

/// Every node listens on this **one** address. Commands carry their target in the
/// frame, and reads are answered by whichever node the last Identify selected -
/// one-hot, by the same broadcast mechanism as arming.
///
/// Protocol v2 used a shared address plus one unicast address per node, which needed 16
/// consecutive free addresses. There is no such window on a bus that also carries the
/// sensors this firmware supports: see hardware/gen/i2c_address_map.py, which computes
/// the map from the driver sources. v3 needs one address, and the whitelist below has
/// plenty. See docs/dev/DECISIONS.md DEC-015.
constexpr uint8_t DefaultBaseAddress = 0x13;
constexpr uint8_t AddressSpan = 1;

/// Vetted alternatives, ranked by distance from the nearest address any supported or
/// common part uses. Regenerate with `python3 hardware/gen/i2c_address_map.py`; the
/// checker in sim/check_numbers.py fails if DefaultBaseAddress drifts off this list.
constexpr uint8_t AddressWhitelist[] = {0x13, 0x12, 0x14, 0x11, 0x15, 0x34, 0x35};

/// 0x00-0x07 and 0x78-0x7F are reserved by the I2C specification.
constexpr uint8_t AddressMin = 0x08;
constexpr uint8_t AddressMax = 0x77;

constexpr uint8_t MinNodeId = 1;
constexpr uint8_t MaxNodeId = 15;
constexpr uint8_t NoNode = 0;

/// A node may own more than one chip select, or more than one gated I2C sensor. The
/// channel rides in the low nibble alongside the node id.
constexpr uint8_t MaxChannels = 16;
constexpr uint8_t DefaultChannel = 0;

/// Node id in the high nibble, channel in the low nibble.
constexpr uint8_t packTarget(uint8_t nodeId, uint8_t channel) {
	return static_cast<uint8_t>((nodeId & 0x0F) << 4 | (channel & 0x0F));
}
constexpr uint8_t unpackNodeId(uint8_t target) { return (target >> 4) & 0x0F; }
constexpr uint8_t unpackChannel(uint8_t target) { return target & 0x0F; }

/// Every frame is exactly three bytes: opcode, target, value. Uniform because there is
/// only one address now, so the node can no longer infer anything from being addressed.
constexpr uint8_t FrameLength = 3;

enum class Command : uint8_t {
	Arm = 0x01,  ///< value ignored. Target's chip select follows the strobe.
	DisarmAll = 0x02,  ///< target and value ignored
	PowerAll = 0x03,  ///< value: 0 off, 1 on. Every node gates its sensor.
	SetCs = 0x10,  ///< value: 0 assert (low), 1 deassert. Software-CS mode only.
	SetMode = 0x11,  ///< value: 0 software CS, 1 strobe
	SetSensorPower = 0x12,  ///< value: 0 off, 1 on. Drives the VCC pass MOSFET.
	SetSensorReset = 0x13,  ///< value: 0 release, 1 hold. Cuts the rail.
	Identify = 0x20,  ///< target answers the next read with its identity block
	ResetAll = 0x7F,  ///< back to power-on state
};

enum class CsMode : uint8_t {
	Software = 0,
	Strobe = 1,
};

/// First byte of the identity block. Lets the host tell one of our nodes apart from
/// whatever else happens to answer at that address.
constexpr uint8_t IdentityMagic = 0x5C;

/// v3 collapsed the two addresses into one and made every frame three bytes. It is NOT
/// wire-compatible with v1 or v2; the host refuses to drive a node reporting an older
/// version, because a v2 node would decode a v3 frame's target byte as its payload.
constexpr uint8_t ProtocolVersion = 0x03;
constexpr uint8_t IdentityLength = 4;

/// Bits in byte 3 of the identity block.
constexpr uint8_t StatusArmed = 1 << 0;
constexpr uint8_t StatusStrobeMode = 1 << 1;
constexpr uint8_t StatusSensorPowered = 1 << 2;
constexpr uint8_t StatusSensorHeldInReset = 1 << 3;

/// The node needs a moment after Arm to reconfigure its gating before CS is valid.
constexpr uint16_t ArmSettleMicros = 2;

/// After switching a sensor's VCC on, how long before the node's sensors will answer.
///
/// Set by the QMC6309, not the IMU: its datasheet gives PSUP (supply ramp, 0.2 V to
/// operating voltage) < 10 ms and PORT (power-on-reset completion) < 3 ms, so 13 ms
/// before it will accept an I2C command. 15 ms adds margin for the RC of a gated rail
/// at the end of a metre of cable. An earlier value of 10 ms was too short and would
/// have produced a magnetometer that intermittently failed to configure.
constexpr uint16_t SensorPowerOnSettleMillis = 15;

/// The QMC6309 needs its supply below SDV (0.2 V) for at least PINT before it will
/// power-on-reset again. Enforced when power-cycling a node's sensors.
constexpr uint16_t SensorPowerOffHoldMicros = 100;

/// Sensors power up gated OFF so the host can bring them online one at a time. See
/// docs/dev/DECISIONS.md DEC-014.
constexpr bool SensorPowerDefaultOn = false;

}  // namespace SlimeVR::ATTinyCS

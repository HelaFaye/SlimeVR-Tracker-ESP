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

/// Nodes listen on BaseAddress (shared, for one-hot arm) and BaseAddress + nodeId
/// (unicast, for identify and configuration). Node id 0 means "nothing armed".
constexpr uint8_t DefaultBaseAddress = 0x30;

/// 0x00-0x07 and 0x78-0x7F are reserved by the I2C specification.
constexpr uint8_t AddressMin = 0x08;
constexpr uint8_t AddressMax = 0x77;

constexpr uint8_t MinNodeId = 1;
constexpr uint8_t MaxNodeId = 15;
constexpr uint8_t NoNode = 0;

/// A node may own more than one chip select. The channel rides in the low nibble
/// alongside the node id, so one node can serve a cluster of sensors.
constexpr uint8_t MaxChannels = 16;
constexpr uint8_t DefaultChannel = 0;

/// Node id in the high nibble, channel in the low nibble. Used by Arm and SetCs.
constexpr uint8_t packTarget(uint8_t nodeId, uint8_t channel) {
	return static_cast<uint8_t>((nodeId & 0x0F) << 4 | (channel & 0x0F));
}
constexpr uint8_t unpackNodeId(uint8_t target) { return (target >> 4) & 0x0F; }
constexpr uint8_t unpackChannel(uint8_t target) { return target & 0x0F; }

/// Written to the shared chain address.
enum class ChainCommand : uint8_t {
	Arm = 0x01,  ///< payload: packTarget(nodeId, channel). One-hot; all others disarm.
	DisarmAll = 0x02,  ///< equivalent to Arm(0)
	PowerAll = 0x03,  ///< payload: 0 off, 1 on. Every node gates its sensor at once.
	ResetAll = 0x7F,  ///< back to power-on state
};

/// Written to a node's unicast address.
enum class NodeCommand : uint8_t {
	SetCs = 0x10,  ///< payload: (channel << 4) | level. Software-CS mode only.
	SetMode = 0x11,  ///< payload: 0 software CS, 1 strobe (CCL or external gate)
	SetSensorPower = 0x12,  ///< payload: 0 off, 1 on. Drives the VCC pass MOSFET.
	SetSensorReset = 0x13,  ///< payload: 0 release, 1 hold. Optional hardware.
	Identify = 0x20,  ///< no payload; next read returns the identity block
};

/// Payload encoding for SetCs.
constexpr uint8_t packSetCs(uint8_t channel, uint8_t level) {
	return static_cast<uint8_t>((channel & 0x0F) << 4 | (level != 0 ? 1 : 0));
}

enum class CsMode : uint8_t {
	Software = 0,
	Strobe = 1,
};

/// First byte of the identity block. Lets the host tell one of our nodes apart from
/// whatever else happens to answer at that address.
constexpr uint8_t IdentityMagic = 0x5C;

/// v2 added the node id / channel packing to Arm and SetCs. A v1 node ignores the
/// channel nibble, so it behaves correctly as a single-channel node.
constexpr uint8_t ProtocolVersion = 0x02;
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

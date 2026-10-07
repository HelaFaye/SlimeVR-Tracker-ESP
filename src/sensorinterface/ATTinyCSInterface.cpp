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
#include "ATTinyCSInterface.h"

#include <Wire.h>

#include "I2CWireSensorInterface.h"

namespace SlimeVR {

using namespace ATTinyCS;

ATTinyCSBus::ATTinyCSBus(
	uint8_t sclPin,
	uint8_t sdaPin,
	uint8_t baseAddress,
	int8_t strobePin
)
	: m_sclPin(sclPin)
	, m_sdaPin(sdaPin)
	, m_baseAddress(baseAddress)
	, m_strobePin(strobePin) {}

void ATTinyCSBus::swapIn() {
	// Cheap when the bus is already on these pins, and necessary when the tracker also
	// has locally wired I2C sensors on a different pin pair.
	swapI2C(m_sclPin, m_sdaPin);
}

bool ATTinyCSBus::init() {
	// The whole chain shares this one address, so it has to be one the I2C spec leaves
	// to us.
	m_addressValid = m_baseAddress >= AddressMin && m_baseAddress <= AddressMax;

	if (!m_addressValid) {
		m_Logger.error(
			"Chain address 0x%02X is outside the usable I2C range 0x%02X-0x%02X",
			m_baseAddress,
			AddressMin,
			AddressMax
		);
		return true;  // see the note on the return value below
	}

	swapIn();

	if (usesStrobe()) {
		::pinMode(m_strobePin, OUTPUT);
		::digitalWrite(m_strobePin, HIGH);
	}

	// Known state before anything else touches the chain: nothing armed, every node's
	// CS high. Without this a node left armed by a previous boot would fight the first
	// sensor we talk to.
	disarmAll();

	// Sensors come up with their VCC gated off (SensorPowerDefaultOn), so the chain can
	// be enumerated with nothing but the ATtinys drawing current and nothing driving
	// MISO. Belt and braces in case a node was left powered by a previous run.
	setAllSensorPower(false);

	m_presentNodes = 0;
	uint8_t found = 0;
	for (uint8_t node = MinNodeId; node <= MaxNodeId; node++) {
		if (probe(node)) {
			m_presentNodes |= static_cast<uint16_t>(1u << node);
			found++;
		}
	}

	if (found == 0) {
		m_Logger.warn(
			"No ATtiny CS nodes answered on SCL %d / SDA %d (base address 0x%02X). "
			"Remote SPI sensors will not be detected.",
			m_sclPin,
			m_sdaPin,
			m_baseAddress
		);
	} else {
		m_Logger.info(
			"Found %d ATtiny CS node(s), CS framing: %s",
			found,
			usesStrobe() ? "strobe" : "software (slow, bring-up only)"
		);
	}

	stageSensorPowerUp();

	// Always true: a chain with no nodes has to surface as "sensor not found" via
	// isPresent(), not as a failed interface. Returning false here would make the
	// manager cache a null pointer for the whole bus, which takes down every sensor on
	// the chain instead of just the missing one.
	return true;
}

bool ATTinyCSBus::isNodePresent(uint8_t nodeId) const {
	if (nodeId < MinNodeId || nodeId > MaxNodeId) {
		return false;
	}
	return (m_presentNodes & static_cast<uint16_t>(1u << nodeId)) != 0;
}

// One address, one frame shape: opcode, target, value. See DEC-015.
bool ATTinyCSBus::writeFrame(Command command, uint8_t target, uint8_t value) {
	if (!m_addressValid) {
		return false;
	}

	swapIn();

	Wire.beginTransmission(m_baseAddress);
	Wire.write(static_cast<uint8_t>(command));
	Wire.write(target);
	Wire.write(value);
	return Wire.endTransmission() == 0;
}

bool ATTinyCSBus::select(uint8_t nodeId, uint8_t channel) {
	const uint8_t target = packTarget(nodeId, channel);

	if (target == m_armedTarget) {
		return true;
	}

	if (!writeFrame(Command::Arm, target, 0)) {
		// Drop our cached belief rather than assume the write landed. Re-arming costs
		// one short write; being wrong costs reading the wrong sensor's registers.
		m_armedTarget = 0;
		m_Logger.error("Failed to arm ATtiny CS node %d channel %d", nodeId, channel);
		return false;
	}

	m_armedTarget = target;
	delayMicroseconds(ArmSettleMicros);
	return true;
}

void ATTinyCSBus::writeCs(uint8_t nodeId, uint8_t channel, uint8_t level) {
	const uint8_t target = packTarget(nodeId, channel);

	if (level != LOW && m_armedTarget != target) {
		// Releasing a chip select we never managed to assert - normally because the arm
		// write failed. Arming now would spend an I2C write reaching a state we are
		// immediately leaving, and would arm a node as a side effect of releasing it.
		// Driving the strobe high is safe regardless of who is armed: high is idle.
		if (usesStrobe()) {
			::digitalWrite(m_strobePin, HIGH);
		}
		return;
	}

	if (!select(nodeId, channel)) {
		// Do not touch the strobe. Some other node may still be armed, and pulsing the
		// shared strobe would assert its chip select instead of ours.
		return;
	}

	if (usesStrobe()) {
		::digitalWrite(m_strobePin, level);
		return;
	}

	if (!writeFrame(Command::SetCs, target, level == LOW ? 0 : 1)) {
		// A dropped CS write means the next SPI transfer clocks against an unknown chip
		// select, which produces data that looks plausible and is wrong. Say so, and
		// force a re-arm so the next attempt re-establishes state from scratch.
		m_armedTarget = 0;
		m_Logger.error(
			"Failed to drive CS on ATtiny CS node %d channel %d",
			nodeId,
			channel
		);
	}
}

bool ATTinyCSBus::probe(uint8_t nodeId) {
	if (!m_addressValid) {
		return false;
	}

	// Identify latches which node answers the next read - one-hot, like arming.
	if (!writeFrame(Command::Identify, packTarget(nodeId, DefaultChannel), 0)) {
		return false;
	}

	const uint8_t read = Wire.requestFrom(m_baseAddress, IdentityLength);
	if (read != IdentityLength) {
		return false;
	}

	// Wire.read() returns int and can signal underflow with -1, but requestFrom()
	// already confirmed IdentityLength bytes are buffered.
	const auto magic = static_cast<uint8_t>(Wire.read());
	const auto version = static_cast<uint8_t>(Wire.read());
	const auto reportedId = static_cast<uint8_t>(Wire.read());
	const auto status = static_cast<uint8_t>(Wire.read());

	if (magic != IdentityMagic) {
		m_Logger.warn(
			"Device at 0x%02X answering for node %d is not an ATtiny CS node "
			"(magic 0x%02X)",
			m_baseAddress,
			nodeId,
			magic
		);
		return false;
	}

	if (version != ProtocolVersion) {
		// v1 nodes ignore the channel nibble, so they still work as single-channel
		// nodes. Worth saying out loud before someone wires a second sensor to one.
		m_Logger.warn(
			"ATtiny CS node %d speaks protocol v%d, firmware expects v%d - "
			"multi-channel "
			"selection will not work on this node",
			nodeId,
			version,
			ProtocolVersion
		);
	}

	if (reportedId != nodeId) {
		// Almost always a node flashed with the wrong -DNODE_ID. Worth shouting about:
		// the symptom otherwise is one sensor that mysteriously never appears.
		m_Logger.error(
			"ATtiny CS node answering at id %d reports id %d - check which image was "
			"flashed to which node board",
			nodeId,
			reportedId
		);
	}

	m_Logger.debug(
		"ATtiny CS node %d present (status 0x%02X, mode %s)",
		nodeId,
		status,
		(status & StatusStrobeMode) ? "strobe" : "software"
	);
	return true;
}

bool ATTinyCSBus::setSensorPower(uint8_t nodeId, bool on) {
	return writeFrame(
		Command::SetSensorPower,
		packTarget(nodeId, DefaultChannel),
		on ? 1 : 0
	);
}

bool ATTinyCSBus::setAllSensorPower(bool on) {
	return writeFrame(Command::PowerAll, packTarget(NoNode, 0), on ? 1 : 0);
}

void ATTinyCSBus::stageSensorPowerUp() {
	// One at a time rather than a broadcast. Three reasons, in order of how much they
	// matter: a sensor that is shorted or drawing wrongly is attributable to a node
	// instead of taking the rail down anonymously; inrush is spread over milliseconds
	// rather than summed across the chain, which at the far end of a metre of thin
	// cable is the difference between a droop and a brownout; and each sensor gets a
	// clean supply ramp with nothing else switching on the same rail.
	for (uint8_t node = MinNodeId; node <= MaxNodeId; node++) {
		if (!isNodePresent(node)) {
			continue;
		}

		if (!setSensorPower(node, true)) {
			m_Logger.error(
				"Node %d did not accept sensor power-on; its sensor will read as "
				"absent",
				node
			);
			continue;
		}

		delay(SensorPowerOnSettleMillis);
		m_Logger.debug("Node %d sensor powered", node);
	}
}

void ATTinyCSBus::disarmAll() {
	writeFrame(Command::DisarmAll, packTarget(NoNode, 0), 0);
	m_armedTarget = 0;

	if (usesStrobe()) {
		::digitalWrite(m_strobePin, HIGH);
	}
}

std::string ATTinyCSBus::toString() const {
	using namespace std::string_literals;
	return "ATTinyCSBus(scl "s + std::to_string(m_sclPin) + ", sda "
		 + std::to_string(m_sdaPin) + ", base " + std::to_string(m_baseAddress)
		 + (usesStrobe() ? ", strobe " + std::to_string(m_strobePin) : ", no strobe")
		 + ")";
}

bool ATTinyCSWireInterface::init() {
	// Same reasoning as the pin interface: a missing node has to surface as a missing
	// sensor, not as a failed interface.
	return true;
}

void ATTinyCSWireInterface::swapIn() {
	// The sensor's own traffic goes out on the chain's pins, so Wire has to be there
	// even when select() has nothing to do. select() skips the bus entirely when this
	// target is already armed, and a local I2C sensor polled in between will have moved
	// Wire to its own pins - leaving this sensor's reads on the wrong bus.
	m_bus->swapIn();

	// Arming ungates this node's sensor SCL and gates every other node's. From here the
	// caller does ordinary Wire traffic; the sensor's own address is irrelevant to
	// anyone else on the chain because nobody else can hear the clock.
	m_bus->select(m_nodeId, m_channel);
}

bool ATTinyCSWireInterface::isNodePresent() const {
	return m_bus != nullptr && m_bus->isNodePresent(m_nodeId);
}

bool ATTinyCSPinInterface::init() {
	// Deliberately not gated on the node answering. A missing node has to look like a
	// missing sensor further up the stack via isPresent(), otherwise the interface
	// cache hands back nullptr and SPIImpl has no chip select to report on at all.
	return true;
}

bool ATTinyCSPinInterface::isPresent() const {
	return m_bus != nullptr && m_bus->isNodePresent(m_nodeId);
}

int ATTinyCSPinInterface::digitalRead() { return m_lastLevel; }

void ATTinyCSPinInterface::pinMode(uint8_t) {
	// The remote pin is permanently an output; the node owns its direction.
}

void ATTinyCSPinInterface::digitalWrite(uint8_t val) {
	m_lastLevel = val;
	m_bus->writeCs(m_nodeId, m_channel, val);
}

}  // namespace SlimeVR

/*
 * Host-side model of an I2SPI chain.
 *
 * Runs the real ATTinyCSBus / ATTinyCSPinInterface / DirectSPIInterface / SPIImpl
 * sources against modelled ATtiny nodes and modelled ICM-45686s, so the bus sequencing
 * can be exercised without hardware. It is not a device emulator - it models behaviour
 * at the transaction level, which is the level the bugs worth catching live at:
 *
 *   - is exactly one chip select ever asserted?          (the one-hot invariant,
 * DEC-007)
 *   - does the ARM write actually precede the transfer?
 *   - how many I2C writes does a poll cycle really cost? (the DEC-004 claim)
 *   - does a missing node degrade to "absent" rather than to garbage or a crash?
 *
 * The node model implements ATTinyCSProtocol.h independently of the node firmware, so a
 * host/node protocol disagreement shows up here rather than on the bench.
 */
#include "chain_model.h"

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>

#include <cstdio>

#include "ATTinyCSProtocol.h"

using namespace SlimeVR::ATTinyCS;

namespace sim {

Chain g_chain;

// ---------------------------------------------------------------- GPIO / strobe

void gpioWrite(int pin, int level) {
	if (pin == g_chain.strobePin) {
		g_chain.strobe = level;
		g_chain.stats.strobeToggles++;
	}
	g_chain.gpio[pin] = level;
}

int gpioRead(int pin) { return g_chain.gpio.count(pin) ? g_chain.gpio[pin] : HIGH; }

// A node's chip select is low when it is armed on that channel and the strobe is low.
// This is the OR-gate / CCL behaviour expressed as one line, which is the whole point
// of the design: no firmware is in this path on real hardware either.
bool Node::csAsserted(uint8_t channel) const {
	if (!armed || armedChannel != channel) {
		return false;
	}
	return softwareCsLow || (mode == CsMode::Strobe && g_chain.strobe == LOW);
}

// --------------------------------------------------------------- ATtiny node model

void Node::onWrite(const std::vector<uint8_t>& bytes, bool toChainAddress) {
	// v3: every frame is exactly opcode, target, value, to the one chain address.
	if (bytes.size() != FrameLength) {
		g_chain.fail("malformed frame: v3 frames are exactly three bytes");
		return;
	}
	(void)toChainAddress;

	const uint8_t opcode = bytes[0];
	const uint8_t target = bytes[1];
	const uint8_t value = bytes[2];
	const uint8_t payload = target;  // Arm's target doubles as its payload

	if (opcode == static_cast<uint8_t>(Command::Arm)) {
		const uint8_t wantNode = unpackNodeId(payload);
		const uint8_t wantChannel = unpackChannel(payload);
		armed = (wantNode == id) && (wantChannel < channels);
		armedChannel = armed ? wantChannel : 0;
		softwareCsLow = false;
		return;
	}

	if (opcode == static_cast<uint8_t>(Command::PowerAll)) {
		setSensorPower(value != 0);
		return;
	}

	if (opcode == static_cast<uint8_t>(Command::SetSensorPower)) {
		if (unpackNodeId(target) == id) {
			setSensorPower(value != 0);
		}
		return;
	}

	if (opcode == static_cast<uint8_t>(Command::Identify)) {
		// One-hot, like arming: the matching node answers the next read, and every
		// other node stands down so two nodes can never drive SDA together.
		answersRead = (unpackNodeId(target) == id);
		return;
	}

	if (opcode == static_cast<uint8_t>(Command::DisarmAll)
		|| opcode == static_cast<uint8_t>(Command::ResetAll)) {
		armed = false;
		armedChannel = 0;
		softwareCsLow = false;
		return;
	}

	if (opcode == static_cast<uint8_t>(Command::SetCs)) {
		if (!armed || mode != CsMode::Software) {
			return;
		}
		if (unpackNodeId(target) != id || unpackChannel(target) != armedChannel) {
			return;
		}
		softwareCsLow = (value == 0);
		return;
	}

	if (opcode == static_cast<uint8_t>(Command::SetMode)) {
		if (unpackNodeId(target) == id) {
			mode = value == 0 ? CsMode::Software : CsMode::Strobe;
		}
	}
}

void Node::setSensorPower(bool on) {
	if (on && !sensorPowered) {
		g_chain.stats.powerOnEvents++;
	}
	sensorPowered = on;
	for (auto& sensor : sensors) {
		sensor.powered = on;
	}

	// How many sensors were mid-ramp at once? Staged bring-up should never exceed one.
	int ramping = 0;
	for (const auto& node : g_chain.nodes) {
		if (node.present && node.sensorPowered && !node.settled) {
			ramping++;
		}
	}
	if (ramping > g_chain.stats.maxSimultaneousPowerUps) {
		g_chain.stats.maxSimultaneousPowerUps = ramping;
	}
	settled = false;
}

std::vector<uint8_t> Node::identity() const {
	uint8_t status = 0;
	if (armed) {
		status |= StatusArmed;
	}
	if (mode == CsMode::Strobe) {
		status |= StatusStrobeMode;
	}
	if (sensorPowered) {
		status |= StatusSensorPowered;
	}
	return {IdentityMagic, ProtocolVersion, reportedId, status};
}

// ------------------------------------------------------------------- I2C transport

void Chain::i2cBegin(uint8_t addr) {
	txAddress = addr;
	txBuffer.clear();
}

uint8_t Chain::i2cEnd() {
	stats.i2cWrites++;
	stats.i2cBytes += txBuffer.size() + 1;

	if (failNextWrite) {
		failNextWrite = false;
		stats.i2cFailures++;
		return 4;  // NACK
	}

	if (txAddress != baseAddress) {
		// Traffic aimed at a chained I2C sensor. Only nodes whose SCL is ungated can
		// hear it, so identical addresses on different nodes never collide.
		int listening = 0;
		for (auto& node : nodes) {
			if (node.present && node.wireSensorListening()
				&& node.wireAddress == txAddress) {
				listening++;
			}
		}
		if (listening > 1) {
			fail("BUS FIGHT: two gated I2C sensors listening at the same address");
		}
		stats.wireSensorWrites += listening;
		return listening ? 0 : 2;
	}

	for (auto& node : nodes) {
		if (node.present) {
			node.onWrite(txBuffer, true);
		}
	}

	checkOneHot("after I2C write");
	return 0;
}

uint8_t Chain::i2cRequest(uint8_t addr, uint8_t len) {
	rxBuffer.clear();
	if (addr != baseAddress) {
		return 0;
	}
	int answering = 0;
	for (auto& node : nodes) {
		if (node.present && node.answersRead) {
			rxBuffer = node.identity();
			answering++;
		}
	}
	if (answering > 1) {
		// Two nodes driving SDA on a read is the same class of fault as two chip
		// selects on MISO, and just as invisible.
		fail("READ COLLISION: more than one node answered a read");
	}
	if (rxBuffer.size() > len) {
		rxBuffer.resize(len);
	}
	rxPos = 0;
	return static_cast<uint8_t>(rxBuffer.size());
}

// ------------------------------------------------------------------- SPI transport

uint8_t Chain::spiTransfer(uint8_t out) {
	stats.spiBytes++;

	// Which sensors are listening right now?
	std::vector<Sensor*> selected;
	if (localCsPin >= 0 && gpioRead(localCsPin) == LOW && localSensor.present) {
		selected.push_back(&localSensor);
	}
	for (auto& node : nodes) {
		for (uint8_t ch = 0; ch < node.channels; ch++) {
			if (node.present && node.csAsserted(ch) && node.sensors[ch].present) {
				selected.push_back(&node.sensors[ch]);
			}
		}
	}

	if (selected.size() > 1) {
		// Two IMUs driving MISO. On hardware this is a bus fight, not a glitch.
		fail("BUS FIGHT: more than one chip select asserted during an SPI transfer");
	}

	if (selected.empty()) {
		return 0xFF;  // floating MISO
	}

	return selected[0]->transfer(out);
}

void Chain::checkOneHot(const char* where) {
	int asserted = 0;
	if (localCsPin >= 0 && gpioRead(localCsPin) == LOW) {
		asserted++;
	}
	for (auto& node : nodes) {
		for (uint8_t ch = 0; ch < node.channels; ch++) {
			if (node.present && node.csAsserted(ch)) {
				asserted++;
			}
		}
	}
	if (asserted > 1) {
		std::printf("  !! %d chip selects asserted %s\n", asserted, where);
		failures++;
	}
}

void Chain::fail(const char* message) {
	std::printf("  !! %s\n", message);
	failures++;
}

// ---------------------------------------------------------------- ICM-45686 model

uint8_t Sensor::transfer(uint8_t out) {
	if (!powered) {
		// No supply: the sensor cannot drive MISO, so the host sees the idle bus.
		return 0xFF;
	}

	if (expectRegister) {
		expectRegister = false;
		// Bit 7 set means read on this part.
		reading = (out & 0x80) != 0;
		address = out & 0x7F;
		return 0x00;
	}

	if (!reading) {
		expectRegister = true;
		return 0x00;
	}

	const uint8_t reg = address++;
	if (reg == 0x72) {
		return 0xE9;  // WHO_AM_I
	}
	if (reg < 0x0C) {
		// Accel and gyro data. Zero until configured - the exact behaviour that made
		// the register-probing presence heuristic reject a healthy sensor (DEC-012).
		return configured ? dataByte++ : 0x00;
	}
	return 0x00;
}

}  // namespace sim

// ------------------------------------------------------- Arduino shim entry points

SPIClass SPI;
TwoWire Wire;

uint8_t SPIClass::transfer(uint8_t v) { return sim::g_chain.spiTransfer(v); }

void TwoWire::beginTransmission(uint8_t addr) { sim::g_chain.i2cBegin(addr); }
size_t TwoWire::write(uint8_t b) {
	sim::g_chain.txBuffer.push_back(b);
	return 1;
}
uint8_t TwoWire::endTransmission() { return sim::g_chain.i2cEnd(); }
uint8_t TwoWire::requestFrom(uint8_t addr, uint8_t len) {
	return sim::g_chain.i2cRequest(addr, len);
}
int TwoWire::available() {
	return static_cast<int>(sim::g_chain.rxBuffer.size() - sim::g_chain.rxPos);
}
int TwoWire::read() {
	if (sim::g_chain.rxPos >= sim::g_chain.rxBuffer.size()) {
		return -1;
	}
	return sim::g_chain.rxBuffer[sim::g_chain.rxPos++];
}

void delayMicroseconds(unsigned us) { sim::g_chain.stats.delayMicros += us; }

void delay(unsigned ms) {
	sim::g_chain.stats.delayMillis += ms;
	// A settle delay means whatever was ramping has now finished, so the next power-on
	// is not simultaneous with it.
	for (auto& node : sim::g_chain.nodes) {
		node.settled = true;
	}
}

namespace SlimeVR {
void swapI2C(uint8_t, uint8_t) {}
}  // namespace SlimeVR

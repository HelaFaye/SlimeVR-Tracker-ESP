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

#include <Arduino.h>
#include <PinInterface.h>

#include <cstdint>
#include <string>

#include "ATTinyCSProtocol.h"
#include "SensorInterface.h"
#include "logging/Logger.h"

namespace SlimeVR {

/**
 * One chain of ATtiny chip-select nodes hanging off an RJ45 cable.
 *
 * Every remote SPI sensor's CS line is owned by an ATtiny with its own I2C address. The
 * host arms exactly one (node, channel) at a time with a single broadcast write; the
 * armed node then mirrors the shared CS_STROBE conductor onto that channel's CS in
 * hardware, so framing each SPI transaction costs one host GPIO toggle rather than an
 * I2C round trip.
 *
 * If no strobe pin is configured the bus falls back to driving CS over I2C, which is
 * roughly a thousand times slower per transaction and is meant for bring-up only.
 *
 * See docs/dev/ATTINY-CS-PROTOCOL.md and DECISIONS.md DEC-004/DEC-007/DEC-011.
 */
class ATTinyCSBus {
public:
	ATTinyCSBus(
		uint8_t sclPin,
		uint8_t sdaPin,
		uint8_t baseAddress,
		int8_t strobePin  // -1 => software-CS fallback
	);

	bool init();

	/// True when CS framing is done by toggling the host strobe pin rather than by I2C.
	[[nodiscard]] bool usesStrobe() const { return m_strobePin >= 0; }

	/// True if this node answered the identity probe at startup.
	[[nodiscard]] bool isNodePresent(uint8_t nodeId) const;

	/// Make (nodeId, channel) the armed target. No bus traffic if it already is.
	bool select(uint8_t nodeId, uint8_t channel);

	/// Assert (level == LOW) or deassert the given channel's CS.
	void writeCs(uint8_t nodeId, uint8_t channel, uint8_t level);

	/// Read a node's identity block. Used at startup to catch mis-flashed ids.
	bool probe(uint8_t nodeId);

	/// Switch one node's sensor VCC pass MOSFET.
	bool setSensorPower(uint8_t nodeId, bool on);

	/// Broadcast: every node gates its sensor at once.
	bool setAllSensorPower(bool on);

	/// Bring sensors online one at a time, in node order, settling between each.
	/// Called by init(); exposed so a fault can be re-run without a reboot.
	void stageSensorPowerUp();

	void disarmAll();

	[[nodiscard]] std::string toString() const;

private:
	bool writeFrame(ATTinyCS::Command command, uint8_t target, uint8_t value);
	void swapIn();

	uint8_t m_sclPin;
	uint8_t m_sdaPin;
	uint8_t m_baseAddress;
	int8_t m_strobePin;

	/// What we believe is armed, packed as packTarget(nodeId, channel). Invalidated on
	/// any I2C failure, because acting on a stale belief here means silently talking to
	/// the wrong sensor.
	uint8_t m_armedTarget = 0;

	/// Bit n set when node n answered the identity probe during init().
	uint16_t m_presentNodes = 0;

	bool m_addressValid = false;

	Logging::Logger m_Logger = Logging::Logger("ATTinyCS");
};

/**
 * Looks like an ordinary chip-select pin to SPIImpl, but the pin lives on a remote
 * ATtiny.
 */
/**
 * A chain node hosting an **I2C** sensor rather than an SPI one.
 *
 * The node gates its sensor's SCL: unarmed, the sensor sees SCL held low and cannot
 * even detect a START, so it is electrically absent from the bus. Arming passes SCL
 * through.
 *
 * The consequence worth understanding: chained I2C sensors do **not** consume bus
 * addresses. Six ICM-45686s all answering at 0x68 coexist happily, because only one is
 * listening at a time. Address collisions between chained sensors are impossible by
 * construction, and only the node controller's own address has to be unique - which is
 * why one whitelisted address is enough for the whole chain. See DEC-016.
 */
class ATTinyCSWireInterface : public SensorInterface {
public:
	ATTinyCSWireInterface(
		ATTinyCSBus* bus,
		uint8_t nodeId,
		uint8_t channel = ATTinyCS::DefaultChannel
	)
		: m_bus(bus)
		, m_nodeId(nodeId)
		, m_channel(channel) {}

	bool init() final;
	void swapIn() final;

	[[nodiscard]] std::string toString() const final {
		using namespace std::string_literals;
		return "I2SPIWire(node "s + std::to_string(m_nodeId) + ", ch "
			 + std::to_string(m_channel) + ")";
	}

	[[nodiscard]] bool isNodePresent() const;

private:
	ATTinyCSBus* m_bus;
	uint8_t m_nodeId;
	uint8_t m_channel;
};

/**
 * Looks like an ordinary chip-select pin to SPIImpl, but the pin lives on a remote
 * ATtiny.
 */
class ATTinyCSPinInterface : public PinInterface {
public:
	ATTinyCSPinInterface(
		ATTinyCSBus* bus,
		uint8_t nodeId,
		uint8_t channel = ATTinyCS::DefaultChannel
	)
		: m_bus(bus)
		, m_nodeId(nodeId)
		, m_channel(channel) {}

	bool init() override final;
	[[nodiscard]] bool isPresent() const override final;
	int digitalRead() override final;
	void pinMode(uint8_t mode) override final;
	void digitalWrite(uint8_t val) override final;

	[[nodiscard]] std::string toString() const final {
		using namespace std::string_literals;
		return "ATTinyCS(node "s + std::to_string(m_nodeId) + ", ch "
			 + std::to_string(m_channel) + ")";
	}

private:
	ATTinyCSBus* m_bus;
	uint8_t m_nodeId;
	uint8_t m_channel;
	uint8_t m_lastLevel = HIGH;
};

}  // namespace SlimeVR

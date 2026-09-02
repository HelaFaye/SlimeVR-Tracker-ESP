/*
	SlimeVR Code is placed under the MIT license
	Copyright (c) 2025 Eiren Rain & SlimeVR Contributors

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

#include <PinInterface.h>
#include <SPI.h>

#include <cstdint>
#include <cstring>

#include "../logging/Logger.h"
#include "DirectSPIInterface.h"
#include "RegisterInterface.h"

#define ICM_READ_FLAG 0x80

namespace SlimeVR::Sensors {

struct SPIImpl : public RegisterInterface {
	SPIImpl(DirectSPIInterface* spi, PinInterface* csPin)
		: m_spi(spi)
		, m_csPin(csPin) {
		// Either may be null if its interface failed to initialise. Report it once and
		// stay inert: every register accessor below is gated on isUsable(), so an
		// unusable instance is inert rather than a null dereference waiting for a
		// caller that skips the hasSensorOnBus() check.
		if (!isUsable()) {
			m_Logger.error("SPI interface unavailable, sensor will be skipped");
			return;
		}

		auto& spiSettings = spi->getSpiSettings();
		m_Logger.info(
			"SPI settings: clock: %d, bit order: 0x%02X, data mode: 0x%02X",
			spiSettings._clock,
			spiSettings._bitOrder,
			spiSettings._dataMode
		);
		csPin->pinMode(OUTPUT);
		csPin->digitalWrite(HIGH);
	}

	uint8_t readReg(uint8_t regAddr) const override {
		if (!isUsable()) {
			return 0;
		}
		m_spi->beginTransaction(m_csPin);

		m_spi->transfer(regAddr | ICM_READ_FLAG);
		uint8_t buffer = m_spi->transfer(0);

		m_spi->endTransaction(m_csPin);

		return buffer;
	}

	uint16_t readReg16(uint8_t regAddr) const override {
		if (!isUsable()) {
			return 0;
		}
		m_spi->beginTransaction(m_csPin);

		m_spi->transfer(regAddr | ICM_READ_FLAG);
		uint8_t b1 = m_spi->transfer(0);
		uint8_t b2 = m_spi->transfer(0);

		m_spi->endTransaction(m_csPin);
		return b2 << 8 | b1;
	}

	void writeReg(uint8_t regAddr, uint8_t value) const override {
		if (!isUsable()) {
			return;
		}
		m_spi->beginTransaction(m_csPin);

		m_spi->transfer(regAddr);
		m_spi->transfer(value);

		m_spi->endTransaction(m_csPin);
	}

	void writeReg16(uint8_t regAddr, uint16_t value) const override {
		if (!isUsable()) {
			return;
		}
		m_spi->beginTransaction(m_csPin);

		m_spi->transfer(regAddr);
		m_spi->transfer(value & 0xFF);
		m_spi->transfer(value >> 8);

		m_spi->endTransaction(m_csPin);
	}

	void readBytes(uint8_t regAddr, uint8_t size, uint8_t* buffer) const override {
		if (!isUsable()) {
			// Leaving the caller's buffer untouched would hand it stack garbage that
			// looks like sensor data.
			std::memset(buffer, 0, size);
			return;
		}
		m_spi->beginTransaction(m_csPin);

		m_spi->transfer(regAddr | ICM_READ_FLAG);
		for (uint8_t i = 0; i < size; ++i) {
			buffer[i] = m_spi->transfer(0);
		}

		m_spi->endTransaction(m_csPin);
	}

	void writeBytes(uint8_t regAddr, uint8_t size, uint8_t* buffer) const override {
		if (!isUsable()) {
			return;
		}
		m_spi->beginTransaction(m_csPin);

		m_spi->transfer(regAddr);
		for (uint8_t i = 0; i < size; ++i) {
			m_spi->transfer(buffer[i]);
		}

		m_spi->endTransaction(m_csPin);
	}

	bool hasSensorOnBus() override {
		if (!isUsable()) {
			return false;
		}

		// SPI has no addressing and no ACK, so the bus itself cannot tell us whether a
		// sensor is out there - that is what the driver's checkPresent() is for.
		//
		// Do NOT try to infer presence by reading low registers and looking for a stuck
		// 0x00/0xFF: on the ICM-45686 registers 0x00-0x0b are accel and gyro data and
		// WHO_AM_I lives at 0x72, so a healthy sensor that has not been configured yet
		// reads back all zeros and would be rejected as missing.
		//
		// What we can answer is whether the chip select is actually reachable. For a
		// local pin that is always true; for a remote ATtiny node it is false when the
		// node never answered, which is the case worth catching early.
		return m_csPin->isPresent();
	}

	uint8_t getAddress() const override { return 0; }

	std::string toString() const override {
		// Include the chip select, otherwise every SPI sensor on a multi-drop
		// bus reports an identical, useless "SPI" in the setup logs.
		if (m_csPin == nullptr) {
			return std::string("SPI");
		}
		return "SPI(" + m_csPin->toString() + ")";
	}

private:
	// True when both the bus and the chip select line came up successfully.
	bool isUsable() const { return m_spi != nullptr && m_csPin != nullptr; }

	DirectSPIInterface* m_spi;
	PinInterface* m_csPin;
	SlimeVR::Logging::Logger m_Logger = SlimeVR::Logging::Logger("SPI");
};

}  // namespace SlimeVR::Sensors

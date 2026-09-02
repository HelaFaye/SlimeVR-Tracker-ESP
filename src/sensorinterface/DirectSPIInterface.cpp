/*
	SlimeVR Code is placed under the MIT license
	Copyright (c) 2025 Gorbit99 & SlimeVR Contributors

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

#include "DirectSPIInterface.h"

#include <Arduino.h>
#include <PinInterface.h>

namespace SlimeVR {

DirectSPIInterface::DirectSPIInterface(
	SPIClass* spiClass,
	SPISettings spiSettings,
	int8_t sck,
	int8_t miso,
	int8_t mosi
)
	: m_spiClass{spiClass}
	, m_spiSettings{spiSettings}
	, m_sck{sck}
	, m_miso{miso}
	, m_mosi{mosi} {}

bool DirectSPIInterface::init() {
	if (m_spiClass == nullptr) {
		return false;
	}

#ifdef ESP32
	// -1 tells the ESP32 core to keep the default pin for that signal, which is exactly
	// the semantics we want for PinDefault. ss is always -1: chip select is owned by a
	// PinInterface (possibly a remote one), never by the SPI driver.
	m_spiClass->begin(m_sck, m_miso, m_mosi, -1);
#else
	// ESP8266's SPIClass has fixed HSPI pins and a no-argument begin().
	m_spiClass->begin();
#endif
	return true;
}

void DirectSPIInterface::swapIn() {}

void DirectSPIInterface::beginTransaction(PinInterface* csPin) {
	m_spiClass->beginTransaction(m_spiSettings);
	csPin->digitalWrite(LOW);
}

void DirectSPIInterface::endTransaction(PinInterface* csPin) {
	csPin->digitalWrite(HIGH);
	m_spiClass->endTransaction();
}

std::string DirectSPIInterface::toString() const {
	using namespace std::string_literals;

	if (m_sck == PinDefault && m_miso == PinDefault && m_mosi == PinDefault) {
		return "SPI"s;
	}

	return "SPI("s + std::to_string(m_sck) + ", " + std::to_string(m_miso) + ", "
		 + std::to_string(m_mosi) + ")";
}

const SPISettings& DirectSPIInterface::getSpiSettings() { return m_spiSettings; }

}  // namespace SlimeVR

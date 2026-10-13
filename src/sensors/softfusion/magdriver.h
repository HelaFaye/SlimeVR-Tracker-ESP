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

#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <vector>

#include "logging/Logger.h"
#include "sensorinterface/RegisterInterface.h"

namespace SlimeVR::Sensors::SoftFusion {

enum class MagDataWidth {
	SixByte,
	NineByte,
};

/// How the host reaches the magnetometer. Decides which parts are tried during
/// detection and which multi-byte read convention is used.
enum class MagTransport {
	/// Behind the IMU's auxiliary I2C master (ICM-456xx AUX1). Selected per part with
	/// setDeviceId(); the IMU driver does the bus work.
	ImuAux,
	/// On its own SPI chip select, sharing the SPI bus with the IMUs: a host GPIO, or
	/// a channel on an I2SPI chain node.
	Spi,
};

enum class MagByteOrder {
	LittleEndian,
	BigEndian,
};

struct MagInterface {
	MagTransport transport;
	std::function<uint8_t(uint8_t)> readByte;
	std::function<void(uint8_t, uint8_t)> writeByte;
	/// Burst read starting at a register. The caller has already applied the part's
	/// auto-increment flag for this transport.
	std::function<void(uint8_t, uint8_t*, size_t)> readBytes;
	/// Aux only: which I2C device the IMU's master talks to. No-op on SPI.
	std::function<void(uint8_t)> setDeviceId;
};

struct MagDefinition {
	const char* name;

	/// 7-bit I2C address when behind an IMU's aux master; 0 if the part is not
	/// supported there.
	uint8_t deviceId;
	bool supportsSpi;

	uint8_t whoAmIReg;
	uint8_t expectedWhoAmI;

	MagDataWidth dataWidth;
	uint8_t dataReg;
	MagByteOrder byteOrder;
	/// Raw value that means zero field. 0 for signed outputs; parts with unsigned
	/// outputs (MMC5983MA) report 32768 at zero field.
	int32_t zeroOffset;
	/// Field per LSB, in microtesla.
	float resolution;

	/// OR-ed into the register address for a burst read, per transport. ST parts need
	/// an explicit auto-increment bit (0x80 on I2C, 0x40 on SPI); most others
	/// auto-increment on their own.
	uint8_t i2cBurstFlag;
	uint8_t spiBurstFlag;

	std::function<bool(MagInterface& interface)> setup;
};

class MagDriver {
public:
	/// Detect and configure a magnetometer on this transport. Only parts that support
	/// the transport are tried.
	bool init(MagInterface&& interface, bool supports9ByteMags);

	/// Enable or disable sampling. The host polls; nothing on the bus changes.
	void setPollingEnabled(bool enabled);

	/// Call every loop. When enabled and due, reads one sample, scales it to
	/// microtesla and hands it to `onSample`. Polls at a fixed period so the fusion's
	/// mag filter, which is built for one sample period, sees a steady rate. A
	/// magnetometer slower than that period just repeats its last sample.
	void poll(
		uint32_t nowMicros,
		float periodSeconds,
		const std::function<void(const float scaled[3])>& onSample
	);

	[[nodiscard]] const char* getAttachedMagName() const;
	[[nodiscard]] bool isMagAttached() const;

	/// Raw sample bytes -> microtesla, honouring byte order, width and zero offset.
	/// Public and static so it can be tested without hardware.
	static void
	scaleMagSample(const MagDefinition& mag, const uint8_t* raw, float scaled[3]);

	static const std::vector<MagDefinition>& getSupportedMags() {
		return supportedMags;
	}

private:
	std::optional<MagDefinition> detectedMag;
	MagInterface interface;
	bool pollingEnabled = false;
	uint32_t lastPollMicros = 0;

	static std::vector<MagDefinition> supportedMags;

	Logging::Logger logger{"MagDriver"};
};

}  // namespace SlimeVR::Sensors::SoftFusion

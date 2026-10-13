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

#include "magdriver.h"

namespace SlimeVR::Sensors::SoftFusion {

// Register values for the SPI-capable parts were checked against primary sources:
//   MMC5983MA: MEMSIC datasheet Rev A (2019-04-03), registers 09H-0BH and 2FH, SPI
//              protocol on pp. 5-6. Shipped in SparkFun's MMC5983MA library repo.
//   LIS3MDL:   STMicroelectronics lis3mdl-pid (lis3mdl_reg.h/.c) for registers,
//              bitfields and sensitivity; STMems_Standard_C_drivers examples for the
//              SPI/I2C burst flags (SPI read 0xC0, I2C sub-address 0x80).
// QMC6309 and IST8306 resolutions are taken from upstream PR #465.
std::vector<MagDefinition> MagDriver::supportedMags{
	MagDefinition{
		.name = "QMC6309",
		.deviceId = 0x7c,
		.supportsSpi = false,  // I2C only

		.whoAmIReg = 0x00,
		.expectedWhoAmI = 0x90,

		.dataWidth = MagDataWidth::SixByte,
		.dataReg = 0x01,
		.byteOrder = MagByteOrder::LittleEndian,
		.zeroOffset = 0,
		.resolution = 0.025f,
		.i2cBurstFlag = 0,
		.spiBurstFlag = 0,

		.setup =
			[](MagInterface& interface) {
				interface.writeByte(0x0b, 0x80);
				interface.writeByte(0x0b, 0x00);  // Soft reset
				delay(10);
				interface.writeByte(0x0b, 0x48);  // Set/reset on, 8g full range, 200Hz
				interface.writeByte(
					0x0a,
					0x21
				);  // LP filter 2, 8x Oversampling, normal mode
				return true;
			},
	},
	MagDefinition{
		.name = "IST8306",
		.deviceId = 0x19,
		.supportsSpi = false,  // I2C only

		.whoAmIReg = 0x00,
		.expectedWhoAmI = 0x06,

		.dataWidth = MagDataWidth::SixByte,
		.dataReg = 0x11,
		.byteOrder = MagByteOrder::LittleEndian,
		.zeroOffset = 0,
		.resolution = 0.3f,
		.i2cBurstFlag = 0,
		.spiBurstFlag = 0,

		.setup =
			[](MagInterface& interface) {
				interface.writeByte(0x32, 0x01);  // Soft reset
				delay(50);
				interface.writeByte(0x30, 0x20);  // Noise suppression: low
				interface.writeByte(0x41, 0x2d);  // Oversampling: 32X
				interface.writeByte(0x31, 0x02);  // Continuous measurement @ 10Hz
				return true;
			},
	},
	MagDefinition{
		// SPI mode 3 per the datasheet (SCK idles high, data driven on falling edges
		// and captured on rising), the same as the IMUs, so one SPI bus config serves
		// both. Read = 0x80 | address, 6-bit address; bursts auto-increment.
		.name = "MMC5983MA",
		.deviceId = 0x30,
		.supportsSpi = true,

		.whoAmIReg = 0x2f,  // Product ID 1
		.expectedWhoAmI = 0x30,

		// Xout0/Xout1 = Xout[17:10], Xout[9:2]: 16-bit mode, MSB first, unsigned with
		// a null-field output of 32768. 4096 counts/G = 0.0244 uT/count.
		.dataWidth = MagDataWidth::SixByte,
		.dataReg = 0x00,
		.byteOrder = MagByteOrder::BigEndian,
		.zeroOffset = 32768,
		.resolution = 100.0f / 4096.0f,
		.i2cBurstFlag = 0,
		.spiBurstFlag = 0,

		.setup =
			[](MagInterface& interface) {
				interface.writeByte(0x0a, 0x80);  // Control 1: SW_RST
				delay(15);  // Datasheet: power-on time 10 ms after SW_RST
				interface.writeByte(0x0a, 0x00);  // Control 1: BW=00, 100 Hz, 8 ms
				interface.writeByte(0x09, 0x20);  // Control 0: Auto_SR_en
				// Control 2: Cmm_en | Cm_freq=101 (100 Hz continuous measurement)
				interface.writeByte(0x0b, 0x08 | 0x05);
				return true;
			},
	},
	MagDefinition{
		// I2C 0x1C with SA1 low (0x1E with SA1 high: not tried). SPI: read 0x80, burst
		// needs MS (0x40); I2C burst needs 0x80 in the sub-address.
		.name = "LIS3MDL",
		.deviceId = 0x1c,
		.supportsSpi = true,

		.whoAmIReg = 0x0f,
		.expectedWhoAmI = 0x3d,

		// OUT_X_L..OUT_Z_H, signed little-endian. +/-4 gauss: 6842 LSB/G.
		.dataWidth = MagDataWidth::SixByte,
		.dataReg = 0x28,
		.byteOrder = MagByteOrder::LittleEndian,
		.zeroOffset = 0,
		.resolution = 100.0f / 6842.0f,
		.i2cBurstFlag = 0x80,
		.spiBurstFlag = 0x40,

		.setup =
			[](MagInterface& interface) {
				interface.writeByte(0x21, 0x04);  // CTRL_REG2: SOFT_RST
				delay(10);
				interface.writeByte(0x21, 0x00);  // CTRL_REG2: FS = +/-4 gauss
				// CTRL_REG1: OM = high-performance, DO = 80 Hz (LIS3MDL_HP_80Hz,
				// 0x2E in the driver's packed om field, shifted past ST)
				interface.writeByte(0x20, 0x5c);
				interface.writeByte(0x23, 0x08);  // CTRL_REG4: OMZ = high-performance
				interface.writeByte(0x24, 0x40);  // CTRL_REG5: BDU
				interface.writeByte(0x22, 0x00);  // CTRL_REG3: continuous conversion
				return true;
			},
	},
};

bool MagDriver::init(MagInterface&& interface, bool supports9ByteMags) {
	this->interface = std::move(interface);
	auto& bus = this->interface;
	const bool spi = bus.transport == MagTransport::Spi;

	for (auto& mag : supportedMags) {
		if (spi ? !mag.supportsSpi : mag.deviceId == 0) {
			continue;
		}

		if (!spi) {
			bus.setDeviceId(mag.deviceId);
		}

		logger.info("Trying mag %s over %s", mag.name, spi ? "SPI" : "IMU aux");

		uint8_t whoAmI = bus.readByte(mag.whoAmIReg);
		if (whoAmI != mag.expectedWhoAmI) {
			continue;
		}

		if (!supports9ByteMags && mag.dataWidth == MagDataWidth::NineByte) {
			logger.error("The sensor doesn't support this mag!");
			return false;
		}

		logger.info("Found mag %s! Initializing", mag.name);

		if (!mag.setup(bus)) {
			logger.error("Mag %s failed to initialize!", mag.name);
			return false;
		}

		detectedMag = mag;
		break;
	}

	return detectedMag.has_value();
}

void MagDriver::setPollingEnabled(bool enabled) {
	pollingEnabled = enabled && detectedMag.has_value();
	lastPollMicros = micros();
}

bool MagDriver::poll(
	uint32_t nowMicros,
	float periodSeconds,
	const std::function<void(const float scaled[3])>& onSample
) {
	if (!pollingEnabled || !detectedMag) {
		return false;
	}

	const auto period = static_cast<uint32_t>(periodSeconds * 1e6f);
	const uint32_t elapsed = nowMicros - lastPollMicros;
	if (elapsed < period) {
		return false;
	}
	// Keep the cadence steady, but do not try to catch up after a long stall: the
	// fusion only wants the current field.
	lastPollMicros = elapsed > 4 * period ? nowMicros : lastPollMicros + period;

	const uint8_t burstFlag = interface.transport == MagTransport::Spi
								? detectedMag->spiBurstFlag
								: detectedMag->i2cBurstFlag;
	const size_t length = detectedMag->dataWidth == MagDataWidth::SixByte ? 6 : 9;

	uint8_t raw[9] = {};
	if (!interface.readBytes(detectedMag->dataReg | burstFlag, raw, length)) {
		// Do not scale garbage: on parts with a zero offset (MMC5983MA) an all-zero
		// buffer reads as a full-scale field.
		return true;
	}

	float scaled[3];
	scaleMagSample(*detectedMag, raw, scaled);
	onSample(scaled);
	return true;
}

void MagDriver::scaleMagSample(
	const MagDefinition& mag,
	const uint8_t* raw,
	float scaled[3]
) {
	const size_t bytes = mag.dataWidth == MagDataWidth::SixByte ? 2 : 3;

	for (size_t axis = 0; axis < 3; axis++) {
		const uint8_t* p = raw + axis * bytes;

		uint32_t value = 0;
		for (size_t i = 0; i < bytes; i++) {
			const size_t shift = mag.byteOrder == MagByteOrder::LittleEndian
								   ? 8 * i
								   : 8 * (bytes - 1 - i);
			value |= static_cast<uint32_t>(p[i]) << shift;
		}

		int32_t field;
		if (mag.zeroOffset != 0) {
			field = static_cast<int32_t>(value) - mag.zeroOffset;
		} else {
			// Sign-extend from 16 or 24 bits.
			const uint32_t signBit = 1u << (8 * bytes - 1);
			field = static_cast<int32_t>((value ^ signBit))
				  - static_cast<int32_t>(signBit);
		}

		scaled[axis] = static_cast<float>(field) * mag.resolution;
	}
}

const char* MagDriver::getAttachedMagName() const {
	if (!detectedMag) {
		return nullptr;
	}

	return detectedMag->name;
}

bool MagDriver::isMagAttached() const { return detectedMag.has_value(); }

}  // namespace SlimeVR::Sensors::SoftFusion

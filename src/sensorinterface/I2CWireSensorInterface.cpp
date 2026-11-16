/*
	SlimeVR Code is placed under the MIT license
	Copyright (c) 2024 Eiren Rain & SlimeVR Contributors

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

#include "I2CWireSensorInterface.h"

#include <optional>

#ifdef ESP32
#include <driver/gpio.h>
#include <esp_rom_gpio.h>
#include <soc/i2c_periph.h>
#endif

std::optional<uint8_t> activeSCLPin;
std::optional<uint8_t> activeSDAPin;
bool isI2CActive = false;

namespace SlimeVR {
#ifdef ESP32
namespace {
/// Move I2C0 (Wire) to other pins without restarting it: what the legacy driver's
/// i2c_set_pin() does, done here through the GPIO matrix instead. Calling i2c_set_pin()
/// links the legacy I2C driver, and from Arduino-ESP32 3.1 (ESP-IDF 5.3+) Wire uses the
/// new i2c_master driver: ESP-IDF then aborts at start-up, before setup() ("CONFLICT!
/// driver_ng is not allowed to be used with this old driver"), and the board reboots
/// forever. Found by booting the ESP32-S3 build on Arduino-ESP32 3.3 in QEMU.
void routeI2C0(uint8_t sdaPin, uint8_t sclPin) {
	const i2c_signal_conn_t& signals = i2c_periph_signal[0];
	const struct {
		uint8_t pin;
		uint8_t out;
		uint8_t in;
	} lines[] = {
		{sdaPin, signals.sda_out_sig, signals.sda_in_sig},
		{sclPin, signals.scl_out_sig, signals.scl_in_sig},
	};
	for (const auto& line : lines) {
		const auto pin = static_cast<gpio_num_t>(line.pin);
		gpio_set_level(pin, 1);
		esp_rom_gpio_pad_select_gpio(line.pin);
		gpio_set_direction(pin, GPIO_MODE_INPUT_OUTPUT_OD);
		gpio_set_pull_mode(
			pin,
			GPIO_FLOATING
		);  // as i2c_set_pin(..., false, false, ...)
		esp_rom_gpio_connect_out_signal(line.pin, line.out, false, false);
		esp_rom_gpio_connect_in_signal(line.pin, line.in, false);
	}
}
}  // namespace
#endif

void swapI2C(uint8_t sclPin, uint8_t sdaPin) {
	if (sclPin != activeSCLPin || sdaPin != activeSDAPin || !isI2CActive) {
		Wire.flush();
#ifdef ESP32
		if (!isI2CActive) {
			// Reset HWI2C to avoid being affected by I2CBUS reset
			Wire.end();
		}

		// Was `activeSCLPin && activeSCLPin`: with SCL set and SDA unset, the
		// dereference of activeSDAPin below hit an empty optional.
		if (activeSCLPin && activeSDAPin) {
			// Disconnect pins from HWI2C
			gpio_set_direction((gpio_num_t)*activeSCLPin, GPIO_MODE_INPUT);
			gpio_set_direction((gpio_num_t)*activeSDAPin, GPIO_MODE_INPUT);
		}

		if (isI2CActive) {
			routeI2C0(sdaPin, sclPin);
		} else {
			Wire.begin(static_cast<int>(sdaPin), static_cast<int>(sclPin), I2C_SPEED);
			Wire.setTimeOut(150);
		}
#else
		Wire.begin(static_cast<int>(sdaPin), static_cast<int>(sclPin));
#endif

		activeSCLPin = sclPin;
		activeSDAPin = sdaPin;
		isI2CActive = true;
	}
}

void disconnectI2C() {
	Wire.flush();
	isI2CActive = false;
#ifdef ESP32
	Wire.end();
#endif
}
}  // namespace SlimeVR

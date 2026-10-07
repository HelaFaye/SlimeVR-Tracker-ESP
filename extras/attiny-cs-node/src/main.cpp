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

/*
 * Chip-select node for a SlimeVR RJ45 SPI sensor chain.
 *
 * One of these sits next to each remote IMU. It owns nothing but the IMU's CS line:
 * SCK, MOSI and MISO run straight past it from the cable to the sensor, so a wedged
 * node can fail to select but can never corrupt SPI data.
 *
 * When armed, CCL routes the shared CS_STROBE conductor to the local CS pin in
 * hardware. That is the whole point of the design - see docs/dev/DECISIONS.md DEC-004.
 * No interrupt handler is in the CS path, so framing an SPI transaction costs the host
 * one GPIO toggle instead of an I2C round trip.
 */

#include <Arduino.h>
#include <Wire.h>

#ifndef EXTERNAL_CS_GATE
// megaTinyCore only. The gate variant deliberately builds on cores that have neither.
#include <Event.h>
#include <Logic.h>
#endif

// megaTinyCore and ATTinyCore provide digitalWriteFast as a *function*, so an
// `#ifndef digitalWriteFast` guard cannot detect it - the guard always fires and
// silently aliases to something that may not exist. Select explicitly instead.
#ifdef NO_DIGITAL_WRITE_FAST
#define nodeWrite digitalWrite
#else
#define nodeWrite digitalWriteFast
#endif

#include "ATTinyCSProtocol.h"

using namespace SlimeVR::ATTinyCS;

// Protocol v3: one I2C address for the whole chain, every frame exactly three bytes
// (opcode, target, value). Dual-address TWI is no longer needed, which is what widens
// the node MCU choice beyond parts with a second-address register. See DEC-015.

#ifndef NODE_ID
#error "Build with -DNODE_ID=n (1..15). Each node board needs its own image."
#endif

#if NODE_ID < 1 || NODE_ID > 15
#error "NODE_ID must be between 1 and 15"
#endif

// A node may own more than one chip select. Channel 0 uses the pins below; further
// channels need one output pin and one gate each, so multi-channel requires the
// external gate build - there is only one usable CCL output on an 8-pin tinyAVR.
#ifndef NUM_CHANNELS
#define NUM_CHANNELS 1
#endif

#if NUM_CHANNELS > 1 && !defined(EXTERNAL_CS_GATE)
#error "NUM_CHANNELS > 1 requires -DEXTERNAL_CS_GATE (one OR gate per channel)"
#endif

#if NUM_CHANNELS < 1 || NUM_CHANNELS > 16
#error "NUM_CHANNELS must be between 1 and 16"
#endif

// Which channels gate a sensor's SCL rather than its chip select, as a bitmask.
// Bit n set = channel n carries an I2C sensor.
//
// The gating logic is identical either way; only the idle level and the external gate
// differ, because the two buses idle at opposite levels:
//
//   SPI chip select  idles HIGH  ->  CS  = CS_STROBE OR ARMED_N   (74LVC1G32)
//   I2C clock        idles LOW   ->  SCL = CHAIN_SCL AND ARMED    (74LVC1G08)
//
// Gating SCL low is deliberate: an I2C slave detects START as SDA falling while SCL is
// high, so a sensor whose clock is held low cannot see a START at all and is
// electrically absent from the bus. See docs/dev/DECISIONS.md DEC-016.
#ifndef I2C_CHANNELS
#define I2C_CHANNELS 0
#endif

#if I2C_CHANNELS != 0 && !defined(EXTERNAL_CS_GATE)
#error "I2C_CHANNELS requires -DEXTERNAL_CS_GATE (an AND gate per I2C channel)"
#endif

constexpr bool channelIsI2C(uint8_t channel) { return (I2C_CHANNELS >> channel) & 1; }

// The chain address comes from ATTinyCSProtocol.h, shared with the tracker. Override
// with -DBASE_ADDRESS only for a second chain on the same I2C bus, and then use an
// address from AddressWhitelist and set the matching baseAddress in
// board-defaults.json.
#ifndef BASE_ADDRESS
#define BASE_ADDRESS DefaultBaseAddress
#endif

// PA6 in, PA7 out is not a free choice in the default build: on an 8-pin tinyAVR the
// only CCL output that exists is LUT0's alternate output on PA7, and PA1/PA2 are taken
// by TWI.
#ifndef EXTERNAL_CS_GATE
constexpr uint8_t PinStrobe = PIN_PA6;
constexpr uint8_t PinChipSelect = PIN_PA7;
constexpr uint8_t PinSensorPower = PIN_PA3;  // gate of the VCC pass MOSFET
#endif

#ifdef EXTERNAL_CS_GATE
// The gate variant runs on parts with a different pin map entirely (ATtiny85 has
// PB0..PB5 and no PIN_PAn names), so these are plain pin numbers, overridable per
// board.
#ifndef PIN_ARMED_N
#define PIN_ARMED_N 1
#endif
#ifndef PIN_SENSOR_POWER
#define PIN_SENSOR_POWER 3
#endif
constexpr uint8_t PinChipSelect = PIN_ARMED_N;  // named for the shared code paths
constexpr uint8_t PinSensorPower = PIN_SENSOR_POWER;
/*
 * Build variant for parts without CCL (ATtiny85 and friends).
 *
 * An external single-gate OR does the job the CCL was doing:
 *
 *     CS = CS_STROBE OR ARMED_N
 *
 * When this node is not armed it holds ARMED_N high, which forces CS high no matter
 * what the strobe does. When armed it holds ARMED_N low and CS follows the strobe,
 * exactly as the CCL pass-through did - combinationally, with no CPU in the path.
 *
 * Software-CS mode degenerates correctly for free: with the host parking the strobe
 * low, CS == ARMED_N, so driving ARMED_N over I2C *is* driving CS.
 *
 * Costs one 74LVC1G32 (SOT-353, a couple of cents). Buys second-sourcing on the node
 * MCU. The tracker firmware cannot tell the two variants apart.
 */
constexpr uint8_t PinArmedN = PIN_ARMED_N;
#endif

namespace {

bool armed = false;
uint8_t armedChannel = 0;
bool answersRead = false;
CsMode csMode = CsMode::Strobe;
bool sensorPowered = SensorPowerDefaultOn;
bool sensorHeldInReset = false;

uint8_t identity[IdentityLength];

/// Drives the P-channel pass MOSFET gating the sensor's 3V3.
///
/// P-channel high-side: gate LOW turns the FET ON. Inverted deliberately - if the
/// ATtiny is unprogrammed, held in reset, or has not reached setup() yet, its pins are
/// inputs and the pull-up on the gate holds the sensor OFF. Failing to a de-energised
/// sensor is the safe direction: an unpowered IMU cannot drive MISO and cannot fight
/// the bus.
void applySensorPower() { nodeWrite(PinSensorPower, sensorPowered ? LOW : HIGH); }

void updateIdentity() {
	uint8_t status = 0;
	if (armed) {
		status |= StatusArmed;
	}
	if (csMode == CsMode::Strobe) {
		status |= StatusStrobeMode;
	}
	if (sensorPowered) {
		status |= StatusSensorPowered;
	}
	if (sensorHeldInReset) {
		status |= StatusSensorHeldInReset;
	}

	identity[0] = IdentityMagic;
	identity[1] = ProtocolVersion;
	identity[2] = NODE_ID;
	identity[3] = status;
}

#ifdef EXTERNAL_CS_GATE

// One ARMED_N line per channel, each feeding its own OR gate. Override per board.
#ifndef ARMED_N_PINS
#define ARMED_N_PINS \
	{ PIN_ARMED_N }
#endif
constexpr uint8_t ChannelPins[NUM_CHANNELS] = ARMED_N_PINS;

/// The level that leaves a channel's sensor deselected.
constexpr uint8_t idleLevel(uint8_t channel) {
	// ARMED_N feeds an OR gate for chip select (idle high = CS forced high); ARMED
	// feeds an AND gate for I2C (idle low = clock held low).
	return channelIsI2C(channel) ? LOW : HIGH;
}

/// The level that lets a channel's sensor through.
constexpr uint8_t activeLevel(uint8_t channel) {
	return channelIsI2C(channel) ? HIGH : LOW;
}

void writeChannel(uint8_t channel, uint8_t level) {
	if (channel < NUM_CHANNELS) {
		nodeWrite(ChannelPins[channel], level);
	}
}

void setupStrobePassthrough() {
	// Nothing to configure: the OR gate is the pass-through. The strobe pin isn't even
	// read by this MCU.
}

void applyArmedState() {
	// Armed pulls ARMED_N low so the gate lets the strobe through; disarmed forces CS
	// high. In software mode the host parks the strobe low, so this same line is CS.
	for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
		nodeWrite(
			ChannelPins[i],
			(armed && i == armedChannel) ? activeLevel(i) : idleLevel(i)
		);
	}
}

#else

void setupStrobePassthrough() {
	// LUT1's direct pin inputs live on PORTC, which an 8-pin package does not have, so
	// the strobe reaches the LUT through the event system instead.
	Event0.set_generator(gen0::pin_pa6);
	Event0.set_user(user::ccl1_event_a);
	Event0.start();

	Logic1.enable = true;
	Logic1.input0 = logic::in::event_a;
	Logic1.input1 = logic::in::masked;
	Logic1.input2 = logic::in::masked;
	// Truth table: output follows input0. Bit n of the table is the output for input
	// combination n, so 0b00000010 means "high only when in0 is high".
	Logic1.truth = 0b00000010;
	Logic1.output = logic::out::disable;  // port keeps the pin until we arm
	Logic1.init();

	Logic::start();
}

void applyArmedState() {
	if (armed && csMode == CsMode::Strobe) {
		Logic1.output = logic::out::enable;
		Logic1.init();
		return;
	}

	// Not armed, or armed in software mode: the CCL lets go and the port drives CS.
	Logic1.output = logic::out::disable;
	Logic1.init();

	if (!armed) {
		nodeWrite(PinChipSelect, HIGH);
	}
}

void writeChannel(uint8_t channel, uint8_t level) {
	// The CCL build is single-channel by construction (see the NUM_CHANNELS guard).
	if (channel == 0) {
		nodeWrite(PinChipSelect, level);
	}
}

#endif  // EXTERNAL_CS_GATE

void handleFrame(uint8_t opcode, uint8_t target, uint8_t value) {
	const bool forUs = unpackNodeId(target) == NODE_ID;

	switch (static_cast<Command>(opcode)) {
		case Command::Arm: {
			// One-hot by construction: every node sees the same frame, so there is no
			// window in which two are armed and two sensors drive the bus.
			const uint8_t wantChannel = unpackChannel(target);
			armed = forUs && (wantChannel < NUM_CHANNELS);
			armedChannel = armed ? wantChannel : 0;
			applyArmedState();
			break;
		}

		case Command::DisarmAll:
			armed = false;
			armedChannel = 0;
			applyArmedState();
			break;

		case Command::PowerAll:
			sensorPowered = value != 0;
			applySensorPower();
			break;

		case Command::ResetAll:
			armed = false;
			armedChannel = 0;
			answersRead = false;
			csMode = CsMode::Strobe;
			sensorPowered = SensorPowerDefaultOn;
			sensorHeldInReset = false;
			applySensorPower();
			applyArmedState();
			break;

		case Command::SetCs: {
			if (!forUs || !armed || csMode != CsMode::Software) {
				return;
			}
			// Refuse a channel we are not armed on, so a stale frame cannot drive a
			// chip select out from under the host.
			const uint8_t channel = unpackChannel(target);
			if (channel != armedChannel || channelIsI2C(channel)) {
				// An I2C channel has no software-CS analogue: its clock either passes
				// or it does not, and that is what arming already controls.
				return;
			}
			writeChannel(channel, value ? HIGH : LOW);
			break;
		}

		case Command::SetMode:
			if (!forUs) {
				return;
			}
			csMode = value == 0 ? CsMode::Software : CsMode::Strobe;
			applyArmedState();
			break;

		case Command::SetSensorPower:
			if (!forUs) {
				return;
			}
			sensorPowered = value != 0;
			applySensorPower();
			break;

		case Command::SetSensorReset:
			// Cutting the rail is this board's reset: stronger than the sensor's own,
			// and it costs no extra pin.
			if (!forUs) {
				return;
			}
			sensorHeldInReset = value != 0;
			sensorPowered = !sensorHeldInReset;
			applySensorPower();
			break;

		case Command::Identify:
			// One-hot again: only the addressed node answers the next read, so two
			// nodes can never drive SDA together.
			answersRead = forUs;
			break;

		default:
			break;
	}

	updateIdentity();
}

void onReceive(int count) {
	// v3 frames are exactly three bytes. Anything else is a v1/v2 host, or noise.
	if (count != FrameLength) {
		while (Wire.available()) {
			Wire.read();
		}
		return;
	}

	const uint8_t opcode = Wire.read();
	const uint8_t target = Wire.read();
	const uint8_t value = Wire.read();
	handleFrame(opcode, target, value);
}

void onRequest() {
	// Silence unless the last Identify selected us. Without this every node would drive
	// SDA on the host's read.
	if (!answersRead) {
		return;
	}
	Wire.write(identity, IdentityLength);
}

}  // namespace

void setup() {
	// CS high before anything else. A node that powers up asserting CS would fight
	// whatever the host is already talking to.
#ifdef EXTERNAL_CS_GATE
	for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
		// Idle before the pin becomes an output, so there is no glimpse of a selected
		// sensor while the port direction changes.
		nodeWrite(ChannelPins[i], idleLevel(i));
		pinMode(ChannelPins[i], OUTPUT);
		nodeWrite(ChannelPins[i], idleLevel(i));
	}
#else
	pinMode(PinChipSelect, OUTPUT);
	nodeWrite(PinChipSelect, HIGH);
#endif

#ifndef EXTERNAL_CS_GATE
	pinMode(PinStrobe, INPUT);
#endif

	// Gate high = FET off = sensor unpowered. Set before the pin becomes an output so
	// there is no glimpse of an enabled rail.
	nodeWrite(PinSensorPower, HIGH);
	pinMode(PinSensorPower, OUTPUT);
	applySensorPower();

	setupStrobePassthrough();
	updateIdentity();

	Wire.onReceive(onReceive);
	Wire.onRequest(onRequest);

	// One address for the whole chain. v2 needed a second, per-node address and relied
	// on megaTinyCore's dual-address support; v3 does not, which removes both that
	// dependency and the need for 16 consecutive free addresses on the bus.
	Wire.begin(BASE_ADDRESS);
}

void loop() {
	// Everything happens in the TWI interrupt and in the CCL. Nothing to do here, and
	// deliberately no sleep: waking costs microseconds we would pay on every select.
}

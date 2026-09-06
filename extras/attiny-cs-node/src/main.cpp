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

#ifndef digitalWriteFast
// ATTinyCore and megaTinyCore both provide this; plain avr-gcc cores may not.
#define digitalWriteFast digitalWrite
#endif

#include "ATTinyCSProtocol.h"

using namespace SlimeVR::ATTinyCS;

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

#ifndef BASE_ADDRESS
#define BASE_ADDRESS 0x30
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
void applySensorPower() {
	digitalWriteFast(PinSensorPower, sensorPowered ? LOW : HIGH);
}

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

void writeChannel(uint8_t channel, uint8_t level) {
	if (channel < NUM_CHANNELS) {
		digitalWriteFast(ChannelPins[channel], level);
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
		digitalWriteFast(ChannelPins[i], (armed && i == armedChannel) ? LOW : HIGH);
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
		digitalWriteFast(PinChipSelect, HIGH);
	}
}

void writeChannel(uint8_t channel, uint8_t level) {
	// The CCL build is single-channel by construction (see the NUM_CHANNELS guard).
	if (channel == 0) {
		digitalWriteFast(PinChipSelect, level);
	}
}

#endif  // EXTERNAL_CS_GATE

void handleChainCommand(uint8_t opcode, uint8_t payload, bool hasPayload) {
	switch (static_cast<ChainCommand>(opcode)) {
		case ChainCommand::Arm:
			if (!hasPayload) {
				return;
			}
			// One-hot by construction: every node sees the same broadcast, so there is
			// no window in which two nodes are armed and two IMUs drive MISO.
			{
				const uint8_t wantNode = unpackNodeId(payload);
				const uint8_t wantChannel = unpackChannel(payload);

				armed = (wantNode == NODE_ID) && (wantChannel < NUM_CHANNELS);
				armedChannel = armed ? wantChannel : 0;
			}
			applyArmedState();
			break;

		case ChainCommand::PowerAll:
			if (!hasPayload) {
				return;
			}
			sensorPowered = payload != 0;
			applySensorPower();
			break;

		case ChainCommand::DisarmAll:
			armed = false;
			armedChannel = 0;
			applyArmedState();
			break;

		case ChainCommand::ResetAll:
			armed = false;
			armedChannel = 0;
			csMode = CsMode::Strobe;
			sensorPowered = SensorPowerDefaultOn;
			sensorHeldInReset = false;
			applySensorPower();
			applyArmedState();
			break;

		default:
			break;
	}

	updateIdentity();
}

void handleNodeCommand(uint8_t opcode, uint8_t payload, bool hasPayload) {
	switch (static_cast<NodeCommand>(opcode)) {
		case NodeCommand::SetCs: {
			if (!hasPayload || !armed || csMode != CsMode::Software) {
				return;
			}
			// Payload is (channel << 4) | level. Refuse a channel we are not armed on,
			// so a stale command cannot drive a chip select out from under the host.
			const uint8_t channel = (payload >> 4) & 0x0F;
			const uint8_t level = (payload & 0x01) ? HIGH : LOW;
			if (channel != armedChannel) {
				return;
			}
			writeChannel(channel, level);
			break;
		}

		case NodeCommand::SetMode:
			if (!hasPayload) {
				return;
			}
			csMode = payload == 0 ? CsMode::Software : CsMode::Strobe;
			applyArmedState();
			break;

		case NodeCommand::SetSensorPower:
			if (!hasPayload) {
				return;
			}
			sensorPowered = payload != 0;
			applySensorPower();
			break;

		case NodeCommand::SetSensorReset:
			// Cutting the rail is this board's reset: there is no separate reset pin,
			// and a power cycle is a stronger reset than the sensor's own anyway.
			if (!hasPayload) {
				return;
			}
			sensorHeldInReset = payload != 0;
			sensorPowered = !sensorHeldInReset;
			applySensorPower();
			break;

		case NodeCommand::Identify:
			break;  // the identity block is always what a read returns

		default:
			break;
	}

	updateIdentity();
}

void onReceive(int count) {
	if (count < 1) {
		return;
	}

	const uint8_t opcode = Wire.read();
	uint8_t payload = 0;
	const bool hasPayload = count > 1;
	if (hasPayload) {
		payload = Wire.read();
	}

	while (Wire.available()) {
		Wire.read();
	}

	// The node listens on two addresses but the core doesn't report which one was
	// matched, so the chain and unicast opcode spaces are deliberately disjoint. See
	// docs/dev/ATTINY-CS-PROTOCOL.md.
	if (opcode < 0x10) {
		handleChainCommand(opcode, payload, hasPayload);
	} else if (opcode == static_cast<uint8_t>(ChainCommand::ResetAll)) {
		handleChainCommand(opcode, payload, hasPayload);
	} else {
		handleNodeCommand(opcode, payload, hasPayload);
	}
}

void onRequest() { Wire.write(identity, IdentityLength); }

}  // namespace

void setup() {
	// CS high before anything else. A node that powers up asserting CS would fight
	// whatever the host is already talking to.
#ifdef EXTERNAL_CS_GATE
	for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
		pinMode(ChannelPins[i], OUTPUT);
		digitalWriteFast(ChannelPins[i], HIGH);
	}
#else
	pinMode(PinChipSelect, OUTPUT);
	digitalWriteFast(PinChipSelect, HIGH);
#endif

#ifndef EXTERNAL_CS_GATE
	pinMode(PinStrobe, INPUT);
#endif

	// Gate high = FET off = sensor unpowered. Set before the pin becomes an output so
	// there is no glimpse of an enabled rail.
	digitalWriteFast(PinSensorPower, HIGH);
	pinMode(PinSensorPower, OUTPUT);
	applySensorPower();

	setupStrobePassthrough();
	updateIdentity();

	Wire.onReceive(onReceive);
	Wire.onRequest(onRequest);

	// megaTinyCore's second_address argument doubles as an address mask; setting bit 0
	// says "treat this as a second address" rather than as a mask.
	Wire.begin(BASE_ADDRESS, false, ((BASE_ADDRESS + NODE_ID) << 1) | 0x01);
}

void loop() {
	// Everything happens in the TWI interrupt and in the CCL. Nothing to do here, and
	// deliberately no sleep: waking costs microseconds we would pay on every select.
}

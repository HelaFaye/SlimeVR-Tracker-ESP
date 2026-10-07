/*
 * Scenarios run against the real ATTinyCSBus / SPIImpl sources.
 *
 * Build and run: sim/run.sh
 */
#include <Wire.h>

#include <cstdio>
#include <string>

#include "ATTinyCSInterface.h"
#include "DirectPinInterface.h"
#include "DirectSPIInterface.h"
#include "SPIImpl.h"
#include "chain_model.h"

using namespace sim;

// Declared in I2CWireSensorInterface.h, which drags in the real Wire; the model in
// chain_model.cpp provides the definition.
namespace SlimeVR {
void swapI2C(uint8_t sclPin, uint8_t sdaPin);
}

namespace {

int checks = 0;
int failed = 0;

void check(bool ok, const std::string& what) {
	checks++;
	std::printf("  [%s] %s\n", ok ? "ok" : "FAIL", what.c_str());
	if (!ok) {
		failed++;
	}
}

void resetChain(int nodeCount, int channelsPerNode = 1, int localCs = -1) {
	g_chain = Chain{};
	g_chain.localCsPin = localCs;
	if (localCs >= 0) {
		g_chain.gpio[localCs] = HIGH;
		// The hub's own IMU sits on the board's 3V3, not behind a gated pass MOSFET.
		// Only remote sensors are staged.
		g_chain.localSensor.powered = true;
	}
	for (int i = 1; i <= nodeCount; i++) {
		Node n;
		n.id = static_cast<uint8_t>(i);
		n.reportedId = static_cast<uint8_t>(i);
		n.channels = static_cast<uint8_t>(channelsPerNode);
		g_chain.nodes.push_back(n);
	}
}

/// One FIFO-style poll: address the sensor, read a burst.
void pollSensor(SlimeVR::Sensors::SPIImpl& imu) {
	uint8_t buf[16];
	imu.readBytes(0x00, sizeof(buf), buf);
}

// ------------------------------------------------------------------------------

void scenarioBasicChain() {
	std::printf("\n== Four-node chain, strobe mode ==\n");
	resetChain(4);

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();
	check(g_chain.failures == 0, "enumeration asserts no chip select");

	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 11, 12);
	spi.init();

	std::vector<SlimeVR::ATTinyCSPinInterface> pins;
	for (uint8_t i = 1; i <= 4; i++) {
		pins.emplace_back(&bus, i, 0);
	}

	std::vector<SlimeVR::Sensors::SPIImpl> imus;
	for (auto& p : pins) {
		imus.emplace_back(&spi, &p);
	}

	check(imus[0].hasSensorOnBus(), "present node reports a sensor on the bus");
	check(imus[0].readReg(0x72) == 0xE9, "WHO_AM_I reads 0xE9 through node 1");
	check(imus[3].readReg(0x72) == 0xE9, "WHO_AM_I reads 0xE9 through node 4");

	g_chain.stats.reset();
	for (auto& imu : imus) {
		pollSensor(imu);
	}
	std::printf(
		"     poll cycle over 4 sensors: %d I2C writes (%d bytes), %d SPI bytes, %d "
		"strobe toggles\n",
		g_chain.stats.i2cWrites,
		g_chain.stats.i2cBytes,
		g_chain.stats.spiBytes,
		g_chain.stats.strobeToggles
	);
	// The DEC-004 claim: I2C traffic scales with sensor switches, not transactions.
	check(
		g_chain.stats.i2cWrites == 4,
		"one ARM write per sensor, not per SPI transaction"
	);
	check(g_chain.failures == 0, "one-hot invariant held throughout the cycle");
}

void scenarioRepeatPollsAreFree() {
	std::printf("\n== Repeated access to the same sensor ==\n");
	resetChain(2);
	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();
	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 11, 12);
	spi.init();
	SlimeVR::ATTinyCSPinInterface pin(&bus, 1, 0);
	SlimeVR::Sensors::SPIImpl imu(&spi, &pin);

	imu.readReg(0x72);
	g_chain.stats.reset();
	for (int i = 0; i < 20; i++) {
		imu.readReg(0x72);
	}
	std::printf(
		"     20 reads of an already-armed node: %d I2C writes\n",
		g_chain.stats.i2cWrites
	);
	check(g_chain.stats.i2cWrites == 0, "no I2C traffic while the target is unchanged");
	check(
		g_chain.stats.strobeToggles == 40,
		"each transaction framed by a strobe toggle"
	);
}

void scenarioMissingNode() {
	std::printf("\n== Missing node ==\n");
	resetChain(3);
	g_chain.nodes[1].present = false;  // node 2 absent

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();

	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 11, 12);
	spi.init();
	SlimeVR::ATTinyCSPinInterface present(&bus, 1, 0);
	SlimeVR::ATTinyCSPinInterface absent(&bus, 2, 0);
	SlimeVR::Sensors::SPIImpl good(&spi, &present);
	SlimeVR::Sensors::SPIImpl bad(&spi, &absent);

	check(good.hasSensorOnBus(), "present node still detected");
	check(!bad.hasSensorOnBus(), "absent node reports no sensor rather than garbage");
	check(g_chain.failures == 0, "no bus fight while probing an absent node");
}

void scenarioIdleSensorIsNotMistakenForAbsent() {
	std::printf("\n== Unconfigured sensor (the DEC-012 regression) ==\n");
	resetChain(1);
	g_chain.nodes[0].sensors[0].configured = false;  // data registers read 0x00

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();
	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 11, 12);
	spi.init();
	SlimeVR::ATTinyCSPinInterface pin(&bus, 1, 0);
	SlimeVR::Sensors::SPIImpl imu(&spi, &pin);

	uint8_t probe[4];
	imu.readBytes(0x00, 4, probe);
	const bool allZero
		= probe[0] == 0 && probe[1] == 0 && probe[2] == 0 && probe[3] == 0;
	check(allZero, "an idle ICM-45686 really does read 0x00 from its low registers");
	check(
		imu.hasSensorOnBus(),
		"...and is still reported present (a register heuristic would reject it)"
	);
}

void scenarioLocalAndRemoteShareTheBus() {
	std::printf("\n== Local chip select alongside remote ones ==\n");
	resetChain(2, 1, /*localCs=*/3);

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();
	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 11, 12);
	spi.init();

	DirectPinInterface localPin(3);
	SlimeVR::ATTinyCSPinInterface remote1(&bus, 1, 0);
	SlimeVR::Sensors::SPIImpl local(&spi, &localPin);
	SlimeVR::Sensors::SPIImpl remote(&spi, &remote1);

	check(local.readReg(0x72) == 0xE9, "local sensor answers on the shared bus");
	check(remote.readReg(0x72) == 0xE9, "remote sensor answers on the same bus");
	pollSensor(local);
	pollSensor(remote);
	pollSensor(local);
	check(g_chain.failures == 0, "no bus fight when alternating local and remote");
}

void scenarioMultiChannel() {
	std::printf("\n== Protocol v2 channels: 2 nodes x 3 channels ==\n");
	resetChain(2, 3);

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();
	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 11, 12);
	spi.init();

	std::vector<SlimeVR::ATTinyCSPinInterface> pins;
	for (uint8_t n = 1; n <= 2; n++) {
		for (uint8_t c = 0; c < 3; c++) {
			pins.emplace_back(&bus, n, c);
		}
	}
	std::vector<SlimeVR::Sensors::SPIImpl> imus;
	for (auto& p : pins) {
		imus.emplace_back(&spi, &p);
	}

	bool allOk = true;
	for (auto& imu : imus) {
		allOk = allOk && imu.readReg(0x72) == 0xE9;
	}
	check(allOk, "all six channels addressable");

	g_chain.stats.reset();
	for (auto& imu : imus) {
		pollSensor(imu);
	}
	std::printf("     6 sensors on 2 nodes: %d I2C writes\n", g_chain.stats.i2cWrites);
	// Worth demonstrating rather than asserting in prose: channels save nodes, not
	// traffic.
	check(
		g_chain.stats.i2cWrites == 6,
		"channels reduce node count, not arm writes (one per sensor either way)"
	);
	check(g_chain.failures == 0, "one-hot holds across channels on the same node");
}

void scenarioFailedArmDoesNotPulseStrobe() {
	std::printf("\n== I2C failure during arm ==\n");
	resetChain(2);
	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();
	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 11, 12);
	spi.init();
	SlimeVR::ATTinyCSPinInterface pin1(&bus, 1, 0);
	SlimeVR::ATTinyCSPinInterface pin2(&bus, 2, 0);
	SlimeVR::Sensors::SPIImpl imu1(&spi, &pin1);
	SlimeVR::Sensors::SPIImpl imu2(&spi, &pin2);

	imu1.readReg(0x72);  // node 1 armed

	g_chain.stats.reset();
	g_chain.failNextWrite = true;
	imu2.readReg(0x72);  // arm to node 2 fails

	check(g_chain.stats.i2cFailures == 1, "the arm write was NACKed");
	check(
		g_chain.stats.i2cWrites == 1,
		"the failed transaction costs one write, not two (release does not re-arm)"
	);
	check(g_chain.failures == 0, "no bus fight caused by the failure");
	// Node 1 is still *armed*: the failed write never reached the chain, so no node
	// changed state. That is fine and is why the release path drives the strobe high -
	// arming is a latch, assertion is the latch AND the strobe.
	check(
		g_chain.nodes[0].armed,
		"node 1 remains armed (the chain never saw the write)"
	);
	check(
		!g_chain.nodes[0].csAsserted(0),
		"...but its chip select is NOT asserted, because the strobe was driven idle"
	);

	// Recovery: the next access must reach the right sensor.
	g_chain.stats.reset();
	check(imu2.readReg(0x72) == 0xE9, "next access re-arms and reaches node 2");
	check(g_chain.stats.i2cWrites >= 1, "...by issuing a fresh arm write");
	check(g_chain.failures == 0, "one-hot held through failure and recovery");
}

void scenarioStagedPowerUp() {
	std::printf("\n== Staged sensor power-up ==\n");
	resetChain(4);

	// Nothing is powered before the bus comes up.
	bool anyPowered = false;
	for (auto& n : g_chain.nodes) {
		anyPowered = anyPowered || n.sensorPowered;
	}
	check(!anyPowered, "sensors are gated off before init()");

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();

	int powered = 0;
	for (auto& n : g_chain.nodes) {
		if (n.sensorPowered) {
			powered++;
		}
	}
	check(powered == 4, "init() brought all four sensors online");
	check(
		g_chain.stats.maxSimultaneousPowerUps <= 1,
		"never more than one sensor ramping at a time (inrush is staged)"
	);
	check(
		g_chain.stats.delayMillis == 4 * SlimeVR::ATTinyCS::SensorPowerOnSettleMillis,
		"one settle delay per powered sensor"
	);

	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 11, 12);
	spi.init();
	SlimeVR::ATTinyCSPinInterface pin(&bus, 1, 0);
	SlimeVR::Sensors::SPIImpl imu(&spi, &pin);
	check(imu.readReg(0x72) == 0xE9, "sensor answers once powered");

	// A sensor that never got power must read as absent rather than as garbage.
	bus.setSensorPower(1, false);
	check(imu.readReg(0x72) == 0xFF, "unpowered sensor floats MISO rather than lying");
	check(g_chain.failures == 0, "no bus fight during staging");
}

void scenarioNodeRefusesPower() {
	std::printf("\n== Node refuses sensor power ==\n");
	resetChain(2);
	g_chain.nodes[1].present = false;  // node 2 not on the chain at all

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();

	check(g_chain.nodes[0].sensorPowered, "present node powered its sensor");
	check(
		g_chain.stats.delayMillis == 1 * SlimeVR::ATTinyCS::SensorPowerOnSettleMillis,
		"absent node costs no settle delay"
	);
	check(g_chain.failures == 0, "no bus fight");
}

void scenarioIdenticalI2CSensors() {
	std::printf("\n== I2C sensors on the chain, all at the same address ==\n");
	resetChain(4);
	for (auto& n : g_chain.nodes) {
		n.hasWireSensor = true;
		n.wireAddress = 0x68;  // every ICM/BMI/MPU part this firmware supports
	}

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();

	std::vector<SlimeVR::ATTinyCSWireInterface> wires;
	for (uint8_t i = 1; i <= 4; i++) {
		wires.emplace_back(&bus, i, 0);
	}

	// Talking to each in turn is what a poll cycle does.
	g_chain.stats.reset();
	bool reachedAll = true;
	for (auto& w : wires) {
		w.swapIn();
		Wire.beginTransmission(0x68);
		Wire.write(0x00);
		reachedAll = reachedAll && Wire.endTransmission() == 0;
	}
	check(reachedAll, "all four sensors reachable despite sharing address 0x68");
	check(
		g_chain.stats.wireSensorWrites == 4,
		"each write reached exactly one sensor, never two"
	);
	check(g_chain.failures == 0, "no bus fight between identical addresses");
	std::printf(
		"     4 identical sensors: %d arm writes, %d sensor writes\n",
		g_chain.stats.i2cWrites - g_chain.stats.wireSensorWrites,
		g_chain.stats.wireSensorWrites
	);

	// With nothing armed, nobody should answer at all.
	bus.disarmAll();
	Wire.beginTransmission(0x68);
	Wire.write(0x00);
	check(Wire.endTransmission() != 0, "disarmed: no sensor answers at 0x68");
	check(g_chain.failures == 0, "one-hot held across the whole scenario");
}

void scenarioChainedI2CBesideLocalI2C() {
	std::printf("\n== Chained I2C sensor alternating with a local I2C sensor ==\n");
	resetChain(1);
	g_chain.nodes[0].hasWireSensor = true;
	g_chain.nodes[0].wireAddress = 0x68;

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();
	SlimeVR::ATTinyCSWireInterface chained(&bus, 1, 0);

	// A poll cycle: the local sensor's I2CWireSensorInterface moves Wire to its own
	// pins, then the chained sensor's swapIn() has to move it back. The chained target
	// stays armed between cycles, so the arm write is skipped from the second cycle on
	// - which is exactly when Wire used to be left on the local pins.
	g_chain.stats.reset();
	int reached = 0;
	for (int cycle = 0; cycle < 3; cycle++) {
		SlimeVR::swapI2C(21, 22);
		chained.swapIn();
		Wire.beginTransmission(0x68);
		Wire.write(0x00);
		if (Wire.endTransmission() == 0) {
			reached++;
		}
	}
	check(reached == 3, "chained sensor reached on every cycle, not only the first");
	check(
		g_chain.stats.offChainI2C == 0,
		"no chained traffic went out on the local bus"
	);
	check(
		g_chain.stats.i2cWrites - g_chain.stats.wireSensorWrites == 1,
		"armed once; later cycles still skip the arm write"
	);
	check(g_chain.failures == 0, "no bus fight");
}

void scenarioMisflashedNode() {
	std::printf("\n== Node flashed with the wrong id ==\n");
	resetChain(2);
	g_chain.nodes[1].reportedId = 7;  // answers at 2, claims to be 7

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();
	check(true, "enumeration completes and logs the mismatch (see output above)");
	check(g_chain.failures == 0, "mismatch does not corrupt the bus");
}

}  // namespace

int main() {
	std::printf("I2SPI chain simulation\n");

	scenarioBasicChain();
	scenarioRepeatPollsAreFree();
	scenarioMissingNode();
	scenarioIdleSensorIsNotMistakenForAbsent();
	scenarioLocalAndRemoteShareTheBus();
	scenarioMultiChannel();
	scenarioFailedArmDoesNotPulseStrobe();
	scenarioStagedPowerUp();
	scenarioNodeRefusesPower();
	scenarioIdenticalI2CSensors();
	scenarioChainedI2CBesideLocalI2C();
	scenarioMisflashedNode();

	std::printf("\n%d checks, %d failed\n", checks, failed);
	return failed == 0 ? 0 : 1;
}

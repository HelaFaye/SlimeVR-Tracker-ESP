#pragma once

#include <cstdint>
#include <map>
#include <vector>

#include "ATTinyCSProtocol.h"

namespace sim {

/// Transaction-level model of an ICM-45686 on SPI.
struct Sensor {
	bool present = true;
	bool configured = false;

	uint8_t transfer(uint8_t out);

private:
	bool expectRegister = true;
	bool reading = false;
	uint8_t address = 0;
	uint8_t dataByte = 1;
};

/// Model of one ATtiny chip-select node, implementing ATTinyCSProtocol.h independently of
/// the node firmware so the two can be checked against each other.
struct Node {
	uint8_t id = 0;
	uint8_t reportedId = 0;  // set differently from id to simulate a mis-flashed node
	bool present = true;
	uint8_t channels = 1;

	bool armed = false;
	uint8_t armedChannel = 0;
	bool softwareCsLow = false;
	SlimeVR::ATTinyCS::CsMode mode = SlimeVR::ATTinyCS::CsMode::Strobe;

	Sensor sensors[SlimeVR::ATTinyCS::MaxChannels];

	void onWrite(const std::vector<uint8_t>& bytes, bool toChainAddress);
	[[nodiscard]] bool csAsserted(uint8_t channel) const;
	[[nodiscard]] std::vector<uint8_t> identity() const;
};

struct Stats {
	int i2cWrites = 0;
	int i2cBytes = 0;
	int i2cFailures = 0;
	int spiBytes = 0;
	int strobeToggles = 0;
	unsigned delayMicros = 0;

	void reset() { *this = Stats{}; }
};

struct Chain {
	uint8_t baseAddress = SlimeVR::ATTinyCS::DefaultBaseAddress;
	int strobePin = 6;
	int localCsPin = -1;

	int strobe = 1;  // HIGH
	std::map<int, int> gpio;

	std::vector<Node> nodes;
	Sensor localSensor;

	Stats stats;
	int failures = 0;

	bool failNextWrite = false;

	uint8_t txAddress = 0;
	std::vector<uint8_t> txBuffer;
	std::vector<uint8_t> rxBuffer;
	size_t rxPos = 0;

	void i2cBegin(uint8_t addr);
	uint8_t i2cEnd();
	uint8_t i2cRequest(uint8_t addr, uint8_t len);
	uint8_t spiTransfer(uint8_t out);

	void checkOneHot(const char* where);
	void fail(const char* message);
};

extern Chain g_chain;

void gpioWrite(int pin, int level);
int gpioRead(int pin);

}  // namespace sim

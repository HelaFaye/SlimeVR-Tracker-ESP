#pragma once
#include <cstdint>
#define MSBFIRST 1
#define LSBFIRST 0
#define SPI_MODE0 0
#define SPI_MODE3 3

struct SPISettings {
	SPISettings(uint32_t c = 1000000, uint8_t b = MSBFIRST, uint8_t m = SPI_MODE3)
		: _clock(c), _bitOrder(b), _dataMode(m) {}
	uint32_t _clock;
	uint8_t _bitOrder;
	uint8_t _dataMode;
};

// Routed into the simulated chain: every transfer is checked against which chip
// select is actually asserted.
struct SPIClass {
	void begin(int8_t = -1, int8_t = -1, int8_t = -1, int8_t = -1) {}
	void beginTransaction(SPISettings) {}
	void endTransaction() {}
	uint8_t transfer(uint8_t v);
};
extern SPIClass SPI;

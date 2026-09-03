#pragma once
#include <cstdint>
// Delivers writes to the modelled ATtiny nodes rather than to a real bus.
struct TwoWire {
	void begin() {}
	void begin(int, int) {}
	void end() {}
	void flush() {}
	void setClock(int) {}
	void setTimeOut(int) {}
	void beginTransmission(uint8_t addr);
	size_t write(uint8_t b);
	uint8_t endTransmission();
	uint8_t requestFrom(uint8_t addr, uint8_t len);
	int available();
	int read();
};
extern TwoWire Wire;

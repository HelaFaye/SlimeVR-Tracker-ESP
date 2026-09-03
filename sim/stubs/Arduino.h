#pragma once
// Minimal Arduino surface for the host simulation. Not a general-purpose shim:
// it exists to let the real firmware sources compile against a modelled bus.
#include <cstdarg>
#include <cstdint>
#include <string>

#define LOW 0
#define HIGH 1
#define INPUT 0
#define OUTPUT 1

namespace sim { void gpioWrite(int pin, int level); int gpioRead(int pin); }

inline void pinMode(int, int) {}
inline void digitalWrite(int pin, int level) { sim::gpioWrite(pin, level); }
inline int digitalRead(int pin) { return sim::gpioRead(pin); }
void delayMicroseconds(unsigned us);

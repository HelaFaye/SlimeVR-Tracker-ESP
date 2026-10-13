#pragma once
// Minimal Arduino surface for the host simulation. Not a general-purpose shim:
// it exists to let the real firmware sources compile against a modelled bus.
#include <cstdarg>
#include <cstdint>
#include <string>

#define LOW 0
#define HIGH 1
// Flash placement attribute on AVR/ESP; meaningless on a host.
#define PROGMEM

#define INPUT 0
#define OUTPUT 1

namespace sim {
void gpioWrite(int pin, int level);
int gpioRead(int pin);
}  // namespace sim

inline void pinMode(int, int) {}
inline void digitalWrite(int pin, int level) { sim::gpioWrite(pin, level); }
inline int digitalRead(int pin) { return sim::gpioRead(pin); }
void delayMicroseconds(unsigned us);
void delay(unsigned ms);
// Declared for sources that read the clock; each test binary that needs it defines it.
uint32_t micros();

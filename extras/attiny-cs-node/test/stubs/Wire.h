#pragma once
#include <stdint.h>
#include <stddef.h>
struct TwoWire {
  void begin(uint8_t);
  void begin(uint8_t, bool, uint8_t);
  void onReceive(void (*)(int));
  void onRequest(void (*)(void));
  int read(); int available();
  size_t write(const uint8_t*, size_t);
};
extern TwoWire Wire;

#pragma once
#include <stdint.h>
namespace logic {
  namespace in { constexpr uint8_t event_a = 1, masked = 0; }
  namespace out { constexpr uint8_t enable = 1, disable = 0; }
}
struct LogicClass {
  bool enable; uint8_t input0, input1, input2, truth, output;
  void init();
  static void start();
};
extern LogicClass Logic0, Logic1;
namespace Logic { inline void start() { LogicClass::start(); } }

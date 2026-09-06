#pragma once
#include <stdint.h>
namespace gen0 { constexpr uint8_t pin_pa6 = 1; }
namespace user { constexpr uint8_t ccl0_event_a = 1, ccl1_event_a = 2; }
struct EventClass { void set_generator(uint8_t); void set_user(uint8_t); void start(); };
extern EventClass Event0;

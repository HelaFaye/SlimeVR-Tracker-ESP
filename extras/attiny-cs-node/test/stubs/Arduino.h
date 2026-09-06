#pragma once
#include <stdint.h>
#include <stddef.h>
#define LOW 0
#define HIGH 1
#define INPUT 0
#define OUTPUT 1
#define PIN_PA0 0
#define PIN_PA1 1
#define PIN_PA2 2
#define PIN_PA3 3
#define PIN_PA6 6
#define PIN_PA7 7
void pinMode(uint8_t, uint8_t);
void digitalWriteFast(uint8_t, uint8_t);
void digitalWrite(uint8_t, uint8_t);

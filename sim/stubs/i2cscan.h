#pragma once
#include <cstddef>
#include <cstdint>
namespace I2CSCAN {
bool checkI2C(uint8_t, uint8_t);
bool hasDevOnBus(uint8_t);
uint8_t pickDevice(uint8_t, uint8_t, bool);
int clearBus(uint8_t, uint8_t);
bool inArray(uint8_t, const uint8_t*, size_t);
void scani2cports();
}  // namespace I2CSCAN

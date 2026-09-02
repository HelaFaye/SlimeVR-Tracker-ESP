/*
	SlimeVR Code is placed under the MIT license
	Copyright (c) 2021 Eiren Rain

	Permission is hereby granted, free of charge, to any person obtaining a copy
	of this software and associated documentation files (the "Software"), to deal
	in the Software without restriction, including without limitation the rights
	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the Software is
	furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in
	all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
	THE SOFTWARE.
*/
#pragma once

#include <Arduino.h>

#include "consts.h"
#include "debug.h"
#include "defines.h"

// clang-format off
#include "boards/boards_default.h"
// clang-format on

#ifndef SECOND_IMU
#define SECOND_IMU IMU
#endif

#ifndef SECOND_IMU_ROTATION
#define SECOND_IMU_ROTATION IMU_ROTATION
#endif

#ifndef BATTERY_MONITOR
#define BATTERY_MONITOR BAT_INTERNAL
#endif

#ifndef SENSOR_INFO_LIST
#define SENSOR_INFO_LIST
#endif

// --- Wi-Fi band selection (dual-band parts only)
// The ESP32-C5 is dual-band. Arduino-ESP32's default band mode is AUTO, which faults
// when the radio starts, so a band has to be chosen explicitly before WiFi.begin().
//
// Default is 2.4 GHz only. 5 GHz is the reason to want a C5 in the first place, but the
// SlimeVR server is discovered by UDP broadcast on the local subnet - if your AP puts
// 5 GHz on a separate SSID rather than bridging the bands, a 5 GHz-only tracker will
// associate fine and then never find the server. See DECISIONS.md DEC-002.
//
// Override with -DWIFI_TRACKER_BAND_MODE=WIFI_BAND_MODE_5G_ONLY once you have confirmed
// discovery works on your network.
#ifndef WIFI_TRACKER_BAND_MODE
#define WIFI_TRACKER_BAND_MODE WIFI_BAND_MODE_2G_ONLY
#endif

// --- Remote chip select over an RJ45 sensor chain (ATtiny CS nodes)
// Defaults for the ATTINY_CS(nodeId) descriptor. A board that puts the node chain on
// the same I2C pins as its local sensors needs to set nothing; boards with a dedicated
// chain bus override these. See docs/dev/ATTINY-CS-PROTOCOL.md.
#ifndef REMOTE_CS_SCL
#ifdef PIN_IMU_SCL
#define REMOTE_CS_SCL PIN_IMU_SCL
#else
#define REMOTE_CS_SCL 255
#endif
#endif

#ifndef REMOTE_CS_SDA
#ifdef PIN_IMU_SDA
#define REMOTE_CS_SDA PIN_IMU_SDA
#else
#define REMOTE_CS_SDA 255
#endif
#endif

#ifndef REMOTE_CS_BASE_ADDR
#define REMOTE_CS_BASE_ADDR 0x30
#endif

// -1 disables the shared CS strobe conductor and falls back to driving CS over I2C.
// That is ~1000x slower per SPI transaction and is meant for bring-up only.
#ifndef REMOTE_CS_STROBE
#define REMOTE_CS_STROBE -1
#endif

// Experimental features
#ifndef EXPERIMENTAL_BNO_DISABLE_ACCEL_CALIBRATION
#define EXPERIMENTAL_BNO_DISABLE_ACCEL_CALIBRATION true
#endif

#ifndef IMU_USE_EXTERNAL_CLOCK
#define IMU_USE_EXTERNAL_CLOCK true  // Use external clock for IMU (ICM-45686 only)
#endif

#ifndef VENDOR_NAME
#define VENDOR_NAME "Unknown"
#endif

#ifndef VENDOR_URL
#define VENDOR_URL ""
#endif

#ifndef PRODUCT_NAME
#define PRODUCT_NAME "DIY SlimeVR Tracker"
#endif

#ifndef UPDATE_ADDRESS
#define UPDATE_ADDRESS ""
#endif

#ifndef UPDATE_NAME
#define UPDATE_NAME ""
#endif

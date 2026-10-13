/*
 * Host tests for SoftFusion::MagDriver: detection per transport, the exact setup
 * writes, burst-read addressing, sample scaling and polling cadence. The magnetometers
 * are register-map models of the MMC5983MA and LIS3MDL, built from the same primary
 * sources cited in magdriver.cpp; a test failing here means driver and source disagree.
 */

#include <cmath>
#include <cstdio>
#include <map>
#include <vector>

#include "sensors/softfusion/magdriver.h"

using namespace SlimeVR::Sensors::SoftFusion;

static uint32_t g_micros = 0;
uint32_t micros() { return g_micros; }
void delay(unsigned ms) { g_micros += ms * 1000; }
void delayMicroseconds(unsigned us) { g_micros += us; }
namespace sim {
void gpioWrite(int, int) {}
int gpioRead(int) { return 0; }
}  // namespace sim

static int checks = 0, failures = 0;
static void check(bool ok, const char* what) {
	checks++;
	if (!ok) {
		failures++;
	}
	std::printf("  [%s] %s\n", ok ? "ok" : "FAIL", what);
}

/// A register-level model. Records every write and every burst-read address.
struct FakeMag {
	std::map<uint8_t, uint8_t> regs;
	std::vector<std::pair<uint8_t, uint8_t>> writes;
	std::vector<uint8_t> singleReads;
	std::vector<uint8_t> burstReads;
	std::vector<uint8_t> deviceIds;
	uint8_t i2cAddress = 0;  // for aux: only answer when selected

	bool selected = true;

	MagInterface interface(MagTransport transport) {
		return MagInterface{
			.transport = transport,
			.readByte = [this](uint8_t reg) -> uint8_t {
				singleReads.push_back(reg);
				if (!selected) {
					return 0xff;
				}
				return regs.count(reg) ? regs[reg] : 0;
			},
			.writeByte
			= [this](uint8_t reg, uint8_t value) { writes.emplace_back(reg, value); },
			.readBytes =
				[this](uint8_t reg, uint8_t* buffer, size_t length) {
					burstReads.push_back(reg);
					// Strip whichever auto-increment flag the part uses; a model only
					// sees the register index.
					uint8_t base = reg & 0x3f;
					for (size_t i = 0; i < length; i++) {
						buffer[i] = regs.count(base + i) ? regs[base + i] : 0;
					}
				},
			.setDeviceId =
				[this](uint8_t id) {
					deviceIds.push_back(id);
					selected = (i2cAddress == 0 || id == i2cAddress);
				},
		};
	}
};

static bool near(float a, float b) { return std::fabs(a - b) < 0.01f; }

static void mmc5983maOverSpi() {
	std::printf("\n== MMC5983MA on its own SPI chip select ==\n");
	FakeMag mmc;
	mmc.regs[0x2f] = 0x30;  // Product ID
	// X = +1 G = 32768 + 4096, Y = -0.5 G = 32768 - 2048, Z = 0: big-endian, unsigned.
	mmc.regs[0x00] = 0x90;
	mmc.regs[0x01] = 0x00;
	mmc.regs[0x02] = 0x78;
	mmc.regs[0x03] = 0x00;
	mmc.regs[0x04] = 0x80;
	mmc.regs[0x05] = 0x00;

	MagDriver driver;
	check(driver.init(mmc.interface(MagTransport::Spi), false), "detected over SPI");
	check(
		driver.getAttachedMagName()
			&& std::string(driver.getAttachedMagName()) == "MMC5983MA",
		"identified as MMC5983MA"
	);

	bool onlySpiParts = true;
	for (auto reg : mmc.singleReads) {
		onlySpiParts = onlySpiParts && (reg == 0x2f || reg == 0x0f);
	}
	check(
		onlySpiParts,
		"only SPI-capable parts probed (no QMC6309/IST8306 WHO_AM_I reads)"
	);
	check(mmc.deviceIds.empty(), "no aux device-id selection on SPI");

	std::vector<std::pair<uint8_t, uint8_t>> expected
		= {{0x0a, 0x80}, {0x0a, 0x00}, {0x09, 0x20}, {0x0b, 0x0d}};
	check(
		mmc.writes == expected,
		"setup: SW_RST, BW=100 Hz, Auto_SR_en, continuous 100 Hz"
	);

	driver.setPollingEnabled(true);
	float out[3] = {0, 0, 0};
	int samples = 0;
	g_micros += 10'000;
	driver.poll(g_micros, 0.01f, [&](const float s[3]) {
		out[0] = s[0];
		out[1] = s[1];
		out[2] = s[2];
		samples++;
	});
	check(samples == 1, "one sample when the period has elapsed");
	check(
		mmc.burstReads.size() == 1 && mmc.burstReads[0] == 0x00,
		"burst from 0x00, no flag"
	);
	check(
		near(out[0], 100.0f) && near(out[1], -50.0f) && near(out[2], 0.0f),
		"big-endian unsigned with 32768 offset -> (+100, -50, 0) uT"
	);
}

static void lis3mdlOverSpiAndAux() {
	std::printf("\n== LIS3MDL over SPI and behind an IMU aux master ==\n");
	for (auto transport : {MagTransport::Spi, MagTransport::ImuAux}) {
		const bool spi = transport == MagTransport::Spi;
		std::printf("  -- %s\n", spi ? "SPI" : "IMU aux");
		FakeMag lis;
		lis.i2cAddress = spi ? 0 : 0x1c;
		lis.regs[0x0f] = 0x3d;
		// X = +6842 (1 G), Y = -6842, Z = 0: little-endian signed.
		lis.regs[0x28] = 0xba;
		lis.regs[0x29] = 0x1a;
		lis.regs[0x2a] = 0x46;
		lis.regs[0x2b] = 0xe5;
		lis.regs[0x2c] = 0x00;
		lis.regs[0x2d] = 0x00;

		MagDriver driver;
		check(driver.init(lis.interface(transport), false), "detected");
		check(
			driver.getAttachedMagName()
				&& std::string(driver.getAttachedMagName()) == "LIS3MDL",
			"identified as LIS3MDL"
		);
		if (!spi) {
			bool selectedLis = !lis.deviceIds.empty() && lis.deviceIds.back() == 0x1c;
			check(selectedLis, "aux master pointed at 0x1C");
		}

		std::vector<std::pair<uint8_t, uint8_t>> expected = {
			{0x21, 0x04},
			{0x21, 0x00},
			{0x20, 0x5c},
			{0x23, 0x08},
			{0x24, 0x40},
			{0x22, 0x00},
		};
		check(
			lis.writes == expected,
			"setup: reset, +/-4 G, HP 80 Hz XY+Z, BDU, continuous"
		);

		driver.setPollingEnabled(true);
		float out[3] = {0, 0, 0};
		g_micros += 20'000;
		driver.poll(g_micros, 0.01f, [&](const float s[3]) {
			out[0] = s[0];
			out[1] = s[1];
			out[2] = s[2];
		});
		const uint8_t want = spi ? (0x28 | 0x40) : (0x28 | 0x80);
		check(
			!lis.burstReads.empty() && lis.burstReads[0] == want,
			spi ? "SPI burst sets MS (0x40): register byte 0x68"
				: "I2C burst sets auto-increment (0x80): sub-address 0xA8"
		);
		check(
			near(out[0], 100.0f) && near(out[1], -100.0f) && near(out[2], 0.0f),
			"little-endian signed, 6842 LSB/G -> (+100, -100, 0) uT"
		);
	}
}

static void pollingCadence() {
	std::printf("\n== Polling cadence and the enable toggle ==\n");
	FakeMag mmc;
	mmc.regs[0x2f] = 0x30;
	MagDriver driver;
	driver.init(mmc.interface(MagTransport::Spi), false);

	int samples = 0;
	auto count = [&](const float*) { samples++; };

	g_micros = 1'000'000;
	driver.poll(g_micros, 0.01f, count);
	check(samples == 0, "disabled by default: no reads");

	driver.setPollingEnabled(true);
	for (int i = 1; i <= 100; i++) {
		g_micros += 1'000;  // 1 ms loop, 100 ms total
		driver.poll(g_micros, 0.01f, count);
	}
	check(samples == 10, "10 ms period over 100 ms of 1 ms loops: exactly 10 samples");

	samples = 0;
	g_micros += 500'000;  // a long stall
	driver.poll(g_micros, 0.01f, count);
	driver.poll(g_micros, 0.01f, count);
	check(samples == 1, "after a stall: one sample, no burst of catch-up reads");

	driver.setPollingEnabled(false);
	samples = 0;
	g_micros += 100'000;
	driver.poll(g_micros, 0.01f, count);
	check(samples == 0, "disabled again: no reads");
}

static void noMagnetometer() {
	std::printf("\n== Nothing answering ==\n");
	FakeMag none;  // every register reads 0
	MagDriver driver;
	check(
		!driver.init(none.interface(MagTransport::Spi), false),
		"init reports no magnetometer"
	);
	check(
		!driver.isMagAttached(),
		"isMagAttached() is false, so the toggle is unsupported"
	);
	driver.setPollingEnabled(true);
	int samples = 0;
	g_micros += 50'000;
	driver.poll(g_micros, 0.01f, [&](const float*) { samples++; });
	check(
		samples == 0 && none.burstReads.empty(),
		"enabling polling with no part does nothing"
	);
}

static void scalingEdges() {
	std::printf("\n== Scaling edge cases ==\n");
	const auto& mags = MagDriver::getSupportedMags();
	const MagDefinition* lis = nullptr;
	const MagDefinition* mmc = nullptr;
	for (auto& m : mags) {
		if (std::string(m.name) == "LIS3MDL") {
			lis = &m;
		}
		if (std::string(m.name) == "MMC5983MA") {
			mmc = &m;
		}
	}
	float out[3];
	uint8_t lisRaw[6] = {0x00, 0x80, 0xff, 0x7f, 0xff, 0xff};  // -32768, +32767, -1
	MagDriver::scaleMagSample(*lis, lisRaw, out);
	check(
		out[0] < 0 && out[1] > 0 && out[2] < 0 && near(out[2], -100.0f / 6842.0f),
		"LIS3MDL: full-scale negative, positive and -1 LSB sign-extend correctly"
	);
	uint8_t mmcRaw[6] = {0x00, 0x00, 0xff, 0xff, 0x80, 0x00};  // 0, 65535, 32768
	MagDriver::scaleMagSample(*mmc, mmcRaw, out);
	check(
		near(out[0], -32768 * 100.0f / 4096.0f)
			&& near(out[1], 32767 * 100.0f / 4096.0f) && near(out[2], 0.0f),
		"MMC5983MA: 0 and 65535 map to -/+ full scale, 32768 to zero"
	);
}

int main() {
	mmc5983maOverSpi();
	lis3mdlOverSpiAndAux();
	pollingCadence();
	noMagnetometer();
	scalingEdges();
	std::printf("\n%d checks, %d failed\n", checks, failures);
	return failures ? 1 : 0;
}

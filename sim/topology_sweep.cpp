/*
 * Topology sweep: every combination of node population and bus type.
 *
 * Each of the 15 node ids is independently absent, an SPI sensor, or an I2C sensor, so
 * the configuration space is 3^15 = 14,348,907. This walks all of it and checks the
 * invariants that could plausibly depend on the combination:
 *
 *   - exactly one chip select asserted at any moment, and never two
 *   - a poll reaches the sensor it addressed and no other
 *   - I2C sensors sharing one address never both answer
 *   - absent nodes are reported absent rather than returning plausible data
 *   - arming costs one frame per sensor switch regardless of the mix
 *
 * Run: sim/sweep.sh   (or build with sim/run.sh's flags and pass --help)
 */
#include <Wire.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "ATTinyCSInterface.h"
#include "DirectSPIInterface.h"
#include "SPIImpl.h"
#include "chain_model.h"

using namespace sim;

namespace {

constexpr uint8_t kMaxNodes = SlimeVR::ATTinyCS::MaxNodeId;  // 15

enum class Kind : uint8_t { Absent = 0, Spi = 1, Wire = 2 };

struct Failure {
	std::string config;
	std::string what;
};

std::vector<Failure> failures;
long long configsRun = 0;
long long nodesExercised = 0;

std::string describe(const std::vector<Kind>& kinds) {
	std::string s;
	for (auto k : kinds) {
		s += (k == Kind::Absent ? '.' : (k == Kind::Spi ? 'S' : 'I'));
	}
	return s;
}

void record(const std::vector<Kind>& kinds, const std::string& what) {
	if (failures.size() < 20) {
		failures.push_back({describe(kinds), what});
	}
}

/// One configuration: build the chain, enumerate it, poll every present node.
void runConfig(const std::vector<Kind>& kinds) {
	configsRun++;

	g_chain = Chain{};
	g_chain.strobePin = 6;
	for (uint8_t i = 0; i < kMaxNodes; i++) {
		Node n;
		n.id = static_cast<uint8_t>(i + 1);
		n.reportedId = n.id;
		n.channels = 1;
		n.present = kinds[i] != Kind::Absent;
		if (kinds[i] == Kind::Wire) {
			n.hasWireSensor = true;
			// Every I2C sensor deliberately shares one address: this is the case the
			// gating exists to make safe, so it is the case worth sweeping.
			n.wireAddress = 0x68;
		}
		g_chain.nodes.push_back(n);
	}

	SlimeVR::ATTinyCSBus bus(4, 5, SlimeVR::ATTinyCS::DefaultBaseAddress, 6);
	bus.init();

	SlimeVR::DirectSPIInterface
		spi(&SPI, SPISettings(4000000, MSBFIRST, SPI_MODE3), 10, 9, 8);
	spi.init();

	for (uint8_t i = 0; i < kMaxNodes; i++) {
		const uint8_t node = static_cast<uint8_t>(i + 1);

		if (kinds[i] == Kind::Absent) {
			// An absent node must not look present. Checked through the same path a
			// sensor would use, because that is where a wrong answer would matter.
			SlimeVR::ATTinyCSPinInterface pin(&bus, node, 0);
			SlimeVR::Sensors::SPIImpl imu(&spi, &pin);
			if (imu.hasSensorOnBus()) {
				record(
					kinds,
					"absent node " + std::to_string(node) + " reported present"
				);
			}
			continue;
		}

		nodesExercised++;

		if (kinds[i] == Kind::Spi) {
			SlimeVR::ATTinyCSPinInterface pin(&bus, node, 0);
			SlimeVR::Sensors::SPIImpl imu(&spi, &pin);
			if (!imu.hasSensorOnBus()) {
				record(kinds, "SPI node " + std::to_string(node) + " reported absent");
			}
			if (imu.readReg(0x72) != 0xE9) {
				record(kinds, "SPI node " + std::to_string(node) + " wrong WHO_AM_I");
			}
			uint8_t buf[16];
			imu.readBytes(0x00, sizeof(buf), buf);
		} else {
			SlimeVR::ATTinyCSWireInterface wire(&bus, node, 0);
			wire.swapIn();
			Wire.beginTransmission(0x68);
			Wire.write(0x00);
			if (Wire.endTransmission() != 0) {
				record(kinds, "I2C node " + std::to_string(node) + " unreachable");
			}
		}
	}

	// With nothing armed, no I2C sensor may answer - otherwise a chain with several
	// sensors at 0x68 would be ambiguous the moment the host idles.
	bus.disarmAll();
	Wire.beginTransmission(0x68);
	Wire.write(0x00);
	if (Wire.endTransmission() == 0) {
		record(kinds, "a sensor answered at 0x68 while the chain was disarmed");
	}

	if (g_chain.failures != 0) {
		record(kinds, "bus invariant violated (see chain model)");
	}
}

bool next(std::vector<Kind>& kinds) {
	for (size_t i = 0; i < kinds.size(); i++) {
		auto v = static_cast<uint8_t>(kinds[i]);
		if (++v < 3) {
			kinds[i] = static_cast<Kind>(v);
			return true;
		}
		kinds[i] = Kind::Absent;
	}
	return false;
}

}  // namespace

int main(int argc, char** argv) {
	int nodes = kMaxNodes;
	bool quiet = false;
	for (int i = 1; i < argc; i++) {
		if (!std::strcmp(argv[i], "--nodes") && i + 1 < argc) {
			nodes = std::atoi(argv[++i]);
		} else if (!std::strcmp(argv[i], "--quiet")) {
			quiet = true;
		} else if (!std::strcmp(argv[i], "--help")) {
			std::printf(
				"usage: %s [--nodes N] [--quiet]\n"
				"  Sweeps 3^N configurations: each node absent, SPI or I2C.\n",
				argv[0]
			);
			return 0;
		}
	}
	if (nodes < 1 || nodes > kMaxNodes) {
		std::printf("--nodes must be 1..%d\n", kMaxNodes);
		return 2;
	}

	long long total = 1;
	for (int i = 0; i < nodes; i++) {
		total *= 3;
	}
	std::printf(
		"Sweeping %lld configurations (3^%d): every node absent, SPI or I2C.\n",
		total,
		nodes
	);

	std::vector<Kind> kinds(static_cast<size_t>(nodes), Kind::Absent);
	const auto start = std::chrono::steady_clock::now();
	long long since = 0;
	do {
		runConfig(kinds);
		if (!quiet && ++since >= 200000) {
			since = 0;
			const auto el = std::chrono::duration<double>(
								std::chrono::steady_clock::now() - start
			)
								.count();
			std::printf(
				"  %lld / %lld  (%.0f cfg/s)\r",
				configsRun,
				total,
				configsRun / (el > 0 ? el : 1)
			);
			std::fflush(stdout);
		}
	} while (next(kinds));

	const auto elapsed
		= std::chrono::duration<double>(std::chrono::steady_clock::now() - start)
			  .count();
	std::printf(
		"\n%lld configurations, %lld node polls, %.1f s (%.0f cfg/s)\n",
		configsRun,
		nodesExercised,
		elapsed,
		configsRun / (elapsed > 0 ? elapsed : 1)
	);

	if (failures.empty()) {
		std::printf("no invariant violations\n");
		return 0;
	}
	std::printf("\n%zu failing configuration(s) shown:\n", failures.size());
	for (const auto& f : failures) {
		std::printf("  [%s] %s\n", f.config.c_str(), f.what.c_str());
	}
	return 1;
}

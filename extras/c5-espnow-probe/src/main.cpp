/*
 * ESP-NOW channel probe for the ESP32-C5.
 *
 * Answers the questions docs/dev/E22-AND-C5-HUB.md §5 leaves open, on real radios:
 *   1. Does ESP-NOW work on 5 GHz channels on this ESP-IDF release?
 *   2. What loss and RSSI does a body-worn link see on each band?
 *   3. Can peers follow an announced channel switch without dropping out?
 *
 * Flash the same image on two or more C5 boards. Each broadcasts a numbered ping every
 * 50 ms and prints, once a second, every peer it heard: packets, loss and mean RSSI.
 *
 * Serial commands (115200 baud, newline-terminated):
 *   c <channel>   switch this board now (1-13 on 2.4 GHz; 36-48, 149-165 on 5 GHz)
 *   s <channel>   announce a switch: every board that hears it moves 1 s later
 *   ?             print the current channel and band
 */

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include <atomic>

namespace {

constexpr uint32_t Magic = 0x534C5043;  // "SLPC"
constexpr uint32_t PingIntervalMs = 50;
constexpr uint32_t ReportIntervalMs = 1000;
constexpr uint32_t SwitchDelayMs = 1000;
constexpr uint8_t DefaultChannel = 36;  // UNII-1, no DFS
constexpr size_t MaxPeers = 8;
const uint8_t Broadcast[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

enum class Kind : uint8_t { Ping = 1, Switch = 2 };

struct __attribute__((packed)) Frame {
	uint32_t magic;
	Kind kind;
	uint8_t channel;  // Ping: sender's channel. Switch: channel to move to.
	uint32_t seq;
};

struct Peer {
	uint8_t mac[6];
	bool used;
	uint32_t received;
	uint32_t firstSeq;
	uint32_t lastSeq;
	int32_t rssiSum;
};

Peer peers[MaxPeers];
portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
uint8_t channel = DefaultChannel;
uint32_t seq = 0;
std::atomic<uint32_t> sentOk{0};
std::atomic<uint32_t> sentFail{0};
volatile int pendingSwitch = -1;
volatile uint32_t switchAt = 0;

bool is5GHz(uint8_t ch) { return ch > 14; }

bool validChannel(int ch) {
	return (ch >= 1 && ch <= 13) || (ch >= 36 && ch <= 48 && ch % 4 == 0)
		|| (ch >= 149 && ch <= 165 && (ch - 149) % 4 == 0);
}

bool tune(uint8_t ch) {
	esp_err_t err = esp_wifi_set_band_mode(
		is5GHz(ch) ? WIFI_BAND_MODE_5G_ONLY : WIFI_BAND_MODE_2G_ONLY
	);
	if (err == ESP_OK) {
		err = esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
	}
	if (err != ESP_OK) {
		Serial.printf("! channel %u: %s\n", ch, esp_err_to_name(err));
		return false;
	}
	channel = ch;
	portENTER_CRITICAL(&lock);
	for (auto& p : peers) {
		p.used = false;  // statistics restart per channel
	}
	portEXIT_CRITICAL(&lock);
	Serial.printf("= channel %u (%s)\n", ch, is5GHz(ch) ? "5 GHz" : "2.4 GHz");
	return true;
}

void onReceive(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
	if (len != sizeof(Frame)) {
		return;
	}
	Frame f;
	memcpy(&f, data, sizeof(f));
	if (f.magic != Magic) {
		return;
	}
	if (f.kind == Kind::Switch && validChannel(f.channel)) {
		pendingSwitch = f.channel;
		switchAt = millis() + SwitchDelayMs;
		return;
	}
	portENTER_CRITICAL_ISR(&lock);
	Peer* slot = nullptr;
	for (auto& p : peers) {
		if (p.used && memcmp(p.mac, info->src_addr, 6) == 0) {
			slot = &p;
			break;
		}
	}
	if (!slot) {
		for (auto& p : peers) {
			if (!p.used) {
				slot = &p;
				memcpy(p.mac, info->src_addr, 6);
				p.used = true;
				p.received = 0;
				p.firstSeq = f.seq;
				p.rssiSum = 0;
				break;
			}
		}
	}
	if (slot) {
		slot->received++;
		slot->lastSeq = f.seq;
		slot->rssiSum += info->rx_ctrl->rssi;
	}
	portEXIT_CRITICAL_ISR(&lock);
}

void onSent(const esp_now_send_info_t*, esp_now_send_status_t status) {
	if (status == ESP_NOW_SEND_SUCCESS) {
		sentOk++;
	} else {
		sentFail++;
	}
}

void send(Kind kind, uint8_t ch) {
	Frame f{Magic, kind, ch, seq++};
	esp_now_send(Broadcast, reinterpret_cast<uint8_t*>(&f), sizeof(f));
}

void report() {
	Peer snapshot[MaxPeers];
	portENTER_CRITICAL(&lock);
	memcpy(snapshot, peers, sizeof(peers));
	portEXIT_CRITICAL(&lock);
	Serial.printf(
		"ch %u  sent %lu ok / %lu failed\n",
		channel,
		static_cast<unsigned long>(sentOk.load()),
		static_cast<unsigned long>(sentFail.load())
	);
	for (const auto& p : snapshot) {
		if (!p.used || p.received == 0) {
			continue;
		}
		const uint32_t expected = p.lastSeq - p.firstSeq + 1;
		const float loss
			= expected ? 100.0f * (expected - p.received) / expected : 0.0f;
		Serial.printf(
			"  %02X:%02X:%02X:%02X:%02X:%02X  %5lu pkts  loss %5.1f %%  rssi %4ld "
			"dBm\n",
			p.mac[0],
			p.mac[1],
			p.mac[2],
			p.mac[3],
			p.mac[4],
			p.mac[5],
			static_cast<unsigned long>(p.received),
			loss,
			static_cast<long>(p.rssiSum / static_cast<int32_t>(p.received))
		);
	}
}

void handleSerial() {
	static String line;
	while (Serial.available()) {
		const char c = Serial.read();
		if (c != '\n' && c != '\r') {
			line += c;
			continue;
		}
		line.trim();
		if (line.length() == 0) {
			continue;
		}
		const char cmd = line[0];
		const int ch = line.length() > 1 ? line.substring(1).toInt() : -1;
		if (cmd == '?') {
			Serial.printf(
				"= channel %u (%s)\n",
				channel,
				is5GHz(channel) ? "5 GHz" : "2.4 GHz"
			);
		} else if ((cmd == 'c' || cmd == 's') && validChannel(ch)) {
			if (cmd == 's') {
				// Repeat the announcement: a broadcast has no retries.
				for (int i = 0; i < 5; i++) {
					send(Kind::Switch, ch);
					delay(20);
				}
				pendingSwitch = ch;
				switchAt = millis() + SwitchDelayMs;
			} else {
				tune(ch);
			}
		} else {
			Serial.println("? commands: c <ch>, s <ch>, ?");
		}
		line = "";
	}
}

}  // namespace

void setup() {
	Serial.begin(115200);
	delay(1500);
	Serial.println("\nESP-NOW channel probe (ESP32-C5)");
	WiFi.mode(WIFI_STA);
	WiFi.disconnect();
	Serial.printf("MAC %s\n", WiFi.macAddress().c_str());
	if (esp_now_init() != ESP_OK) {
		Serial.println("! esp_now_init failed");
		return;
	}
	esp_now_register_recv_cb(onReceive);
	esp_now_register_send_cb(onSent);
	esp_now_peer_info_t peer{};
	memcpy(peer.peer_addr, Broadcast, 6);
	peer.channel = 0;  // follow the current channel
	peer.ifidx = WIFI_IF_STA;
	esp_now_add_peer(&peer);
	tune(DefaultChannel);
}

void loop() {
	static uint32_t lastPing = 0;
	static uint32_t lastReport = 0;
	const uint32_t now = millis();
	if (pendingSwitch >= 0 && static_cast<int32_t>(now - switchAt) >= 0) {
		const int ch = pendingSwitch;
		pendingSwitch = -1;
		tune(static_cast<uint8_t>(ch));
	}
	if (now - lastPing >= PingIntervalMs) {
		lastPing = now;
		send(Kind::Ping, channel);
	}
	if (now - lastReport >= ReportIntervalMs) {
		lastReport = now;
		report();
	}
	handleSerial();
}

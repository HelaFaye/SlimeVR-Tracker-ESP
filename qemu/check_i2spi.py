#!/usr/bin/env python3
"""SlimeVR tracker firmware with its IMUs on I2SPI chains (SPI data, I2C selection;
docs/I2SPI.md in the tracker), in the configurations a build is likely to use, and the
faults a chain is likely to have. Every IMU is an emulated ICM-45686 (icm45686-spi) on the
S3's SPI2; every chain an emulated set of nodes (i2spi-chain) on I2C0.

For each scenario:
- the tracker reports the sensors it should have as working to a stand-in SlimeVR
  server, and streams rotations for each; of the rest, sensor 0 (mandatory) is
  reported in error and the others not at all, as upstream's SensorManager does;
- each working sensor's IMU had its FIFO read;
- no two chip selects were ever asserted together (the chains' and the IMUs' own
  counts: two parts driving MISO);
- what the firmware should say about a fault, it says;
- it stays connected; no panic, no reset.

    check.py IMAGES WORKDIR [SCENARIO...]
IMAGES holds one build per configuration in i2spi/ (s3.sh): IMAGES/<config>/flash.bin.
"""
import os
import re
import socket
import struct
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# boards.py comes from the qemu_esp32 clone s3.sh makes (QEMU_ESP32: its directory)
sys.path.insert(0, os.path.join(os.environ["QEMU_ESP32"], "firmware"))
from boards import boot, link  # noqa: E402

FATAL = re.compile(r"Guru Meditation|abort\(\) was called|Backtrace:|Task watchdog|rst:0xc")
SERVER_PORT = 6969
SENSOR_INFO, ROTATION_DATA = 15, 17
SENSOR_OK, SENSOR_ERROR = 1, 2
STROBE, STROBE_RIGHT, DIRECT_CS = 10, 6, 7      # The configs' pins (i2spi/*.json)
fails = 0


def check(what, ok, detail=""):
    global fails
    print("  %s %s%s" % ("ok  " if ok else "FAIL", what, " (%s)" % detail if detail and not ok else ""))
    if not ok:
        fails += 1
    return ok


class Server(threading.Thread):
    """Answers the handshake, sends heartbeats; keeps each sensor's last reported state
    and counts its rotation packets."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", SERVER_PORT))
        self.sock.settimeout(0.5)
        self.running = True
        self.reset()

    def reset(self):
        self.peer = None
        self.state = {}             # sensor id -> last SensorInfo state
        self.rotations = {}         # sensor id -> RotationData packets

    def run(self):
        last_beat = 0
        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
                ptype = struct.unpack(">I", data[:4])[0] if len(data) >= 4 else -1
                body = data[12:]
                if ptype == 3:
                    self.peer = addr
                    self.sock.sendto(b"\x03Hey OVR =D 5", addr)
                elif ptype == SENSOR_INFO and len(body) >= 2:
                    self.state[body[0]] = body[1]
                elif ptype == ROTATION_DATA and body:
                    self.rotations[body[0]] = self.rotations.get(body[0], 0) + 1
            except socket.timeout:
                pass
            if self.peer and time.time() - last_beat > 0.5:
                self.sock.sendto(b"\x00\x00\x00\x01" + bytes(8), self.peer)
                last_beat = time.time()


def chain(name, links, nodes, address=0x13, strobe=STROBE, **opts):
    """An i2spi-chain: links {target: imu id}, nodes "1/2:2/..." (absent ones left out)."""
    dev = "i2spi-chain,bus=i2c0,address=%#x,id=%s,links=%s" % (
        address, name, ":".join("%#x=%s" % t for t in sorted(links.items())))
    if nodes:
        dev += ",nodes=" + nodes
    for k, v in opts.items():
        dev += ",%s=%s" % (k, v)
    args = ["-device", dev]
    if strobe is not None:
        args += link(strobe, name, "strobe", pull="up")
    return args


def imus(n):
    """n ICM-45686s, imu0..imu<n-1>, each turning about Z at its own rate so their
    rotations differ."""
    args = []
    for i in range(n):
        args += ["-device", "icm45686-spi,bus=spi2,cs=%d,id=imu%d,gyro-z=%d" % (10 + i, i, 10000 * (i + 1))]
    return args


def hub(nodes="1/2/3/4", **opts):
    return imus(4) + chain("chain", {0x10: "imu0", 0x20: "imu1", 0x30: "imu2", 0x40: "imu3"},
                           nodes, **opts)


# name: (image, QEMU devices, working sensors, absent sensors, chains, log patterns)
SCENARIOS = {
    "rj45-hub": ("rj45-hub", hub(), [0, 1, 2, 3], [], ["chain"],
                 [r"Found 4 ATtiny CS node\(s\), CS framing: strobe"]),
    # A node that doesn't answer takes out its own sensor, not the chain
    "missing-node": ("rj45-hub", hub("1/2/4"), [0, 1, 3], [2], ["chain"],
                     [r"Found 3 ATtiny CS node\(s\)"]),
    # Flashed with node 5's image at node 2's place: it answers there and works, and the
    # firmware says which board has the wrong image
    "misflashed-node": ("rj45-hub", hub(misflash="2=5"), [0, 1, 2, 3], [], ["chain"],
                        [r"node answering at id 2 reports id 5"]),
    # Protocol v2 nodes are refused, never powered or armed
    "old-nodes": ("rj45-hub", hub(version=2), [], [0, 1, 2, 3], ["chain"],
                  [r"node 1 speaks protocol v2, firmware expects v3"]),
    "empty-cable": ("rj45-hub", hub(""), [], [0, 1, 2, 3], ["chain"],
                    [r"No ATtiny CS nodes answered"]),
    # A local IMU on a host pin beside two chained ones, on the same SPI bus
    "chain-hub": ("chain-hub",
                  imus(3) + link(DIRECT_CS, "imu0", "ssi-gpio-cs", pull="up") +
                  chain("chain", {0x10: "imu1", 0x20: "imu2"}, "1/2"),
                  [0, 1, 2], [], ["chain"], [r"Found 2 ATtiny CS node\(s\)"]),
    # Two IMUs on one node's two channels
    "channels": ("channels", imus(3) + chain("chain", {0x10: "imu0", 0x11: "imu1", 0x20: "imu2"}, "1:2/2"),
                 [0, 1, 2], [], ["chain"], [r"Found 2 ATtiny CS node\(s\)"]),
    # No strobe conductor: every transaction framed by SET_CS frames
    "software-cs": ("software-cs", imus(2) + chain("chain", {0x10: "imu0", 0x20: "imu1"}, "1/2", strobe=None),
                    [0, 1], [], ["chain"], [r"CS framing: software"]),
    # Two named chains on one I2C bus, at 0x13 and 0x14, each with its own strobe
    "two-chains": ("two-chains",
                   imus(4) + chain("left", {0x10: "imu0", 0x20: "imu1"}, "1/2") +
                   chain("right", {0x10: "imu2", 0x20: "imu3"}, "1/2", address=0x14, strobe=STROBE_RIGHT),
                   [0, 1, 2, 3], [], ["left", "right"], []),
}


def qom(node, dev, prop):
    return node.qmp("qom-get", path="/machine/peripheral/" + dev, property=prop)


def run(name, images, work, server):
    image, devices, working, absent, chains, logs = SCENARIOS[name]
    flash = os.path.join(images, image, "flash.bin")
    print("%s (%s)" % (name, image))
    if not check("its image was built", os.path.exists(flash), flash):
        return
    server.reset()
    node = boot("esp32s3-supermini", flash, work, name=name, wifi=True, extra=devices)
    try:
        # The server's word for it: Arduino's USB CDC drops lines now and then
        end = time.time() + 120
        while server.peer is None and time.time() < end and node.proc.poll() is None:
            time.sleep(0.5)
        check("it boots, joins Open Wifi and finds the server", server.peer is not None)
        time.sleep(15)
        n = len(working) + len(absent)
        for sid in working:
            check("sensor %d works (state %s, %d rotations)" % (sid, server.state.get(sid), server.rotations.get(sid, 0)),
                  server.state.get(sid) == SENSOR_OK and server.rotations.get(sid, 0) > 0)
            check("  its IMU's FIFO was read", qom(node, "imu%d" % sid, "frames-read") > 0)
        for sid in absent:
            # Sensor 0 is mandatory: reported, in error. Others missing are left out.
            state = server.state.get(sid)
            check("sensor %d is %s (state %s)" % (sid, "in error" if sid == 0 else "not reported", state),
                  (state == SENSOR_ERROR if sid == 0 else state is None)
                  and server.rotations.get(sid, 0) == 0)
            check("  and the log says it wasn't found",
                  re.search(r"(Mandatory|Optional) sensor %d not found" % (sid + 1), node.log()) is not None)
        fights = {c: qom(node, c, "fights") for c in chains}
        fights.update({"imu%d" % i: qom(node, "imu%d" % i, "fights") for i in range(n)})
        check("never two chip selects at once", not any(fights.values()), fights)
        log = node.log()
        for pattern in logs:
            check("it says so: /%s/" % pattern, re.search(pattern, log) is not None)
        check("it stays connected", "Connection to server timed out" not in log)
        m = FATAL.search(log)
        check("no panic, no reset", m is None, m and m.group(0))
    finally:
        node.stop()


def main():
    images, work = sys.argv[1], sys.argv[2]
    names = sys.argv[3:] or list(SCENARIOS)
    os.makedirs(work, exist_ok=True)
    server = Server()
    server.start()
    try:
        for name in names:
            run(name, images, work, server)
    finally:
        server.running = False
    print("%s: %d failure(s)" % ("PASS" if not fails else "FAIL", fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

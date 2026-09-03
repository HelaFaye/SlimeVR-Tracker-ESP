#!/usr/bin/env python3
"""
Synthetic I2SPI trackers driven by a posable body.

Speaks the SlimeVR UDP tracker protocol directly, so it exercises everything above the
network layer -- discovery, handshake, sensor enumeration, tracker assignment, the
skeleton solve, palm forward kinematics -- with no firmware and no hardware.

It is the complement to sim/run.sh: that one covers everything below the network, this
covers everything above it.

    python3 sim/synthetic_tracker.py --pose t-pose
    python3 sim/synthetic_tracker.py --pose wave --rate 100
    python3 sim/synthetic_tracker.py --list-poses

Wire format taken from src/network/packets.h and connection.cpp on the firmware side, and
checked against UDPPacket.kt on the server side, which is the authoritative consumer.
"""

import argparse
import math
import socket
import struct
import sys
import time

SERVER_PORT = 6969  # ServerConfig.kt: trackerPort

# SendPacketType, src/network/packets.h
PACKET_HEARTBEAT = 0
PACKET_HANDSHAKE = 3
PACKET_SENSOR_INFO = 15
PACKET_ROTATION_DATA = 17

BOARD_SLIMEVR_C5_CHAIN_HUB = 30  # src/consts.h
MCU_ESP32C5 = 0  # unknown to the server; harmless
IMU_ICM45686 = 22  # IMUType id
PROTOCOL_VERSION = 19
FIRMWARE_VERSION = "SlimeVR-Sim"

SENSOR_STATUS_OK = 1
DATA_TYPE_ROTATION = 1

# TrackerPosition ids, TrackerPosition.kt
POSITION = {
    "chest": 2,
    "waist": 3,
    "hip": 4,
    "left_upper_leg": 5,
    "right_upper_leg": 6,
    "left_lower_leg": 7,
    "right_lower_leg": 8,
    "left_foot": 9,
    "right_foot": 10,
    "left_upper_arm": 11,
    "right_upper_arm": 12,
    "left_lower_arm": 13,
    "right_lower_arm": 14,
    "left_hand": 17,
    "right_hand": 18,
}


# --------------------------------------------------------------------- quaternions


def quat_from_euler(pitch, yaw, roll):
    """Degrees, applied Y-X-Z, matching how the poses below are written."""
    p, y, r = (math.radians(a) / 2 for a in (pitch, yaw, roll))
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    cr, sr = math.cos(r), math.sin(r)
    return (
        sp * cy * cr + cp * sy * sr,  # x
        cp * sy * cr - sp * cy * sr,  # y
        cp * cy * sr - sp * sy * cr,  # z
        cp * cy * cr + sp * sy * sr,  # w
    )


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


# -------------------------------------------------------------------------- poses
#
# Each pose maps a body part to (pitch, yaw, roll) in degrees. Anything not listed is
# identity. Animated poses take the elapsed time and return the same shape.


def pose_t_pose(_t):
    return {}


def pose_arms_down(_t):
    return {
        "left_upper_arm": (0, 0, 75),
        "right_upper_arm": (0, 0, -75),
        "left_lower_arm": (0, 0, 75),
        "right_lower_arm": (0, 0, -75),
        "left_hand": (0, 0, 75),
        "right_hand": (0, 0, -75),
    }


def pose_sitting(_t):
    return {
        "left_upper_leg": (-85, 0, 0),
        "right_upper_leg": (-85, 0, 0),
        "left_lower_leg": (85, 0, 0),
        "right_lower_leg": (85, 0, 0),
        "left_upper_arm": (0, 0, 70),
        "right_upper_arm": (0, 0, -70),
        "left_lower_arm": (-45, 0, 70),
        "right_lower_arm": (-45, 0, -70),
        "left_hand": (-45, 0, 70),
        "right_hand": (-45, 0, -70),
    }


def pose_wave(t):
    """Right arm waves. The palm leads the forearm, which is the case that exposes a
    wrongly-parented hand bone."""
    swing = 35 * math.sin(t * 3.0)
    base = pose_arms_down(t)
    base.update(
        {
            "right_upper_arm": (0, 0, -160),
            "right_lower_arm": (0, swing, -160),
            "right_hand": (0, swing * 1.6, -160),
        }
    )
    return base


def pose_walk(t):
    """Legs and arms counter-swinging. Useful for watching foot/hip solve stability."""
    phase = t * 2.4
    leg = 30 * math.sin(phase)
    arm = 20 * math.sin(phase + math.pi)
    return {
        "left_upper_leg": (leg, 0, 0),
        "right_upper_leg": (-leg, 0, 0),
        "left_lower_leg": (max(0.0, -leg * 0.8), 0, 0),
        "right_lower_leg": (max(0.0, leg * 0.8), 0, 0),
        "left_foot": (leg * 0.3, 0, 0),
        "right_foot": (-leg * 0.3, 0, 0),
        "left_upper_arm": (arm, 0, 75),
        "right_upper_arm": (-arm, 0, -75),
        "left_lower_arm": (arm, 0, 75),
        "right_lower_arm": (-arm, 0, -75),
        "left_hand": (arm, 0, 75),
        "right_hand": (-arm, 0, -75),
        "chest": (0, 4 * math.sin(phase), 0),
        "waist": (0, 2 * math.sin(phase), 0),
    }


def pose_palm_twist(t):
    """Rotates only the palms. Everything else is still.

    The point of this one: if the palms move and nothing else does, the arm chain is
    parented correctly and forceArmsFromHMD is doing what we think. If the whole forearm
    swings with them, it isn't.
    """
    twist = 90 * math.sin(t * 1.5)
    base = pose_arms_down(t)
    base["left_hand"] = (0, twist, 75)
    base["right_hand"] = (0, -twist, -75)
    return base


POSES = {
    "t-pose": pose_t_pose,
    "arms-down": pose_arms_down,
    "sitting": pose_sitting,
    "wave": pose_wave,
    "walk": pose_walk,
    "palm-twist": pose_palm_twist,
}


# ------------------------------------------------------------------- the build itself
#
# Five hubs, three sensors each where present. Mirrors
# docs/dev/EXAMPLE-18POINT-BUILD.md: sensor 0 is the hub's own IMU, sensors 1 and 2 are
# I2SPI nodes 1 and 2.

HUBS = [
    ("H1", "02:5C:00:00:00:01", ["chest", "waist", "hip"]),
    ("H2", "02:5C:00:00:00:02", ["left_upper_leg", "left_lower_leg", "left_foot"]),
    ("H3", "02:5C:00:00:00:03", ["right_upper_leg", "right_lower_leg", "right_foot"]),
    ("H4", "02:5C:00:00:00:04", ["left_upper_arm", "left_lower_arm", "left_hand"]),
    ("H5", "02:5C:00:00:00:05", ["right_upper_arm", "right_lower_arm", "right_hand"]),
]


class SyntheticHub:
    """One tracker device: its own UDP socket, its own packet counter, N sensors."""

    def __init__(self, name, mac, parts, server):
        self.name = name
        self.mac = bytes(int(b, 16) for b in mac.split(":"))
        self.parts = parts
        self.server = server
        self.packet_number = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.0)
        self.sock.bind(("0.0.0.0", 0))

    # -- framing. Header is 4 bytes of big-endian packet type then 8 of packet number.
    def _send(self, packet_type, body):
        header = struct.pack(">IQ", packet_type, self.packet_number)
        self.packet_number += 1
        self.sock.sendto(header + body, self.server)

    @staticmethod
    def _short_string(text):
        raw = text.encode("ascii")
        return bytes([len(raw)]) + raw

    def send_handshake(self):
        body = struct.pack(
            ">iiiiiii",
            BOARD_SLIMEVR_C5_CHAIN_HUB,
            IMU_ICM45686,
            MCU_ESP32C5,
            0,
            0,
            0,  # legacy IMU info, ignored by the server
            PROTOCOL_VERSION,
        )
        body += self._short_string(FIRMWARE_VERSION)
        body += self.mac
        self._send(PACKET_HANDSHAKE, body)

    def send_sensor_info(self):
        for sensor_id, part in enumerate(self.parts):
            body = struct.pack(
                ">BBBHBBB",
                sensor_id,
                SENSOR_STATUS_OK,
                IMU_ICM45686,
                0,  # sensor config bits
                1,  # rest calibration complete
                POSITION[part],
                DATA_TYPE_ROTATION,
            )
            self._send(PACKET_SENSOR_INFO, body)

    def send_rotations(self, rotations):
        for sensor_id, part in enumerate(self.parts):
            x, y, z, w = rotations[part]
            body = struct.pack(">BBffffB", sensor_id, 1, x, y, z, w, 0)
            self._send(PACKET_ROTATION_DATA, body)

    def send_heartbeat(self):
        self._send(PACKET_HEARTBEAT, b"")

    def drain(self):
        """Consume anything the server sends back so the socket buffer doesn't fill."""
        try:
            while True:
                self.sock.recvfrom(2048)
        except (BlockingIOError, OSError):
            pass


def build_rotations(pose_fn, elapsed):
    """Every part gets a rotation; unposed parts are identity."""
    posed = pose_fn(elapsed)
    out = {}
    for part in POSITION:
        angles = posed.get(part)
        out[part] = quat_from_euler(*angles) if angles else (0.0, 0.0, 0.0, 1.0)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1", help="SlimeVR server address")
    ap.add_argument("--port", type=int, default=SERVER_PORT)
    ap.add_argument("--pose", default="arms-down", choices=sorted(POSES))
    ap.add_argument("--rate", type=int, default=100, help="rotation packets per second")
    ap.add_argument("--duration", type=float, default=0.0, help="0 = run until Ctrl-C")
    ap.add_argument("--list-poses", action="store_true")
    args = ap.parse_args()

    if args.list_poses:
        for name, fn in sorted(POSES.items()):
            summary = (fn.__doc__ or "static pose").strip().split("\n")[0]
            print(f"  {name:<12} {summary}")
        return 0

    server = (args.host, args.port)
    hubs = [SyntheticHub(n, m, p, server) for n, m, p in HUBS]

    sensors = sum(len(h.parts) for h in hubs)
    print(f"{len(hubs)} hubs, {sensors} sensors -> {args.host}:{args.port}")
    print(f"pose '{args.pose}' at {args.rate} Hz. Ctrl-C to stop.\n")

    for hub in hubs:
        hub.send_handshake()
    time.sleep(0.4)  # let the server register the devices before enumerating sensors
    for hub in hubs:
        hub.send_sensor_info()
        print(f"  {hub.name}: {', '.join(hub.parts)}")
    print()

    pose_fn = POSES[args.pose]
    period = 1.0 / args.rate
    start = time.monotonic()
    last_heartbeat = start
    last_report = start
    packets = 0

    try:
        while True:
            now = time.monotonic()
            elapsed = now - start
            if args.duration and elapsed >= args.duration:
                break

            rotations = build_rotations(pose_fn, elapsed)
            for hub in hubs:
                hub.send_rotations(rotations)
                hub.drain()
            packets += sensors

            if now - last_heartbeat >= 1.0:
                for hub in hubs:
                    hub.send_heartbeat()
                last_heartbeat = now

            if now - last_report >= 5.0:
                print(
                    f"  {elapsed:6.1f}s  {packets} rotation packets "
                    f"({packets / elapsed:.0f}/s)"
                )
                last_report = now

            time.sleep(max(0.0, period - (time.monotonic() - now)))
    except KeyboardInterrupt:
        print("\nstopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())

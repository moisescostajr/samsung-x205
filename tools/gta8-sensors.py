#!/usr/bin/env python3
"""Auto-rotate and auto-brightness for gta8wifi from the Unisoc sensor hub.

IIO records from sprd-sensor are 32-byte little-endian:
  u16 magic, u16 sensor_id, u32 pad, f32 x, f32 y, f32 z, padding...
Sensor ids: 1=accel (m/s^2), 2=mag, 4=gyro, 5=light.
"""
import math
import os
import struct
import subprocess
import time

IIO = "/dev/iio:device0"
BL = "/sys/class/backlight/sprd_backlight/brightness"
BL_MAX_PATH = "/sys/class/backlight/sprd_backlight/max_brightness"
MANUAL = "/run/gta8-brightness-manual"
MANUAL_HOLD = 300.0  # QS slider wins for 5 minutes after a manual set
REC = 32
ACC_ID = 1
LIGHT_ID = 5
G_THRESH = 6.0  # m/s^2; ignore near-flat
HOLD_SEC = 0.45
ROT_EVERY = 0.35
BL_EVERY = 0.8

# With the panel at Phosh's stock transform=270, gravity sits on +X.
# Map that body frame onto wlr-randr transforms.
def transform_from_acc(x, y, z):
    if abs(z) > abs(x) and abs(z) > abs(y) and abs(z) > G_THRESH:
        return None  # lying flat: keep current
    if abs(x) >= abs(y):
        return "270" if x >= 0 else "90"
    return "normal" if y >= 0 else "180"


def env_wayland():
    os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/0")
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    runtime = os.environ["XDG_RUNTIME_DIR"]
    try:
        for name in os.listdir(runtime):
            if name.startswith("wayland-") and not name.endswith(".lock"):
                os.environ["WAYLAND_DISPLAY"] = name
                return True
    except OSError:
        pass
    return False


def set_transform(next_t):
    if not env_wayland():
        return False
    r = subprocess.run(
        ["wlr-randr", "--output", "DSI-1", "--transform", next_t],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def lux_to_brightness(lux, bl_max):
    # STK reports a raw/lux-ish value; keep a usable floor in the dark.
    if lux <= 0:
        return None
    n = math.log10(lux + 1.0) / math.log10(10001.0)
    return max(12, min(bl_max, int(12 + n * (bl_max - 12))))


def main():
    bl_max = 255
    try:
        bl_max = int(open(BL_MAX_PATH).read().strip())
    except OSError:
        pass

    fd = os.open(IIO, os.O_RDONLY)
    cur = None
    pending = None
    pending_since = 0.0
    last_rot = 0.0
    last_bl = 0.0
    buf = b""

    while True:
        chunk = os.read(fd, REC * 16)
        if not chunk:
            time.sleep(0.05)
            continue
        buf += chunk
        now = time.monotonic()
        while len(buf) >= REC:
            rec, buf = buf[:REC], buf[REC:]
            _magic, sid = struct.unpack_from("<HH", rec, 0)
            if rec[4:8] != b"\xef\xef\xef\xef":
                continue
            x, y, z = struct.unpack_from("<fff", rec, 8)
            if sid == ACC_ID and now - last_rot >= ROT_EVERY:
                nxt = transform_from_acc(x, y, z)
                if nxt is None:
                    pending = None
                elif nxt == cur:
                    pending = None
                elif nxt != pending:
                    pending = nxt
                    pending_since = now
                elif now - pending_since >= HOLD_SEC:
                    if set_transform(nxt):
                        cur = nxt
                    pending = None
                    last_rot = now
            elif sid == LIGHT_ID and now - last_bl >= BL_EVERY:
                last_bl = now
                try:
                    age = time.time() - os.stat(MANUAL).st_mtime
                    if age < MANUAL_HOLD:
                        continue
                except OSError:
                    pass
                lux = x
                b = lux_to_brightness(lux, bl_max)
                if b is not None:
                    try:
                        open(BL, "w").write(str(b))
                    except OSError:
                        pass


if __name__ == "__main__":
    main()

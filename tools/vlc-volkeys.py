#!/usr/bin/env python3
"""While VLC is up, volume rocker skips playlist items instead of Pulse volume.

gpio-keys also carries KEY_POWER, so the device is grabbed and power is
replayed through uinput for Phosh. Headset keys are left alone.
"""
import fcntl
import os
import struct
import subprocess
import sys

EV_SYN, EV_KEY = 0, 1
SYN_REPORT = 0
KEY_VOLUMEDOWN, KEY_VOLUMEUP, KEY_POWER = 114, 115, 116
EVENT_FMT = "llHHi"
EVENT_SZ = struct.calcsize(EVENT_FMT)

# ioctl('E', ...) / ioctl('U', ...)
EVIOCGRAB = 0x40044590
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_SETUP = 0x405C5503  # sizeof(struct uinput_setup) == 92


def mpris(method):
    subprocess.call(
        [
            "dbus-send",
            "--session",
            "--type=method_call",
            "--dest=org.mpris.MediaPlayer2.vlc",
            "/org/mpris/MediaPlayer2",
            "org.mpris.MediaPlayer2.Player." + method,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def open_uinput():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_KEYBIT, KEY_POWER)
    # struct uinput_setup { input_id id; char name[80]; unsigned ff_effects_max; }
    setup = struct.pack("HHHH", 0x06, 0, 0, 1) + b"gta8-power\0".ljust(80, b"\0")
    setup += struct.pack("I", 0)
    fcntl.ioctl(fd, UI_DEV_SETUP, setup)
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd


def emit(fd, evtype, code, value):
    os.write(fd, struct.pack(EVENT_FMT, 0, 0, evtype, code, value))


def main():
    src = os.open("/dev/input/event4", os.O_RDONLY)
    fcntl.ioctl(src, EVIOCGRAB, 1)
    ufd = open_uinput()
    try:
        while True:
            buf = os.read(src, EVENT_SZ)
            if len(buf) != EVENT_SZ:
                break
            _s, _us, evtype, code, value = struct.unpack(EVENT_FMT, buf)
            if evtype != EV_KEY:
                continue
            if code == KEY_POWER:
                emit(ufd, EV_KEY, KEY_POWER, value)
                emit(ufd, EV_SYN, SYN_REPORT, 0)
                continue
            if value != 1:
                continue
            if code == KEY_VOLUMEUP:
                mpris("Next")
            elif code == KEY_VOLUMEDOWN:
                mpris("Previous")
    finally:
        try:
            fcntl.ioctl(ufd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(ufd)
        try:
            fcntl.ioctl(src, EVIOCGRAB, 0)
        except OSError:
            pass
        os.close(src)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

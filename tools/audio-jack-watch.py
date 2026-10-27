#!/usr/bin/python3
"""Switch the audio route when the headset jack is plugged or unplugged.

The SC2730 codec exposes "sprdphone-sc2730 Headset Jack" as an input device
carrying SW_HEADPHONE_INSERT. Android's audio HAL would apply a different
mixer path per output; here audio-up.sh does that, so all this has to do is
call it with spk or hp.
"""
import fcntl
import os
import struct
import subprocess
import sys

EVENT_SIZE = 24          # 2x64-bit timeval + u16 type + u16 code + s32 value
EV_SW = 0x05
SW_HEADPHONE_INSERT = 0x02
SW_LINEOUT_INSERT = 0x06
AUDIO_UP = "/root/audio-up.sh"
JACK_NAME = "sprdphone-sc2730 Headset Jack"


def find_jack() -> str | None:
    base = "/sys/class/input"
    for entry in sorted(os.listdir(base)):
        if not entry.startswith("event"):
            continue
        try:
            with open(f"{base}/{entry}/device/name") as f:
                if f.read().strip() == JACK_NAME:
                    return f"/dev/input/{entry}"
        except OSError:
            continue
    return None


def current_state(fd: int) -> bool:
    # EVIOCGSW(len): dir=read(2), type='E', nr=0x1b
    nbytes = 8
    req = (2 << 30) | (nbytes << 16) | (0x45 << 8) | 0x1B
    buf = bytearray(nbytes)
    try:
        fcntl.ioctl(fd, req, buf, True)
    except OSError:
        return False
    bits = int.from_bytes(buf, "little")
    return bool(bits & (1 << SW_HEADPHONE_INSERT))


def apply(route: str) -> None:
    print(f"route -> {route}", flush=True)
    subprocess.run(["/bin/busybox", "sh", AUDIO_UP, route], check=False)


def main() -> int:
    path = find_jack()
    if not path:
        print(f"no input device named {JACK_NAME!r}", file=sys.stderr)
        return 1

    fd = os.open(path, os.O_RDONLY)
    plugged = current_state(fd)
    apply("hp" if plugged else "spk")

    while True:
        data = os.read(fd, EVENT_SIZE)
        if len(data) < EVENT_SIZE:
            continue
        _, _, etype, code, value = struct.unpack("qqHHi", data)
        if etype != EV_SW or code not in (SW_HEADPHONE_INSERT, SW_LINEOUT_INSERT):
            continue
        new = bool(value)
        if new == plugged:
            continue
        plugged = new
        apply("hp" if plugged else "spk")


if __name__ == "__main__":
    raise SystemExit(main())

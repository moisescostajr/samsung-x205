#!/usr/bin/python3
"""Load the Unisoc audio DSP firmware and release it from reset.

Android's modem_control does this at boot: it streams the l_agdsp partition
(6 MiB; mmcblk0p52 on gta8wifi, mmcblk0p55 on gta8 LTE) into
/sys/devices/platform/audiocp_boot/agdsp in 4 KiB chunks, then writes to
.../start. Without it the AGCP stays powered down (PD_AUDCP_DSP_STATE: 0)
and every VBC scene times out waiting on the DSP.
"""
import os
import struct
import sys
import time

BOOT = "/sys/devices/platform/audiocp_boot"
CHUNK = 4096


def find_agdsp() -> str:
    base = "/sys/block/mmcblk0"
    try:
        names = os.listdir(base)
    except OSError:
        names = []
    for name in names:
        if not name.startswith("mmcblk0p"):
            continue
        try:
            with open(f"{base}/{name}/uevent", encoding="ascii", errors="replace") as f:
                for line in f:
                    if line.strip() == "PARTNAME=l_agdsp":
                        return f"/dev/{name}"
        except OSError:
            continue
    return "/dev/mmcblk0p52"


def ldinfo() -> tuple[str, int, int]:
    with open(f"{BOOT}/ldinfo", "rb") as f:
        raw = f.read()
    # struct load_node_info { char name[0x20]; u32 load_phy_addr; u32 size; }
    name = raw[:32].split(b"\x00")[0].decode("ascii", "replace")
    addr, size = struct.unpack_from("<II", raw, 32)
    return name, addr, size


def status() -> tuple[int, int, int]:
    with open(f"{BOOT}/status", "rb") as f:
        raw = f.read(12)
    return struct.unpack("<III", raw)


def main() -> int:
    name, addr, size = ldinfo()
    print(f"ldinfo name={name} load_phy_addr=0x{addr:x} size=0x{size:x}")
    print("status before (core,sys,sleep) =", status())

    fw = find_agdsp()
    with open(fw, "rb") as src:
        image = src.read(size)
    if len(image) < size:
        print(f"firmware short: {len(image)} < {size} from {fw}", file=sys.stderr)
        return 1
    print(f"loaded {len(image)} bytes from {fw}")

    # A second store in the same boot writes 0 bytes unless we reset ppos.
    try:
        with open(f"{BOOT}/stop", "w") as f:
            f.write("1")
        time.sleep(0.2)
    except OSError as e:
        print(f"stop: {e}")

    written = 0
    with open(f"{BOOT}/agdsp", "wb", buffering=0) as dst:
        for off in range(0, len(image), CHUNK):
            written += dst.write(image[off:off + CHUNK])
    print(f"wrote {written} bytes to {BOOT}/agdsp")
    if written < size:
        print(f"short write {written} < {size} (ppos stuck; reboot needed)", file=sys.stderr)
        return 1

    with open(f"{BOOT}/start", "w") as f:
        f.write("1")
    print("start written")

    st = (0, 0, 0)
    for _ in range(10):
        time.sleep(0.3)
        st = status()
        print("status", st)
        if st[0] or st[1]:
            return 0
    print("DSP did not leave reset", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

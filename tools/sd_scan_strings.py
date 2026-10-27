#!/usr/bin/env python3
"""Scan a raw ext partition for gta8 debug strings and leftover inodes."""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

NEEDLES = [
    b"dmesg-v27",
    b"booted-v27",
    b"netifs-v27",
    b"ifconfig-v27",
    b"udc-v27",
    b"dmesg-v26",
    b"dmesg-v28",
    b"172.16.42",
    b"sprd-wdt-fiq",
    b"musb-hdrc",
    b"gta8-v27",
    b"gta8-v26",
    b"gta8-v28",
    b"switch_root",
    b"Phosh",
    b"Debian GNU",
    b"usb0",
]


def pread(fd: int, off: int, n: int) -> bytes:
    align = 512
    aligned_off = off - (off % align)
    skip = off - aligned_off
    aligned_n = skip + n
    if aligned_n % align:
        aligned_n += align - (aligned_n % align)
    got = b""
    while len(got) < aligned_n:
        chunk = os.pread(fd, aligned_n - len(got), aligned_off + len(got))
        if not chunk:
            break
        got += chunk
    return got[skip : skip + n]


def dump_symlinks(fd: int, dest: Path) -> None:
    # Reuse the extractor’s inode table location: group0 itable at block 5, 4k, inode 256.
    block = 4096
    itable = 5 * block
    lines = []
    for ino in (12, 13, 14, 15):
        raw = pread(fd, itable + (ino - 1) * 256, 256)
        mode, uid, size = struct.unpack_from("<HHI", raw, 0)
        target = raw[0x28 : 0x28 + min(size, 60)]
        lines.append(f"ino{ino} mode={oct(mode)} size={size} target={target!r}")
        (dest / f"ino{ino}.raw").write_bytes(raw)
    (dest / "symlinks.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def scan(fd: int, dest: Path, size: int) -> None:
    hits_path = dest / "string-hits.txt"
    chunk = 8 * 1024 * 1024
    overlap = 256
    prev = b""
    found = 0
    off = 0
    with hits_path.open("w", encoding="utf-8") as out:
        while off < size:
            n = min(chunk, size - off)
            data = pread(fd, off, n)
            if not data:
                break
            window = prev + data
            window_base = off - len(prev)
            for needle in NEEDLES:
                start = 0
                while True:
                    i = window.find(needle, start)
                    if i < 0:
                        break
                    abs_off = window_base + i
                    ctx = window[max(0, i - 80) : i + len(needle) + 120]
                    safe = ctx.decode("utf-8", "replace").replace("\n", "\\n")
                    line = f"{abs_off:#x} {needle.decode()} :: {safe}\n"
                    out.write(line)
                    out.flush()
                    print(line.rstrip())
                    found += 1
                    start = i + 1
            prev = data[-overlap:] if len(data) >= overlap else data
            off += len(data)
            if off % (64 * 1024 * 1024) == 0:
                print(f"... scanned {off / (1024*1024):.0f} MiB, hits={found}", flush=True)
    print(f"scan done hits={found}")


def main() -> int:
    src = sys.argv[1]
    dest = Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)
    fd = os.open(src, os.O_RDONLY)
    try:
        size = os.lseek(fd, 0, os.SEEK_END)
        print("device size", size)
        dump_symlinks(fd, dest)
        scan(fd, dest, size)
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

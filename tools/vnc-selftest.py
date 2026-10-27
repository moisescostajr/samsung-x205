#!/usr/bin/env python3
"""Drive the tablet's VNC the way Screen Sharing does and decode the result.

    python3 tools/vnc-selftest.py 127.0.0.1 5900 "$VNC_PASSWORD" /tmp/shot.png

Decoding every update catches the failure a viewer only reports as "cannot
communicate": a server that restarts its ZRLE zlib stream per frame looks
fine on frame one and produces nothing afterwards.
"""
from __future__ import annotations

import os
import socket
import struct
import sys
import time
import zlib
from importlib.machinery import SourceFileLoader
from pathlib import Path

TILE = 64

_des = SourceFileLoader(
    "vncdes", str(Path(__file__).with_name("vnc-des-proxy.py"))
).load_module()


def recvall(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"eof after {len(buf)}/{n}")
        buf += chunk
    return buf


def blit_zrle(fb: bytearray, fw: int, x0: int, y0: int, rw: int, rh: int, data: bytes) -> int:
    """Paint one ZRLE rect (raw subencoding, 3-byte CPIXEL = B,G,R)."""
    pos = 0
    for ty in range(y0, y0 + rh, TILE):
        th = min(TILE, y0 + rh - ty)
        for tx in range(x0, x0 + rw, TILE):
            tw = min(TILE, x0 + rw - tx)
            sub = data[pos]
            pos += 1
            if sub != 0:
                raise RuntimeError(f"unsupported ZRLE subencoding {sub}")
            for row in range(th):
                span = tw * 3
                src = data[pos : pos + span]
                pos += span
                off = ((ty + row) * fw + tx) * 3
                fb[off + 0 : off + span : 3] = src[2::3]
                fb[off + 1 : off + span : 3] = src[1::3]
                fb[off + 2 : off + span : 3] = src[0::3]
    return pos


def blit_raw(fb: bytearray, fw: int, x0: int, y0: int, rw: int, rh: int, data: bytes) -> None:
    """Paint one Raw rect of little-endian 32 bpp pixels (B,G,R,x on the wire)."""
    for row in range(rh):
        src = data[row * rw * 4 : (row + 1) * rw * 4]
        off = ((y0 + row) * fw + x0) * 3
        span = rw * 3
        fb[off + 0 : off + span : 3] = src[2::4]
        fb[off + 1 : off + span : 3] = src[1::4]
        fb[off + 2 : off + span : 3] = src[0::4]


def read_update(sock, inflate, fb, fw) -> tuple[int, int]:
    hdr = recvall(sock, 4)
    if hdr[0] != 0:
        raise RuntimeError(f"expected FramebufferUpdate, got message type {hdr[0]}")
    nrects = struct.unpack(">H", hdr[2:4])[0]
    decoded = 0
    for _ in range(nrects):
        x, y, w, h, enc = struct.unpack(">HHHHi", recvall(sock, 12))
        if enc == 0:
            data = recvall(sock, w * h * 4)
            decoded += len(data)
            blit_raw(fb, fw, x, y, w, h, data)
        elif enc == 16:
            ln = struct.unpack(">I", recvall(sock, 4))[0]
            data = inflate.decompress(recvall(sock, ln))
            decoded += len(data)
            blit_zrle(fb, fw, x, y, w, h, data)
        else:
            raise RuntimeError(f"unhandled encoding {enc}")
    return nrects, decoded


def write_png(path: str, width: int, height: int, rgb: bytes) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgb[y * width * 3 : (y + 1) * width * 3]

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    Path(path).write_bytes(png)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    host = args[0] if args else "127.0.0.1"
    port = int(args[1]) if len(args) > 1 else 5900
    password = args[2] if len(args) > 2 else os.environ.get("VNC_PASSWORD", "")
    if not password:
        print("pass the VNC password as argv[3] or set VNC_PASSWORD", file=sys.stderr)
        return 2
    shot = args[3] if len(args) > 3 else ""
    # --raw talks to servers whose ZRLE uses subencodings this tool cannot
    # decode; it is only meant for eyeballing one frame.
    encs = [0] if "--raw" in flags else [16, 7, 5, 0, -223, -224, -239, -240, 21, 1]
    rounds = 1 if "--raw" in flags else 3

    sock = socket.create_connection((host, port), 8)
    sock.settimeout(60)
    print("version:", recvall(sock, 12).strip().decode())
    sock.sendall(b"RFB 003.008\n")

    types = list(recvall(sock, recvall(sock, 1)[0]))
    print("security types:", types)
    if "--no-auth" in flags:
        if 1 not in types:
            raise RuntimeError("server does not offer None auth (type 1)")
        sock.sendall(bytes([1]))
    else:
        if 2 not in types:
            raise RuntimeError("server does not offer VNC auth (type 2)")
        sock.sendall(bytes([2]))
        sock.sendall(_des.vnc_encrypt_challenge(recvall(sock, 16), password))
    result = struct.unpack(">I", recvall(sock, 4))[0]
    print("auth result:", result)
    if result != 0:
        raise RuntimeError("authentication rejected")

    sock.sendall(b"\x01")  # ClientInit, shared
    init = recvall(sock, 24)
    width, height = struct.unpack(">HH", init[:4])
    name = recvall(sock, struct.unpack(">I", init[20:24])[0])
    print(f"ServerInit: {width}x{height} {name!r} pf={init[4:20].hex()}")

    # Screen Sharing sets its own 32-bit format and a long encoding list.
    apple_pf = bytes([32, 24, 0, 1, 0, 0xFF, 0, 0xFF, 0, 0xFF, 16, 8, 0, 0, 0, 0])
    sock.sendall(bytes([0, 0, 0, 0]) + apple_pf)
    sock.sendall(
        bytes([2, 0]) + struct.pack(">H", len(encs)) + struct.pack(f">{len(encs)}i", *encs)
    )

    # --move/--press exercise input injection; the screenshot then shows
    # whether the compositor acted on it.
    for flag in flags:
        if flag.startswith("--move="):
            mx, my = (int(v) for v in flag.split("=", 1)[1].split(","))
            sock.sendall(bytes([5, 0]) + struct.pack(">HH", mx, my))
            print(f"moved pointer to {mx},{my}")
        elif flag.startswith("--click="):
            mx, my = (int(v) for v in flag.split("=", 1)[1].split(","))
            sock.sendall(bytes([5, 0]) + struct.pack(">HH", mx, my))
            time.sleep(0.2)
            sock.sendall(bytes([5, 1]) + struct.pack(">HH", mx, my))
            time.sleep(0.1)
            sock.sendall(bytes([5, 0]) + struct.pack(">HH", mx, my))
            print(f"clicked {mx},{my}")
        elif flag.startswith("--press="):
            keysym = int(flag.split("=", 1)[1], 0)
            sock.sendall(bytes([4, 1, 0, 0]) + struct.pack(">I", keysym))
            time.sleep(0.2)
            sock.sendall(bytes([4, 0, 0, 0]) + struct.pack(">I", keysym))
            print(f"pressed keysym 0x{keysym:04x}")
        elif flag.startswith("--type="):
            text = flag.split("=", 1)[1]
            for ch in text:
                # For printable ASCII the keysym is the code point; \n is Return.
                keysym = 0xFF0D if ch == "\n" else ord(ch)
                sock.sendall(bytes([4, 1, 0, 0]) + struct.pack(">I", keysym))
                time.sleep(0.03)
                sock.sendall(bytes([4, 0, 0, 0]) + struct.pack(">I", keysym))
                time.sleep(0.03)
            print(f"typed {text!r}")
    if any(f.startswith(("--move=", "--press=", "--click=", "--type=")) for f in flags):
        time.sleep(1.0)

    fb = bytearray(width * height * 3)
    inflate = zlib.decompressobj()
    for i in range(rounds):
        started = time.time()
        sock.sendall(bytes([3, 1 if i else 0]) + struct.pack(">HHHH", 0, 0, width, height))
        nrects, decoded = read_update(sock, inflate, fb, width)
        print(
            f"update {i + 1}: rects={nrects} decoded={decoded}B "
            f"in {time.time() - started:.1f}s"
        )
        if decoded == 0:
            raise RuntimeError("update decoded to nothing (zlib stream restarted?)")

    sock.close()
    if shot:
        write_png(shot, width, height, bytes(fb))
        print("wrote", shot)
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

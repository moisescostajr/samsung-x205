#!/usr/bin/python3
"""RFB 3.8 frontend that speaks classic VNC Authentication (type 2 / DES).

wayvnc 0.5 can only offer None or VeNCrypt. macOS Screen Sharing.app needs
type 2, so this process authenticates the client then splices the session
onto a localhost wayvnc that has no auth.
"""
from __future__ import annotations

import os
import secrets
import select
import socket
import struct
import subprocess
import sys
import threading
import time

_BACKEND_LOCK = threading.Lock()
_WAYVNC_ENV_FILE = "/run/gta8-vnc.env"
_WAYVNC_CFG = "/etc/wayvnc-localhost.conf"
_WAYVNC_CMD = [
    "python3",
    "/root/grim-vnc.py",
]


def _wayvnc_env() -> dict[str, str]:
    env = os.environ.copy()
    try:
        with open(_WAYVNC_ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                env[key] = val
    except FileNotFoundError:
        pass
    return env


def _backend_listening() -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", 5901), 0.2)
        s.close()
        return True
    except OSError:
        return False


def ensure_backend() -> None:
    """Start the screen server once, and leave a running one alone.

    This used to kill and relaunch per client, because wayvnc 0.5 served only
    the first session. grim-vnc threads per client, so restarting now just
    drops whoever is already watching — and a retrying viewer kills itself.
    """
    if _backend_listening():
        return
    log = open("/root/wayvnc.log", "ab", buffering=0)
    subprocess.Popen(
        _WAYVNC_CMD,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=_wayvnc_env(),
    )
    for _ in range(30):
        if _backend_listening():
            return
        time.sleep(0.1)
    raise RuntimeError("screen server did not listen on 5901")


# --- DES ECB (encrypt only), enough for RFB type-2 ---
# Test vector: key 133457799BBCDFF1  plain 0123456789ABCDEF
# cipher 85E813540F0AB405

_IP = (
    58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4,
    62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8,
    57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
    61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7,
)
_FP = (
    40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31,
    38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29,
    36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27,
    34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25,
)
_E = (
    32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9, 8, 9, 10, 11, 12, 13,
    12, 13, 14, 15, 16, 17, 16, 17, 18, 19, 20, 21, 20, 21, 22, 23,
    24, 25, 24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1,
)
_P = (
    16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10,
    2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25,
)
_PC1 = (
    57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18,
    10, 2, 59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36,
    63, 55, 47, 39, 31, 23, 15, 7, 62, 54, 46, 38, 30, 22,
    14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 28, 20, 12, 4,
)
_PC2 = (
    14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10,
    23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2,
    41, 52, 31, 37, 47, 55, 30, 40, 51, 45, 33, 48,
    44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32,
)
_SHIFTS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)
_SBOX = (
    (
        14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7,
        0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8,
        4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0,
        15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13,
    ),
    (
        15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10,
        3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5,
        0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15,
        13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9,
    ),
    (
        10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8,
        13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1,
        13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7,
        1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12,
    ),
    (
        7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15,
        13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9,
        10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4,
        3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14,
    ),
    (
        2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9,
        14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6,
        4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14,
        11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3,
    ),
    (
        12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11,
        10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8,
        9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6,
        4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13,
    ),
    (
        4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1,
        13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6,
        1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2,
        6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12,
    ),
    (
        13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7,
        1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2,
        7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8,
        2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11,
    ),
)


def _permute(value: int, table: tuple[int, ...], nbits: int) -> int:
    out = 0
    for bit in table:
        out = (out << 1) | ((value >> (nbits - bit)) & 1)
    return out


def _rotate_left(value: int, bits: int, width: int = 28) -> int:
    return ((value << bits) | (value >> (width - bits))) & ((1 << width) - 1)


def _sbox(value: int) -> int:
    out = 0
    for i in range(8):
        chunk = (value >> (42 - 6 * i)) & 0x3F
        row = ((chunk & 0x20) >> 4) | (chunk & 1)
        col = (chunk >> 1) & 0x0F
        out = (out << 4) | _SBOX[i][row * 16 + col]
    return out


def _subkeys(key8: bytes) -> list[int]:
    key = int.from_bytes(key8, "big")
    cd = _permute(key, _PC1, 64)
    c, d = cd >> 28, cd & 0x0FFFFFFF
    keys = []
    for s in _SHIFTS:
        c = _rotate_left(c, s)
        d = _rotate_left(d, s)
        keys.append(_permute((c << 28) | d, _PC2, 56))
    return keys


def des_encrypt_block(block8: bytes, key8: bytes) -> bytes:
    keys = _subkeys(key8)
    ip = _permute(int.from_bytes(block8, "big"), _IP, 64)
    l, r = ip >> 32, ip & 0xFFFFFFFF
    for k in keys:
        expanded = _permute(r, _E, 32)
        f = _permute(_sbox(expanded ^ k), _P, 32)
        l, r = r, l ^ f
    return _permute((r << 32) | l, _FP, 64).to_bytes(8, "big")


def _bit_reverse_byte(b: int) -> int:
    return int(f"{b:08b}"[::-1], 2)


def vnc_des_key(password: str) -> bytes:
    raw = password.encode("latin-1", "replace")[:8]
    raw = raw + b"\x00" * (8 - len(raw))
    return bytes(_bit_reverse_byte(b) for b in raw)


def vnc_encrypt_challenge(challenge: bytes, password: str) -> bytes:
    key = vnc_des_key(password)
    return des_encrypt_block(challenge[:8], key) + des_encrypt_block(challenge[8:], key)


def _selftest() -> None:
    cipher = des_encrypt_block(
        bytes.fromhex("0123456789ABCDEF"),
        bytes.fromhex("133457799BBCDFF1"),
    )
    assert cipher == bytes.fromhex("85E813540F0AB405"), cipher.hex()


# --- RFB ---

def recvall(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("eof")
        buf += chunk
    return buf


def handshake_wayvnc(host: str, port: int) -> socket.socket:
    s = socket.create_connection((host, port), timeout=8)
    s.settimeout(20)
    ver = recvall(s, 12)
    if not ver.startswith(b"RFB "):
        raise RuntimeError(f"bad wayvnc version {ver!r}")
    s.sendall(b"RFB 003.008\n")
    ntypes = recvall(s, 1)[0]
    types = recvall(s, ntypes)
    if 1 not in types:
        raise RuntimeError(f"wayvnc has no None auth, types={list(types)}")
    s.sendall(bytes([1]))
    result = struct.unpack(">I", recvall(s, 4))[0]
    if result != 0:
        raise RuntimeError(f"wayvnc None auth failed {result}")
    return s


def handshake_client(client: socket.socket, password: str) -> None:
    client.settimeout(30)
    client.sendall(b"RFB 003.008\n")
    ver = recvall(client, 12)
    if not ver.startswith(b"RFB "):
        raise RuntimeError(f"bad client version {ver!r}")
    # 3.3 uses a 4-byte security type and no client selection. Apple Screen
    # Sharing has used both 3.3 and 3.8 depending on macOS version.
    is_33 = ver.startswith(b"RFB 003.003")
    if is_33:
        client.sendall(struct.pack(">I", 2))
    else:
        client.sendall(bytes([1, 2]))
        chosen = recvall(client, 1)[0]
        if chosen != 2:
            client.sendall(struct.pack(">I", 1))
            raise RuntimeError(f"client picked security type {chosen}")
    challenge = secrets.token_bytes(16)
    client.sendall(challenge)
    response = recvall(client, 16)
    expected = vnc_encrypt_challenge(challenge, password)
    if response != expected:
        client.sendall(struct.pack(">I", 1))
        if not is_33:
            reason = b"Authentication failed"
            client.sendall(struct.pack(">I", len(reason)) + reason)
        raise RuntimeError("bad password")
    client.sendall(struct.pack(">I", 0))


def splice(a: socket.socket, b: socket.socket) -> None:
    """Filter client→server RFB; pass server→client through.

    wayvnc 0.5 stack-smashes on Apple Screen Sharing's long SetEncodings list.
    """
    a.settimeout(None)
    b.settimeout(None)
    client, backend = a, b
    cbuf = b""
    try:
        while True:
            readable, _, exceptional = select.select([client, backend], [], [client, backend], 120)
            if exceptional:
                break
            if not readable:
                continue
            if backend in readable:
                data = backend.recv(65536)
                if not data:
                    return
                client.sendall(data)
            if client in readable:
                data = client.recv(65536)
                if not data:
                    return
                cbuf += data
                while True:
                    msg, cbuf = _pop_client_msg(cbuf)
                    if msg is None:
                        break
                    backend.sendall(msg)
    finally:
        for s in (client, backend):
            try:
                s.close()
            except OSError:
                pass


# The crash was Apple's long encoding list, not ZRLE/Tight themselves.
# Raw-only 1200x1920 frames are ~9 MiB and Screen Sharing gives up.
#
# The pseudo-encodings must survive the filter: wayvnc refuses any client
# that cannot be told the desktop size ("Client does not support desktop
# resizing"), which it announces through -223/-308.
_SAFE_ENCODINGS = (
    16,    # ZRLE
    7,     # Tight
    5,     # Hextile
    0,     # Raw
    -223,  # DesktopSize
    -308,  # ExtendedDesktopSize
    -224,  # LastRect
)


def _pop_client_msg(buf: bytes) -> tuple[bytes | None, bytes]:
    if not buf:
        return None, buf
    t = buf[0]
    if t == 0:  # SetPixelFormat — Apple's 32-bit format also crashes 0.5.
        if len(buf) < 20:
            return None, buf
        pf = bytes([
            32, 24, 0, 1,
            0, 0xff, 0, 0xff, 0, 0xff,
            16, 8, 0,
            0, 0, 0,
        ])
        print("rewrite SetPixelFormat", buf[4:20].hex(), "->", pf.hex(), flush=True)
        return bytes([0, 0, 0, 0]) + pf, buf[20:]
    if t == 2:  # SetEncodings
        if len(buf) < 4:
            return None, buf
        n = struct.unpack(">H", buf[2:4])[0]
        need = 4 + 4 * n
        if len(buf) < need:
            return None, buf
        encs = struct.unpack(">" + "i" * n, buf[4:need])
        kept = [e for e in encs if e in _SAFE_ENCODINGS]
        if not kept:
            kept = [0]
        if -223 not in kept and -308 not in kept:
            kept.append(-223)
        print(f"SetEncodings {list(encs)} -> {kept}", flush=True)
        out = bytes([2, 0]) + struct.pack(">H", len(kept))
        out += struct.pack(">" + "i" * len(kept), *kept)
        return out, buf[need:]
    if t == 3:  # FramebufferUpdateRequest
        if len(buf) < 10:
            return None, buf
        return buf[:10], buf[10:]
    if t == 4:  # KeyEvent
        if len(buf) < 8:
            return None, buf
        return buf[:8], buf[8:]
    if t == 5:  # PointerEvent
        if len(buf) < 6:
            return None, buf
        return buf[:6], buf[6:]
    if t == 6:  # ClientCutText
        if len(buf) < 8:
            return None, buf
        ln = struct.unpack(">I", buf[4:8])[0]
        need = 8 + ln
        if len(buf) < need:
            return None, buf
        return buf[:need], buf[need:]
    # Unknown: don't guess the length; flush as-is and hope.
    print(f"unknown client msg {t}", flush=True)
    return buf, b""


def handle(client: socket.socket, addr, password: str, backend_host: str, backend_port: int) -> None:
    log = sys.stderr
    print(f"client {addr}", file=log, flush=True)
    backend = None
    try:
        handshake_client(client, password)
        with _BACKEND_LOCK:
            ensure_backend()
        backend = handshake_wayvnc(backend_host, backend_port)
        # Always shared; exclusive makes 0.5 hang up if it thinks a client remains.
        recvall(client, 1)
        backend.sendall(b"\x01")
        splice(client, backend)
        print(f"done {addr}", file=log, flush=True)
    except Exception as exc:
        print(f"fail {addr}: {exc}", file=log, flush=True)
        try:
            client.close()
        except OSError:
            pass
        if backend is not None:
            try:
                backend.close()
            except OSError:
                pass


def main() -> int:
    _selftest()
    listen_host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    listen_port = int(sys.argv[2]) if len(sys.argv) > 2 else 5900
    password = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("VNC_PASSWORD", "")
    if not password:
        print("set VNC_PASSWORD or pass the password as argv[3]", file=sys.stderr)
        return 2
    backend_host = sys.argv[4] if len(sys.argv) > 4 else "127.0.0.1"
    backend_port = int(sys.argv[5]) if len(sys.argv) > 5 else 5901

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen_host, listen_port))
    srv.listen(4)
    print(
        f"vnc-des-proxy {listen_host}:{listen_port} -> {backend_host}:{backend_port}",
        flush=True,
    )
    while True:
        client, addr = srv.accept()
        threading.Thread(
            target=handle,
            args=(client, addr, password, backend_host, backend_port),
            daemon=True,
        ).start()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/python3
"""RFB 3.8 backend for the DES proxy: push grim screenshots, not wayvnc.

wayvnc 0.5 on this Mali/GLES compositor serves a uniform gray framebuffer.
grim uses wlr-screencopy correctly, so we VNC that instead.

ZRLE carries one zlib stream for the whole connection, flushed per rect.
Compressing each frame on its own would end the stream after frame one and
every later frame would decode to nothing (macOS then drops the session).

Input goes out through gta8-inject, which owns the Wayland virtual pointer
and keyboard. Each session runs a reader and a writer thread: a capture takes
over a second, and clicks must not sit behind one.
"""
from __future__ import annotations

import os
import socket
import struct
import subprocess
import threading
import time
import zlib

HOST = "127.0.0.1"
PORT = 5901
FPS = 2
TILE = 64
# Nothing on screen changed for this long: resend a tile so the client, which
# is blocked waiting on its update request, sees the connection is alive.
IDLE_KEEPALIVE = 4.0

INJECT_BIN = "/usr/local/bin/gta8-inject"
KEYMAP_PATH = "/run/gta8-vnc.keymap"

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
# (mask bit, evdev button)
_BUTTONS = ((0x01, BTN_LEFT), (0x02, BTN_MIDDLE), (0x04, BTN_RIGHT))
# (mask bit, axis, value) — one wheel click is 15 degrees, axis 0 is vertical.
_WHEEL = ((0x08, 0, -15.0), (0x10, 0, 15.0), (0x20, 1, -15.0), (0x40, 1, 15.0))


def _load_env() -> None:
    try:
        with open("/run/gta8-vnc.env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key in ("LD_PRELOAD", "LD_LIBRARY_PATH"):
                    continue
                os.environ[key] = val
    except FileNotFoundError:
        pass
    os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/0")
    os.environ.setdefault("WAYLAND_DISPLAY", "wayland-0")


# --- keyboard -------------------------------------------------------------
# The keymap is generated rather than taken from a layout, so a keysym maps
# to a key that produces exactly that keysym at level 1. Nothing has to guess
# where a character sits on a US keyboard, and shift never has to be faked.

_PUNCT = {
    " ": "space", "!": "exclam", '"': "quotedbl", "#": "numbersign",
    "$": "dollar", "%": "percent", "&": "ampersand", "'": "apostrophe",
    "(": "parenleft", ")": "parenright", "*": "asterisk", "+": "plus",
    ",": "comma", "-": "minus", ".": "period", "/": "slash",
    ":": "colon", ";": "semicolon", "<": "less", "=": "equal",
    ">": "greater", "?": "question", "@": "at", "[": "bracketleft",
    "\\": "backslash", "]": "bracketright", "^": "asciicircum",
    "_": "underscore", "`": "grave", "{": "braceleft", "|": "bar",
    "}": "braceright", "~": "asciitilde",
}

_SPECIAL = [
    (0xFF08, "BackSpace"), (0xFF09, "Tab"), (0xFF0D, "Return"),
    (0xFF13, "Pause"), (0xFF1B, "Escape"), (0xFF50, "Home"),
    (0xFF51, "Left"), (0xFF52, "Up"), (0xFF53, "Right"), (0xFF54, "Down"),
    (0xFF55, "Prior"), (0xFF56, "Next"), (0xFF57, "End"),
    (0xFF61, "Print"), (0xFF63, "Insert"), (0xFF67, "Menu"),
    (0xFF7F, "Num_Lock"), (0xFF8D, "KP_Enter"),
    (0xFFE1, "Shift_L"), (0xFFE2, "Shift_R"),
    (0xFFE3, "Control_L"), (0xFFE4, "Control_R"), (0xFFE5, "Caps_Lock"),
    (0xFFE7, "Meta_L"), (0xFFE8, "Meta_R"), (0xFFE9, "Alt_L"),
    (0xFFEA, "Alt_R"), (0xFFEB, "Super_L"), (0xFFEC, "Super_R"),
    (0xFFFF, "Delete"),
] + [(0xFFBE + i, f"F{i + 1}") for i in range(12)]

# Keysyms a client may send for a key we already have.
_ALIAS = {
    0xFF0A: 0xFF0D,  # Linefeed -> Return
    0xFE20: 0xFF09,  # ISO_Left_Tab -> Tab
    0xFF9F: 0xFFFF,  # KP_Delete -> Delete
    0xFF80: 0x0020,  # KP_Space -> space
}

_MODMAP = (
    ("Shift", ("Shift_L", "Shift_R")),
    ("Lock", ("Caps_Lock",)),
    ("Control", ("Control_L", "Control_R")),
    ("Mod1", ("Alt_L", "Alt_R", "Meta_L", "Meta_R")),
    ("Mod2", ("Num_Lock",)),
    ("Mod4", ("Super_L", "Super_R")),
)

KEYSYM_TO_CODE: dict[int, int] = {}


def _keysym_table() -> list[tuple[int, str]]:
    out = []
    for point in range(0x20, 0x7F):
        ch = chr(point)
        out.append((point, ch if ch.isascii() and ch.isalnum() else _PUNCT[ch]))
    return out + _SPECIAL


def build_keymap(path: str = KEYMAP_PATH) -> str:
    table = _keysym_table()
    if len(table) > 247:
        raise RuntimeError("more keysyms than there are keycodes")
    codes, syms = [], []
    for i, (keysym, name) in enumerate(table):
        xkb = 9 + i
        KEYSYM_TO_CODE[keysym] = xkb - 8  # the protocol wants evdev codes
        codes.append(f"        <K{xkb:03d}> = {xkb};")
        syms.append(f"        key <K{xkb:03d}> {{ [ {name} ] }};")
    for alias, real in _ALIAS.items():
        if real in KEYSYM_TO_CODE:
            KEYSYM_TO_CODE[alias] = KEYSYM_TO_CODE[real]
    for mod, names in _MODMAP:
        syms.append(f"        modifier_map {mod} {{ {', '.join(names)} }};")

    text = (
        "xkb_keymap {\n"
        '    xkb_keycodes "gta8" {\n'
        "        minimum = 8;\n"
        "        maximum = 255;\n" + "\n".join(codes) + "\n    };\n"
        '    xkb_types "gta8" { include "complete" };\n'
        '    xkb_compat "gta8" { include "complete" };\n'
        '    xkb_symbols "gta8" {\n'
        '        name[Group1] = "gta8";\n' + "\n".join(syms) + "\n    };\n"
        "};\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class Injector:
    """Single gta8-inject child, shared by every viewer."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.mask = 0

    def _child(self, width: int, height: int):
        if self.proc is not None and self.proc.poll() is None:
            return self.proc
        log = open("/root/gta8-inject.log", "ab", buffering=0)
        self.proc = subprocess.Popen(
            [INJECT_BIN, KEYMAP_PATH, str(width), str(height)],
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
            env=os.environ.copy(),
        )
        self.mask = 0
        return self.proc

    def _write(self, width: int, height: int, lines: list[str]) -> None:
        with self.lock:
            try:
                proc = self._child(width, height)
                proc.stdin.write(("".join(f"{l}\n" for l in lines)).encode())
                proc.stdin.flush()
            except (BrokenPipeError, OSError, AttributeError) as exc:
                print(f"inject failed: {exc}", flush=True)
                self.proc = None

    def pointer(self, width: int, height: int, mask: int, x: int, y: int) -> None:
        lines = [f"m {x} {y}"]
        for bit, button in _BUTTONS:
            if (mask ^ self.mask) & bit:
                lines.append(f"b {button} {1 if mask & bit else 0}")
        for bit, axis, value in _WHEEL:
            if mask & bit and not self.mask & bit:
                lines.append(f"a {axis} {value} {1 if value > 0 else -1}")
        self.mask = mask
        lines.append("f")
        self._write(width, height, lines)

    def key(self, width: int, height: int, keysym: int, down: int) -> None:
        code = KEYSYM_TO_CODE.get(keysym)
        if code is None:
            print(f"no key for keysym 0x{keysym:04x}", flush=True)
            return
        self._write(width, height, [f"k {code} {1 if down else 0}"])


INJECT = Injector()


# --- screen ---------------------------------------------------------------


def capture() -> tuple[int, int, bytes]:
    """Return (width, height, pixels) already in CPIXEL order.

    The pixel format we advertise is little-endian 32 bpp with red at shift
    16, so ZRLE's 3-byte CPIXEL is B, G, R. grim hands us R, G, B.
    """
    env = os.environ.copy()
    env.pop("LD_PRELOAD", None)
    ppm = subprocess.check_output(["grim", "-t", "ppm", "-"], env=env)
    if not ppm.startswith(b"P6"):
        raise RuntimeError("grim did not return P6")
    # P6\nW H\n255\n
    nl1 = ppm.index(b"\n")
    nl2 = ppm.index(b"\n", nl1 + 1)
    nl3 = ppm.index(b"\n", nl2 + 1)
    w, h = map(int, ppm[nl1 + 1 : nl2].split())
    rgb = ppm[nl3 + 1 :]
    bgr = bytearray(len(rgb))
    bgr[0::3] = rgb[2::3]
    bgr[1::3] = rgb[1::3]
    bgr[2::3] = rgb[0::3]
    return w, h, bytes(bgr)


def changed_tiles(old: bytes | None, new: bytes, w: int, h: int) -> list[tuple[int, int]]:
    """Top-left corners of the tiles that differ between two frames."""
    if old is None or len(old) != len(new):
        return [(x, y) for y in range(0, h, TILE) for x in range(0, w, TILE)]
    if old == new:
        return []
    out = []
    for ty in range(0, h, TILE):
        th = min(TILE, h - ty)
        for tx in range(0, w, TILE):
            tw = min(TILE, w - tx)
            for row in range(th):
                off = ((ty + row) * w + tx) * 3
                span = tw * 3
                if old[off : off + span] != new[off : off + span]:
                    out.append((tx, ty))
                    break
    return out


def zrle_rect(comp, pixels: bytes, w: int, x0: int, y0: int, rw: int, rh: int) -> bytes:
    tiles = bytearray()
    for ty in range(y0, y0 + rh, TILE):
        th = min(TILE, y0 + rh - ty)
        for tx in range(x0, x0 + rw, TILE):
            tw = min(TILE, x0 + rw - tx)
            tiles.append(0)  # raw subencoding
            for row in range(th):
                off = ((ty + row) * w + tx) * 3
                tiles += pixels[off : off + tw * 3]
    return comp.compress(bytes(tiles)) + comp.flush(zlib.Z_SYNC_FLUSH)


def recvall(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("eof")
        buf += chunk
    return buf


class Session:
    """One viewer. The reader thread never blocks on a screen capture."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.width = 0
        self.height = 0
        self.alive = True
        self.wanted = threading.Event()
        self.want_full = True
        self.comp = zlib.compressobj(6)
        self.sent: bytes | None = None

    def start(self) -> None:
        self.sock.sendall(b"RFB 003.008\n")
        if not recvall(self.sock, 12).startswith(b"RFB "):
            return
        self.sock.sendall(bytes([1, 1]))  # one security type: None
        if recvall(self.sock, 1)[0] != 1:
            self.sock.sendall(struct.pack(">I", 1))
            return
        self.sock.sendall(struct.pack(">I", 0))
        recvall(self.sock, 1)  # shared flag

        self.width, self.height, pixels = capture()
        pf = bytes([32, 24, 0, 1, 0, 0xFF, 0, 0xFF, 0, 0xFF, 16, 8, 0, 0, 0, 0])
        name = b"gta8"
        self.sock.sendall(
            struct.pack(">HH", self.width, self.height)
            + pf
            + struct.pack(">I", len(name))
            + name
        )

        writer = threading.Thread(target=self._writer, daemon=True)
        writer.start()
        try:
            self._reader(pf)
        finally:
            self.alive = False
            self.wanted.set()

    def _reader(self, pf: bytes) -> None:
        sock = self.sock
        while self.alive:
            t = recvall(sock, 1)[0]
            if t == 0:
                got = recvall(sock, 19)
                if got[3:5] != pf[:2]:
                    print(f"client wants bpp/depth {got[3]}/{got[4]}", flush=True)
            elif t == 2:
                n = struct.unpack(">H", recvall(sock, 3)[1:3])[0]
                recvall(sock, 4 * n)
            elif t == 3:
                if not recvall(sock, 9)[0]:
                    self.want_full = True
                self.wanted.set()
            elif t == 4:
                body = recvall(sock, 7)
                INJECT.key(
                    self.width,
                    self.height,
                    struct.unpack(">I", body[3:7])[0],
                    body[0],
                )
            elif t == 5:
                body = recvall(sock, 5)
                x, y = struct.unpack(">HH", body[1:5])
                INJECT.pointer(self.width, self.height, body[0], x, y)
            elif t == 6:
                ln = struct.unpack(">I", recvall(sock, 7)[3:7])[0]
                recvall(sock, ln)
            else:
                return

    def _writer(self) -> None:
        last_frame = 0.0
        last_update = time.time()
        try:
            while self.alive:
                self.wanted.wait()
                self.wanted.clear()
                if not self.alive:
                    return
                full, self.want_full = self.want_full, False

                while self.alive:
                    gap = 1.0 / FPS - (time.time() - last_frame)
                    if gap > 0:
                        time.sleep(gap)
                    w, h, pixels = capture()
                    last_frame = time.time()
                    if (w, h) != (self.width, self.height):
                        # Resolution changed under us; a full rect would not
                        # match what the client allocated.
                        print(f"size changed to {w}x{h}, dropping viewer", flush=True)
                        self.alive = False
                        return
                    if full or self.sent is None:
                        rects = [(0, 0, w, h)]
                        break
                    tiles = changed_tiles(self.sent, pixels, w, h)
                    if tiles:
                        rects = [
                            (x, y, min(TILE, w - x), min(TILE, h - y)) for x, y in tiles
                        ]
                        break
                    if time.time() - last_update > IDLE_KEEPALIVE:
                        rects = [(0, 0, min(TILE, w), min(TILE, h))]
                        break
                if not self.alive:
                    return

                self.sock.sendall(bytes([0, 0]) + struct.pack(">H", len(rects)))
                for x, y, rw, rh in rects:
                    payload = zrle_rect(self.comp, pixels, w, x, y, rw, rh)
                    self.sock.sendall(struct.pack(">HHHHiI", x, y, rw, rh, 16, len(payload)))
                    self.sock.sendall(payload)
                self.sent = pixels
                last_update = time.time()
        except Exception as exc:
            print(f"writer stopped: {exc}", flush=True)
            self.alive = False
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _safe(client: socket.socket) -> None:
    try:
        client.settimeout(None)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        Session(client).start()
    except Exception as exc:
        print(f"drop: {exc}", flush=True)
    try:
        client.close()
    except OSError:
        pass


def main() -> int:
    _load_env()
    build_keymap()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(2)
    print(f"grim-vnc {HOST}:{PORT}", flush=True)
    while True:
        client, addr = srv.accept()
        print(f"client {addr}", flush=True)
        threading.Thread(target=lambda c=client: _safe(c), daemon=True).start()


if __name__ == "__main__":
    raise SystemExit(main())

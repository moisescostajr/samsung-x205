#!/usr/bin/env python3
"""Print Android liblog datagrams from /dev/socket/logdw."""
import os
import socket
import struct

path = "/dev/socket/logdw"
try:
    os.unlink(path)
except FileNotFoundError:
    pass
os.makedirs("/dev/socket", exist_ok=True)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
sock.bind(path)
os.chmod(path, 0o666)
while True:
    data, _ = sock.recvfrom(4096)
    if len(data) < 12:
        continue
    # skip 11-byte header used by liblog, then prio + tag\0 + msg\0
    rest = data[11:]
    if not rest:
        continue
    parts = rest.split(b"\0")
    if len(parts) >= 3:
        tag = parts[1].decode("utf-8", "replace")
        msg = parts[2].decode("utf-8", "replace").rstrip()
        print(f"{tag}: {msg}", flush=True)
    else:
        print(data[12:].decode("utf-8", "replace", flush=True))

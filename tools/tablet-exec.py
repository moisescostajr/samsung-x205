#!/usr/bin/env python3
"""Execute a command directly on the connected tablet over USB ACM serial and print the output."""
import os, sys, time, termios, tty, select

PORT = "/dev/cu.usbmodem14401"
if len(sys.argv) > 1 and sys.argv[1].startswith("/dev/"):
    PORT = sys.argv[1]
    CMD = " ".join(sys.argv[2:])
else:
    CMD = " ".join(sys.argv[1:])

if not CMD:
    CMD = "uname -a"

fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY)
attr = termios.tcgetattr(fd)
tty.setraw(fd)
attr[4] = termios.B115200
attr[5] = termios.B115200
termios.tcsetattr(fd, termios.TCSANOW, attr)
termios.tcflush(fd, termios.TCIOFLUSH)

# Send command wrapped with markers
token_start = b"__BEGIN_CMD__"
token_end = b"__END_CMD__"

payload = f"\r\nexport PATH=/bin:/sbin:/usr/bin:/usr/sbin\r\necho {token_start.decode()}\r\n{CMD}\r\necho {token_end.decode()}\r\n".encode()
os.write(fd, payload)

resp = b""
start_time = time.time()
while time.time() - start_time < 10.0:
    r, _, _ = select.select([fd], [], [], 0.3)
    if r:
        chunk = os.read(fd, 4096)
        if chunk:
            resp += chunk
            if token_end in resp:
                break
    else:
        if token_end in resp:
            break

os.close(fd)

# Extract output between tokens
text = resp.decode("utf-8", errors="replace")
if token_start.decode() in text and token_end.decode() in text:
    clean = text.split(token_start.decode(), 1)[1].split(token_end.decode(), 1)[0]
    # Remove command echo if present
    lines = clean.strip().splitlines()
    if lines and lines[0].strip() == CMD.strip():
        lines = lines[1:]
    print("\n".join(lines).strip())
else:
    print(text.strip())

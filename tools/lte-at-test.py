#!/usr/bin/env python3
"""Unisoc LTE Modem AT Command Diagnostic & Verification Tool.

Connects to the virtual TTY ports (/dev/stty_lte*) created by the Unisoc SIPC driver
and verifies modem status, SIM card detection, signal strength, and network registration.

Usage:
    python3 tools/lte-at-test.py [/dev/stty_lte0]
"""
from __future__ import annotations

import glob
import os
import select
import sys
import termios
import time


class ATChannel:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 2.0):
        self.port = port
        self.timeout = timeout
        self.fd: int | None = None
        self._old_termios = None

        try:
            self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            self._old_termios = termios.tcgetattr(self.fd)
            # Raw mode: 8N1, disable echo, disable flow control
            new = termios.tcgetattr(self.fd)
            new[0] = 0  # iflag
            new[1] = 0  # oflag
            new[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # cflag
            new[3] = 0  # lflag
            new[4] = termios.B115200  # ispeed
            new[5] = termios.B115200  # ospeed
            termios.tcsetattr(self.fd, termios.TCSANOW, new)
        except OSError as e:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            raise RuntimeError(f"Failed to open port {port}: {e}")

    def close(self):
        if self.fd is not None:
            if self._old_termios is not None:
                try:
                    termios.tcsetattr(self.fd, termios.TCSADRAIN, self._old_termios)
                except OSError:
                    pass
            os.close(self.fd)
            self.fd = None

    def send_cmd(self, cmd: str, timeout: float | None = None) -> list[str]:
        if self.fd is None:
            return []
        if timeout is None:
            timeout = self.timeout

        # Flush input buffer
        termios.tcflush(self.fd, termios.TCIFLUSH)

        cmd_bytes = (cmd + "\r\n").encode("ascii", errors="replace")
        os.write(self.fd, cmd_bytes)

        lines: list[str] = []
        raw_buf = b""
        start_time = time.time()

        while time.time() - start_time < timeout:
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(self.fd, 1024)
                except OSError:
                    break
                if not chunk:
                    break
                raw_buf += chunk
                while b"\r\n" in raw_buf:
                    line, raw_buf = raw_buf.split(b"\r\n", 1)
                    dec = line.decode("ascii", errors="replace").strip()
                    if dec:
                        lines.append(dec)
                        # Termination conditions
                        if dec in ("OK", "ERROR") or dec.startswith("+CME ERROR") or dec.startswith("+CMS ERROR"):
                            return lines
        return lines


def format_csq(csq_resp: str) -> str:
    """Format +CSQ: <rssi>,<ber> into a human readable signal strength."""
    if "+CSQ:" not in csq_resp:
        return csq_resp
    parts = csq_resp.split(":", 1)[1].strip().split(",")
    try:
        rssi = int(parts[0].strip())
        if rssi == 99:
            return "99 (Not known or undetectable)"
        # RSSI 0 = -113 dBm, 31 = -51 dBm, 2 dBm per step
        dbm = -113 + (rssi * 2)
        pct = min(100, int((rssi / 31.0) * 100))
        return f"{rssi}/31 (~{dbm} dBm, {pct}%)"
    except (ValueError, IndexError):
        return csq_resp


def format_creg(resp: str) -> str:
    """Format +CREG/+CEREG network registration status."""
    states = {
        "0": "Not registered, not searching",
        "1": "Registered, home network (Connected)",
        "2": "Not registered, currently searching",
        "3": "Registration denied",
        "4": "Unknown",
        "5": "Registered, roaming",
    }
    for line in resp.split("\n"):
        if ":" in line:
            parts = line.split(":", 1)[1].strip().split(",")
            stat = parts[-1].strip() if len(parts) >= 2 else parts[0].strip()
            return f"{stat} - {states.get(stat, 'Other')}"
    return resp


def test_port(port: str) -> bool:
    print(f"\n==========================================")
    print(f" Probing Port: {port}")
    print(f"==========================================")
    try:
        at = ATChannel(port, timeout=1.5)
    except RuntimeError as e:
        print(f"  [!] {e}")
        return False

    try:
        # Initial AT sync
        resp = at.send_cmd("AT", timeout=1.0)
        if not any("OK" in l for l in resp):
            # Try once more with delay
            time.sleep(0.3)
            resp = at.send_cmd("AT", timeout=1.5)

        if not any("OK" in l for l in resp):
            print("  [-] No 'OK' response to 'AT'. Port might be in data mode or inactive.")
            return False

        print("  [+] Port responded OK to AT!")

        # Turn off echo for clean parsing
        at.send_cmd("ATE0", timeout=0.5)

        # Basic identification
        queries = [
            ("Manufacturer", "AT+CGMI"),
            ("Model", "AT+CGMM"),
            ("Firmware", "AT+CGMR"),
            ("IMEI", "AT+CGSN"),
            ("SIM Card Status", "AT+CPIN?"),
            ("Signal Quality (CSQ)", "AT+CSQ"),
            ("Network Registration (GSM)", "AT+CREG?"),
            ("EPS Network Registration (LTE)", "AT+CEREG?"),
            ("Current Operator", "AT+COPS?"),
            ("APN / PDP Contexts", "AT+CGDCONT?"),
        ]

        results = {}
        for label, cmd in queries:
            res = at.send_cmd(cmd, timeout=2.0)
            cleaned = [l for l in res if l not in ("OK", "ERROR") and not l.startswith("AT")]
            results[label] = cleaned

        # Display report
        print("\n--- Modem Diagnostic Report ---")
        for label, lines in results.items():
            if not lines:
                val = "(no response / error)"
            elif label == "Signal Quality (CSQ)":
                val = format_csq(lines[0])
            elif "Network Registration" in label:
                val = format_creg(lines[0])
            elif len(lines) == 1:
                val = lines[0]
            else:
                val = "\n      " + "\n      ".join(lines)
            print(f"  * {label:30}: {val}")

        return True
    finally:
        at.close()


def main():
    print("Galaxy Tab A8 (SM-X205) LTE Modem Diagnostic Tool")
    print("-------------------------------------------------")

    ports: list[str] = []
    if len(sys.argv) > 1:
        ports = [sys.argv[1]]
    else:
        ports = sorted(glob.glob("/dev/stty_lte*"))
        if not ports:
            ports = sorted(glob.glob("/dev/spipe_lte*"))

    if not ports:
        print("[!] No modem TTY ports found matching /dev/stty_lte* or /dev/spipe_lte*.")
        print("    Make sure 'tools/lte-up.sh' has been executed first!")
        print("\nChecking /proc/pmic/status and dmesg candidates:")
        try:
            with open("/proc/pmic/status") as f:
                print("    /proc/pmic/status:", f.read().strip())
        except OSError:
            print("    /proc/pmic/status: not available")
        sys.exit(1)

    print(f"Candidate modem ports found: {ports}")
    responsive_count = 0
    for p in ports:
        if test_port(p):
            responsive_count += 1

    print("\n==========================================")
    if responsive_count > 0:
        print(f"[OK] Found {responsive_count} responsive port(s). Cellular stack is reachable!")
        print("     To activate mobile data in NetworkManager/Phosh:")
        print("       1. Ensure ModemManager is running: systemctl status ModemManager")
        print("       2. Check NetworkManager connections: nmcli device")
        print("       3. Configure APN: nmcli connection add type gsm con-name 'LTE' apn <your-apn>")
    else:
        print("[!] No ports responded to AT commands.")
        print("    Check /root/lte-up.log, /root/modem_control.err, or 'dmesg | grep -i sipc'.")


if __name__ == "__main__":
    main()

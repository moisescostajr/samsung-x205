#!/usr/bin/env python3
"""Local SIP helper: drive linphonec and expose a localhost JSON API."""
import json
import os
import pty
import re
import select
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CFG_PATH = "/etc/homedash-sip.json"
PID_PATH = "/run/homedash-sipd.pid"
HOST = "127.0.0.1"
PORT = 8765
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b].*?\x07|\r")


def load_cfg():
    with open(CFG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def pulse_cmd(*args):
    env = os.environ.copy()
    env["HOME"] = "/root"
    env["XDG_RUNTIME_DIR"] = "/run/user/0"
    try:
        return subprocess.run(
            ["pactl", *args],
            env=env,
            check=False,
            timeout=4,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return None


def prepare_audio():
    os.environ["HOME"] = "/root"
    os.environ["XDG_RUNTIME_DIR"] = "/run/user/0"
    os.environ["PULSE_SERVER"] = "unix:/run/user/0/pulse/native"
    # This kernel has no SysV IPC; mediastreamer echo-cancel uses shm_open
    # and fails with ENOSYS unless /dev/shm is a real tmpfs.
    try:
        if not os.path.ismount("/dev/shm"):
            os.makedirs("/dev/shm", exist_ok=True)
            subprocess.run(
                ["mount", "-t", "tmpfs", "-o", "nosuid,nodev,mode=1777,size=64M", "tmpfs", "/dev/shm"],
                check=False,
                timeout=3,
            )
        os.chmod("/dev/shm", 0o1777)
    except OSError:
        pass
    try:
        subprocess.run(["killall", "-q", "callaudiod"], check=False, timeout=3)
    except Exception:
        pass
    pulse_cmd("set-sink-mute", "sprd", "0")
    pulse_cmd("set-sink-volume", "sprd", "100%")
    srcs = pulse_cmd("list", "sources", "short")
    if srcs is None or "module-null-source" not in (srcs.stdout or "") and "source.null" not in (srcs.stdout or "") and "\tsilence\t" not in (srcs.stdout or ""):
        pulse_cmd("load-module", "module-null-source")


def patch_sound_section(path):
    sound = (
        "[sound]\n"
        "ec=0\n"
        "playback_dev_id=PulseAudio Unknown: Unix FIFO sink /run/sprd.pcm\n"
        "ringer_dev_id=PulseAudio Unknown: Unix FIFO sink /run/sprd.pcm\n"
        "media_dev_id=PulseAudio Unknown: Unix FIFO sink /run/sprd.pcm\n"
        "capture_dev_id=PulseAudio Unknown: Null Input\n"
    )
    text = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    if "[sound]" in text:
        text = re.sub(r"\[sound\][^\[]*", sound + "\n", text, count=1)
    else:
        text = (text.rstrip() + "\n\n" + sound) if text.strip() else "[sip]\nuse_ipv6=0\n\n" + sound
    if "use_ipv6=" not in text:
        text = "[sip]\nuse_ipv6=0\n\n" + text
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class SipClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.master = None
        self.proc = None
        self.lock = threading.Lock()
        self.registered = False
        self.state = "stopped"
        self.peer = ""
        self.last = ""
        self.buf = ""
        self._stop = False
        self.ready = threading.Event()

    def sip_uri(self, number):
        number = (number or "").strip()
        if number.startswith("sip:"):
            return number
        if "@" in number:
            return "sip:" + number
        host = self.cfg["server"]
        port = int(self.cfg.get("port") or 5060)
        if port and port != 5060:
            return "sip:%s@%s:%s" % (number, host, port)
        return "sip:%s@%s" % (number, host)

    def start(self):
        prepare_audio()
        env = os.environ.copy()
        env["HOME"] = "/root"
        env["XDG_RUNTIME_DIR"] = "/run/user/0"
        env["PULSE_SERVER"] = "unix:/run/user/0/pulse/native"
        env.setdefault("WAYLAND_DISPLAY", "wayland-0")
        os.makedirs("/root/.local/share/linphone", exist_ok=True)
        os.makedirs("/root/.config/linphone", exist_ok=True)
        cfg_file = "/root/.homedash-linphonerc"
        if not os.path.exists(cfg_file) or "sip:1234" in open(cfg_file, encoding="utf-8", errors="ignore").read():
            with open(cfg_file, "w", encoding="utf-8") as fh:
                fh.write("[sip]\nuse_ipv6=0\n")
        patch_sound_section(cfg_file)
        master, slave = pty.openpty()
        cmd = [
            "linphonec",
            "-c", cfg_file,
            "-S",
        ]
        # -V uses X11 MIT-SHM (shmat). This kernel has no SYSVIPC, so video
        # init fails and can stall the media thread. Audio goes through Pulse.
        self.proc = subprocess.Popen(
            cmd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            preexec_fn=os.setsid,
            close_fds=True,
        )
        os.close(slave)
        self.master = master
        os.set_blocking(master, False)
        self.state = "starting"
        threading.Thread(target=self._reader, name="linphonec-out", daemon=True).start()
        self.ready.wait(6)
        self.send("ipv6 disable")
        time.sleep(0.15)
        self.send("ec off")
        time.sleep(0.1)
        self.send("unmute")
        time.sleep(0.1)
        user = self.cfg["user"]
        host = self.cfg["server"]
        pwd = self.cfg["password"]
        ident = "sip:%s@%s" % (user, host)
        proxy = "sip:%s" % host
        port = int(self.cfg.get("port") or 5060)
        if port and port != 5060:
            proxy = "sip:%s:%s" % (host, port)
        self.send("register %s %s %s" % (ident, proxy, pwd))
        self.state = "registering"
        self.last = "Registering as %s" % ident

    def send(self, line):
        if self.master is None:
            return
        os.write(self.master, (line + "\n").encode("utf-8", "replace"))

    def _note(self, text):
        text = text.strip()
        pwd = self.cfg.get("password") or ""
        if pwd:
            text = text.replace(pwd, "****")
        if "linphonec>" in text:
            self.ready.set()
            text = text.replace("linphonec>", "").strip()
            if not text:
                return
        if not text:
            return
        if any(x in text for x in (
            "bctbx-error", "liblinphone-error", "ortp-", "belle-sip-error",
            "mediastreamer-error",
        )):
            print("[linphonec]", text, flush=True)
            return
        print("[linphonec]", text, flush=True)
        self.last = text[:180]
        low = text.lower()
        if "registration" in low and "successful" in low:
            self.registered = True
            if self.state in ("starting", "registering", "stopped"):
                self.state = "registered"
        elif "already registered" in low:
            self.registered = True
            self.state = "registered"
        elif "registration" in low and ("fail" in low or "error" in low or "refused" in low):
            self.registered = False
            self.state = "unregistered"
        elif "incoming call" in low or "receiving new incoming" in low:
            self.state = "incoming"
            m = re.search(r"sip:[^\s>]+", text, re.I)
            self.peer = m.group(0) if m else text
        elif any(x in low for x in ("call terminated", "call ended", "call declined", "no answer")):
            self.state = "registered" if self.registered else "unregistered"
            self.peer = ""
        elif "connected" in low or "call answered" in low or "streams running" in low:
            self.state = "incall"
        elif "establishing call" in low or "in progress" in low or "calling" in low:
            self.state = "dialing"
        elif "call failed" in low or "user is busy" in low or "not found" in low:
            if "incoming" not in low:
                self.state = "registered" if self.registered else "unregistered"

    def _reader(self):
        while not self._stop and self.proc and self.proc.poll() is None:
            try:
                r, _, _ = select.select([self.master], [], [], 0.4)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                break
            if not chunk:
                break
            self.buf += chunk.decode("utf-8", "replace")
            self.buf = ANSI.sub("", self.buf)
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                self._note(line)
        if not self._stop:
            self.state = "stopped"
            self.registered = False
            self.last = "SIP client exited"

    def status(self):
        alive = self.proc is not None and self.proc.poll() is None
        return {
            "ok": True,
            "alive": alive,
            "registered": self.registered,
            "state": self.state,
            "user": self.cfg.get("user", ""),
            "server": self.cfg.get("server", ""),
            "peer": self.peer,
            "last": self.last,
        }

    def dial(self, number):
        number = (number or "").strip()
        if not re.match(r"^[A-Za-z0-9.*#+\-_@]+$", number) and not number.startswith("sip:"):
            return {"ok": False, "error": "bad number"}
        uri = self.sip_uri(number)
        self.peer = uri
        self.state = "dialing"
        pulse_cmd("set-sink-mute", "sprd", "0")
        pulse_cmd("set-sink-volume", "sprd", "100%")
        self.send("unmute")
        self.send("call " + uri)
        self.last = "Calling " + uri
        return {"ok": True, "peer": uri}

    def hangup(self):
        self.send("terminate")
        return {"ok": True}

    def answer(self):
        pulse_cmd("set-sink-mute", "sprd", "0")
        pulse_cmd("set-sink-volume", "sprd", "100%")
        self.send("unmute")
        self.send("answer")
        return {"ok": True}

    def dtmf(self, digit):
        digit = str(digit)[:1]
        if digit not in "0123456789*#":
            return {"ok": False, "error": "bad digit"}
        self.send("digit " + digit)
        return {"ok": True}

    def stop(self):
        self._stop = True
        try:
            if self.master is not None:
                self.send("quit")
                time.sleep(0.2)
        except OSError:
            pass
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass


sip = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        if self.path.split("?")[0] != "/status":
            self._json(404, {"ok": False, "error": "not found"})
            return
        self._json(200, sip.status())

    def do_POST(self):
        path = self.path.split("?")[0]
        data = self._read_json()
        with sip.lock:
            if path == "/dial":
                self._json(200, sip.dial(data.get("number") or ""))
            elif path == "/hangup":
                self._json(200, sip.hangup())
            elif path == "/answer":
                self._json(200, sip.answer())
            elif path == "/dtmf":
                self._json(200, sip.dtmf(data.get("digit") or ""))
            else:
                self._json(404, {"ok": False, "error": "not found"})


def main():
    global sip
    cfg = load_cfg()
    with open(PID_PATH, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    sip = SipClient(cfg)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)

    def bye(*_a):
        sip.stop()
        httpd.shutdown()

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    threading.Thread(target=httpd.serve_forever, name="sip-http", daemon=True).start()
    sip.start()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()

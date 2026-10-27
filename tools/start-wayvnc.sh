#!/bin/busybox sh
# VNC into the running Phosh session. phoc exposes wlr-screencopy plus the
# virtual pointer/keyboard protocols, so wayvnc gives a real interactive screen.
#
# wayvnc 0.5 cannot speak classic DES VNC passwords (what Screen Sharing.app
# wants). Bind it on localhost with no auth, and put vnc-des-proxy in front
# with a classic VNC password (password= in the wayvnc config, or VNC_PASSWORD).
export PATH=/sbin:/bin:/usr/sbin:/usr/bin

CFG=/root/.config/wayvnc/config
LOCALCFG=/root/.config/wayvnc/localhost.conf
BIND=${1:-0.0.0.0}
PORT=${2:-5900}
BACKEND_PORT=5901
PROXY=/root/vnc-des-proxy.py
PASSWORD=${VNC_PASSWORD:-}
for f in "$CFG" /root/.config/wayvnc/vencrypt.conf; do
    if [ -z "$PASSWORD" ] && [ -f "$f" ]; then
        line=$(busybox grep '^password=' "$f" | busybox tail -n 1)
        [ -n "$line" ] && PASSWORD=${line#password=}
    fi
done
if [ -z "$PASSWORD" ]; then
    echo "Set VNC_PASSWORD or password= in $CFG before starting VNC" >&2
    exit 1
fi
busybox mkdir -p /root/.config/wayvnc
# wayvnc 0.5 loads ~/.config/wayvnc/config even without -C; that file has
# VeNCrypt and would block the DES proxy. Force a no-auth localhost listener.
printf '%s\n' 'address=127.0.0.1' "port=$BACKEND_PORT" 'enable_auth=false' \
    > "$LOCALCFG"
busybox cp "$LOCALCFG" /etc/wayvnc-localhost.conf
chmod 644 /etc/wayvnc-localhost.conf

# Attach to whichever wlroots compositor is live (Wayfire or Phosh/phoc).
comp_pid=$(busybox pidof wayfire | busybox cut -d" " -f1)
[ -n "$comp_pid" ] || comp_pid=$(busybox pidof phoc | busybox cut -d" " -f1)
if [ -z "$comp_pid" ]; then
    echo "no compositor; start /root/start-wayfire.sh or /root/start-phosh.sh first" >&2
    exit 1
fi

# Join the compositor's session so wayvnc finds the right socket and bus.
for v in XDG_RUNTIME_DIR WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS HOME; do
    line=$(busybox tr "\0" "\n" < "/proc/$comp_pid/environ" | busybox grep "^$v=")
    [ -n "$line" ] && export "$line"
done
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/0}
# Environ can still say wayland-0 after the compositor created wayland-1.
sock=
for s in "$XDG_RUNTIME_DIR"/wayland-*; do
    case "$s" in
        *.lock) continue ;;
        *wayland-*) sock=$s ;;
    esac
done
[ -n "$sock" ] && [ -S "$sock" ] && WAYLAND_DISPLAY=$(busybox basename "$sock")
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
# --gpu needs the same Mali GBM/EGL the compositor uses, not Mesa's sprd stub.
printf '%s\n' "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" "WAYLAND_DISPLAY=$WAYLAND_DISPLAY" \
    "HOME=/root" "XDG_SESSION_TYPE=wayland" \
    "LD_LIBRARY_PATH=/opt/mali13" \
    "LD_PRELOAD=/opt/mali13/libgbm-shim.so" > /run/gta8-vnc.env
chmod 644 /run/gta8-vnc.env
echo "wayvnc attaching pid=$comp_pid WAYLAND_DISPLAY=$WAYLAND_DISPLAY XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"

# Stop wayvnc and its restart wrapper. Do not match this script's own name.
for p in $(busybox pidof wayvnc); do
    kill "$p" 2>/dev/null
done
for p in $(busybox pidof sh) $(busybox pidof busybox); do
    cmd=$(busybox tr "\0" " " < "/proc/$p/cmdline" 2>/dev/null)
    case "$cmd" in
        *while*wayvnc*) kill "$p" 2>/dev/null ;;
    esac
done
for p in $(busybox pidof python3); do
    cmd=$(busybox tr "\0" " " < "/proc/$p/cmdline" 2>/dev/null)
    case "$cmd" in
        # The proxy leaves a live screen server alone, so restarting it here
        # would otherwise keep serving the old code.
        *vnc-des-proxy.py*|*grim-vnc.py*) kill "$p" 2>/dev/null ;;
    esac
done
for p in $(busybox pidof gta8-inject); do
    kill "$p" 2>/dev/null
done
busybox sleep 1

: > /root/wayvnc.log
: > /root/vnc-des-proxy.log
# Proxy owns wayvnc and restarts it per client (0.5 dies after one session).
# Do not also run a wayvnc loop here — the two fight and the proxy used to
# relaunch with -s seat0, which Wayfire does not have (black framebuffer).
busybox setsid python3 "$PROXY" "$BIND" "$PORT" "$PASSWORD" 127.0.0.1 "$BACKEND_PORT" \
    </dev/null >> /root/vnc-des-proxy.log 2>&1 &
busybox sleep 1

if busybox grep -q 'vnc-des-proxy' /root/vnc-des-proxy.log 2>/dev/null; then
    echo "VNC (Screen Sharing) $BIND:$PORT (password not logged)"
else
    echo "vnc-des-proxy failed to start:" >&2
    busybox cat /root/vnc-des-proxy.log >&2
    exit 1
fi

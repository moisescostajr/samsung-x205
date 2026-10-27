#!/bin/busybox sh
# Wayfire (PC-like wlroots compositor). Same GPU/seatd rules as Phosh:
# one DRM master only — this kills phoc/phosh first.
#
# Wayfire refuses to run as root, so the session is user "gta8" (video group
# for seatd). Phosh can still run as root via /root/start-phosh.sh.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/kmsbin

WF_USER=gta8

# /dev/null is often a regular file on this image (redirects while the node
# is missing). Replace it atomically so dbus-run-session can run as gta8.
ensure_null() {
    tmp=/dev/null.gta8
    busybox rm -f "$tmp"
    busybox mknod -m 666 "$tmp" c 1 3
    busybox mv -f "$tmp" /dev/null
    busybox chmod 666 /dev/null 2>/dev/null
    tmp=/dev/zero.gta8
    busybox rm -f "$tmp"
    busybox mknod -m 666 "$tmp" c 1 5
    busybox mv -f "$tmp" /dev/zero
    busybox chmod 666 /dev/zero 2>/dev/null
}

ensure_null

# xfce4-terminal / VTE needs a world-usable PTY mux. This image mounts
# devpts with ptmxmode=000 and /dev/ptmx as root:root 660.
ensure_pts() {
    if ! mount | busybox grep -q 'devpts on /dev/pts'; then
        busybox mkdir -p /dev/pts
        mount -t devpts -o gid=5,mode=620,ptmxmode=666 devpts /dev/pts 2>/dev/null
    else
        mount -o remount,gid=5,mode=620,ptmxmode=666 /dev/pts 2>/dev/null || true
    fi
    [ -e /dev/ptmx ] || busybox mknod -m 666 /dev/ptmx c 5 2
    chmod 666 /dev/ptmx /dev/pts/ptmx 2>/dev/null
}

ensure_pts

busybox mkdir -p /etc/dpkg/dpkg.cfg.d
echo 'path-exclude=/sbin/init' > /etc/dpkg/dpkg.cfg.d/protect-sbin-init
if [ -L /sbin/init ] && [ -f /root/sbin-init.pre-apps ]; then
    busybox rm -f /sbin/init
    busybox cp -a /root/sbin-init.pre-apps /sbin/init
fi

if ! busybox id "$WF_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash -G video,input,audio,netdev "$WF_USER"
fi
busybox id "$WF_USER" | busybox grep -q video || usermod -aG video,input,audio,netdev,tty "$WF_USER"
usermod -aG tty "$WF_USER" 2>/dev/null
WF_UID=$(busybox id -u "$WF_USER")
WF_HOME=$(getent passwd "$WF_USER" | busybox cut -d: -f6)
[ -n "$WF_HOME" ] || WF_HOME=/home/$WF_USER

if [ -x /usr/bin/sudo ] && [ ! -f /etc/sudoers.d/gta8-session ]; then
    echo "$WF_USER ALL=(root) NOPASSWD: /root/start-phosh.sh" > /etc/sudoers.d/gta8-session
    chmod 440 /etc/sudoers.d/gta8-session
fi

if ! busybox pidof systemd-udevd >/dev/null 2>&1; then
    busybox mkdir -p /run/udev
    /lib/systemd/systemd-udevd --daemon
    busybox sleep 2
    udevadm trigger --action=add --subsystem-match=input
    udevadm trigger --action=add --subsystem-match=net
    udevadm trigger --action=add --subsystem-match=ieee80211
    udevadm settle --timeout=10
fi
udevadm trigger --action=add --subsystem-match=net >/dev/null 2>&1
udevadm settle --timeout=5 >/dev/null 2>&1

if ! dbus-send --system --dest=org.freedesktop.DBus --print-reply \
    /org/freedesktop/DBus org.freedesktop.DBus.ListNames >/dev/null 2>&1; then
    busybox rm -f /run/dbus/pid /run/dbus/system_bus_socket
    busybox mkdir -p /run/dbus
    dbus-uuidgen --ensure 2>/dev/null
    busybox setsid dbus-daemon --system --nofork </dev/null >/root/dbus-system.log 2>&1 &
    busybox sleep 3
fi
if [ -x /usr/lib/polkit-1/polkitd ] && ! busybox pidof polkitd >/dev/null 2>&1; then
    busybox setsid /usr/lib/polkit-1/polkitd --no-debug </dev/null >/root/polkit.log 2>&1 &
fi
if [ ! -e /run/gta8-wifi-manual ] && [ -x /usr/sbin/NetworkManager ] \
    && ! busybox pidof NetworkManager >/dev/null 2>&1; then
    busybox setsid /usr/sbin/NetworkManager --no-daemon </dev/null >/root/nm.log 2>&1 &
fi

for p in $(busybox pidof phoc) $(busybox pidof phosh) $(busybox pidof wayfire) \
         $(busybox pidof waybar) $(busybox pidof wofi) $(busybox pidof squeekboard) \
         $(busybox pidof Xwayland) $(busybox pidof drmstep-fb2); do
    kill "$p" 2>/dev/null
done
busybox sleep 3
for p in $(busybox pidof phoc) $(busybox pidof phosh) $(busybox pidof wayfire) \
         $(busybox pidof waybar) $(busybox pidof wofi) $(busybox pidof squeekboard) \
         $(busybox pidof Xwayland) $(busybox pidof drmstep-fb2); do
    kill -9 "$p" 2>/dev/null
done
busybox sleep 2

RT=/run/user/$WF_UID
busybox rm -f "$RT"/wayland-* "$RT"/wayland-*.lock
busybox mkdir -p "$RT" "$WF_HOME/.config/waybar" "$WF_HOME/.config/wofi"
busybox chmod 700 "$RT"
chown "$WF_USER:$WF_USER" "$RT" "$WF_HOME/.config" "$WF_HOME/.config/waybar" "$WF_HOME/.config/wofi"
cp -a /root/.config/wayfire.ini "$WF_HOME/.config/wayfire.ini"
cp -a /root/.config/waybar/config "$WF_HOME/.config/waybar/config"
cp -a /root/.config/waybar/style.css "$WF_HOME/.config/waybar/style.css"
cp -a /root/.config/wofi/config "$WF_HOME/.config/wofi/config"
chown -R "$WF_USER:$WF_USER" "$WF_HOME/.config"

export XDG_RUNTIME_DIR=$RT
export XDG_SESSION_TYPE=wayland
export XDG_CURRENT_DESKTOP=Wayfire
export XDG_CONFIG_HOME=$WF_HOME/.config
export HOME=$WF_HOME
export WLR_BACKENDS=drm,libinput
export WLR_DRM_DEVICES=/dev/dri/card0
export WLR_NO_HARDWARE_CURSORS=1
export WAYFIRE_CONFIG_FILE=$WF_HOME/.config/wayfire.ini
export LIBSEAT_BACKEND=seatd
export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1

# Root-only /dev/shm is why keymap/dmabuf SHM files fail for user gta8.
busybox mkdir -p /dev/shm
chmod 1777 /dev/shm 2>/dev/null
if ! mount | busybox grep -q 'on /dev/shm '; then
    mount -t tmpfs -o nosuid,nodev,mode=1777 shm /dev/shm 2>/dev/null || true
fi

if ! busybox pidof seatd >/dev/null 2>&1; then
    busybox setsid /usr/sbin/seatd -g video </dev/null >/root/seatd.log 2>&1 &
    busybox sleep 3
fi

MALI=/opt/mali13
if [ ! -f /root/gpu-disable ] && [ -f "$MALI/libEGL.so.1" ] && [ -c /dev/mali0 ]; then
    GPU_MODE=gles2
    WF_GPU_ENV="LD_LIBRARY_PATH=$MALI LD_PRELOAD=$MALI/libgbm-shim.so WLR_RENDERER=gles2"
else
    GPU_MODE=pixman
    WF_GPU_ENV="WLR_RENDERER=pixman WLR_RENDERER_ALLOW_SOFTWARE=1"
fi
echo "renderer: $GPU_MODE" > /root/wayfire-renderer

COMMON_ENV="HOME=$WF_HOME XDG_RUNTIME_DIR=$RT XDG_SESSION_TYPE=wayland \
XDG_CURRENT_DESKTOP=Wayfire XDG_CONFIG_HOME=$WF_HOME/.config \
LIBSEAT_BACKEND=seatd \
WLR_BACKENDS=drm,libinput WLR_DRM_DEVICES=/dev/dri/card0 \
WLR_NO_HARDWARE_CURSORS=1 WAYFIRE_CONFIG_FILE=$WF_HOME/.config/wayfire.ini"

start_compositor() {
    ensure_null
    : > /root/wayfire.log
    busybox setsid runuser -u "$WF_USER" -- env $COMMON_ENV \
        dbus-run-session -- env $WF_GPU_ENV \
        /usr/bin/wayfire -c "$WF_HOME/.config/wayfire.ini" \
        >> /root/wayfire.log 2>&1 &
    busybox sleep 8
}

start_compositor

if [ "$GPU_MODE" = gles2 ] && ! busybox pidof wayfire >/dev/null 2>&1; then
    echo "gles2 wayfire failed, falling back to pixman" >> /root/wayfire.log
    GPU_MODE=pixman
    WF_GPU_ENV="WLR_RENDERER=pixman WLR_RENDERER_ALLOW_SOFTWARE=1"
    echo "renderer: pixman (gles2 failed)" > /root/wayfire-renderer
    start_compositor
fi

pid=$(busybox pidof wayfire | busybox cut -d" " -f1)
if [ -n "$pid" ]; then
    addr=$(busybox tr "\0" "\n" < "/proc/$pid/environ" | busybox grep "^DBUS_SESSION_BUS_ADDRESS=")
    [ -n "$addr" ] && export "$addr"
    wd=$(busybox tr "\0" "\n" < "/proc/$pid/environ" | busybox grep "^WAYLAND_DISPLAY=" | busybox tail -1)
    [ -n "$wd" ] && export "$wd"
fi
if [ -z "$WAYLAND_DISPLAY" ]; then
    sock=$(busybox ls "$RT"/wayland-* 2>/dev/null | busybox grep -v lock | busybox head -1)
    [ -n "$sock" ] && export WAYLAND_DISPLAY=$(busybox basename "$sock")
fi
[ -n "$WAYLAND_DISPLAY" ] && COMMON_ENV="$COMMON_ENV WAYLAND_DISPLAY=$WAYLAND_DISPLAY"

# waybar/squeekboard are GTK; keep them off the Mali compositor blob.
CLIENT_GPU="GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1"

: > /root/waybar.log
busybox setsid runuser -u "$WF_USER" -- env $COMMON_ENV $CLIENT_GPU \
    ${DBUS_SESSION_BUS_ADDRESS:+DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS} \
    /usr/bin/waybar >> /root/waybar.log 2>&1 &

if [ -x /usr/bin/squeekboard ]; then
    : > /root/squeekboard.log
    busybox setsid runuser -u "$WF_USER" -- env $COMMON_ENV $CLIENT_GPU \
        ${DBUS_SESSION_BUS_ADDRESS:+DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS} \
        /usr/bin/squeekboard >> /root/squeekboard.log 2>&1 &
fi

echo 128 > /sys/class/backlight/sprd_backlight/brightness
echo 0 > /sys/class/backlight/sprd_backlight/bl_power

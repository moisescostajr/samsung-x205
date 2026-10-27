#!/bin/busybox sh
# Try real libseat via seatd now that CONFIG_VT=y gives us /dev/tty0.
# Reverts to the libseat-novt shim if phoc does not light the panel.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin

: > /root/try-seatd.log
log() { echo "try-seatd: $*" >> /root/try-seatd.log; }

if ! busybox pidof seatd >/dev/null 2>&1; then
    busybox setsid /usr/sbin/seatd -g video </dev/null >/root/seatd.log 2>&1 &
    busybox sleep 3
fi
log "seatd=$(busybox pidof seatd)"

for p in $(busybox pidof phoc) $(busybox pidof phosh) $(busybox pidof squeekboard); do
    kill -9 "$p" 2>/dev/null
done
busybox sleep 3
busybox rm -f /run/user/0/wayland-0 /run/user/0/wayland-0.lock

export XDG_RUNTIME_DIR=/run/user/0
export XDG_SESSION_TYPE=wayland
export XDG_CURRENT_DESKTOP=Phosh
export WAYLAND_DISPLAY=wayland-0
export WLR_BACKENDS=drm,libinput
export WLR_RENDERER=pixman
export WLR_DRM_DEVICES=/dev/dri/card0
export WLR_NO_HARDWARE_CURSORS=1
export LIBGL_ALWAYS_SOFTWARE=1
export LIBSEAT_BACKEND=seatd
unset LD_PRELOAD

: > /root/phoc.log
busybox setsid dbus-run-session -- /usr/bin/phoc -S -C /usr/share/phosh/phoc.ini >> /root/phoc.log 2>&1 &
busybox sleep 10

if busybox pidof phoc >/dev/null 2>&1 && busybox grep -q "Output 'DSI-1' added" /root/phoc.log; then
    log SEATD_OK
    pid=$(busybox pidof phoc | busybox cut -d" " -f1)
    addr=$(busybox tr "\0" "\n" < "/proc/$pid/environ" | busybox grep "^DBUS_SESSION_BUS_ADDRESS=")
    [ -n "$addr" ] && export "$addr"
    : > /root/phosh-shell.log
    busybox setsid /usr/libexec/phosh >> /root/phosh-shell.log 2>&1 &
    busybox sleep 8
    echo 128 > /sys/class/backlight/sprd_backlight/brightness
    echo 0 > /sys/class/backlight/sprd_backlight/bl_power
    log "phoc=$(busybox pidof phoc) phosh=$(busybox pidof phosh)"
else
    log SEATD_FAILED
    busybox tail -15 /root/phoc.log >> /root/try-seatd.log
    busybox sh /root/start-phosh.sh >> /root/try-seatd.log 2>&1
    log REVERTED
fi
log DONE

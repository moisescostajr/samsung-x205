#!/bin/busybox sh
# Phosh with sole DRM ownership. Two DRM masters wedge this SPRD driver.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/kmsbin

busybox rm -f /dev/null
busybox mknod -m 666 /dev/null c 1 3 2>/dev/null

# apt once replaced this with a systemd symlink and froze at the Samsung logo.
busybox mkdir -p /etc/dpkg/dpkg.cfg.d
echo 'path-exclude=/sbin/init' > /etc/dpkg/dpkg.cfg.d/protect-sbin-init
if [ -L /sbin/init ] && [ -f /root/sbin-init.pre-apps ]; then
    busybox rm -f /sbin/init
    busybox cp -a /root/sbin-init.pre-apps /sbin/init
fi

busybox mkdir -p /usr/share/dbus-1/services
if [ ! -f /usr/share/dbus-1/services/sm.puri.OSK0.service ]; then
    printf '%s\n' '[D-BUS Service]' 'Name=sm.puri.OSK0' 'Exec=/usr/bin/squeekboard' \
        > /usr/share/dbus-1/services/sm.puri.OSK0.service
fi
# Phosh QS brightness talks to this name. Real gsd-power needs logind.
printf '%s\n' '[D-BUS Service]' 'Name=org.gnome.SettingsDaemon.Power' \
    'Exec=/usr/bin/python3 -u /root/gsd-power-stub.py' \
    > /usr/share/dbus-1/services/org.gnome.SettingsDaemon.Power.service

# libinput enumerates through udev, and nothing else starts udevd here.
if [ -f /root/udev/77-unisoc-modem.rules ] && [ ! -f /etc/udev/rules.d/77-unisoc-modem.rules ]; then
    busybox cp -f /root/udev/77-unisoc-modem.rules /etc/udev/rules.d/ 2>/dev/null || true
fi
if ! busybox pidof systemd-udevd >/dev/null 2>&1; then
    busybox mkdir -p /run/udev
    /lib/systemd/systemd-udevd --daemon
    busybox sleep 2
    udevadm trigger --action=add --subsystem-match=input
    udevadm trigger --action=add --subsystem-match=net
    udevadm trigger --action=add --subsystem-match=ieee80211
    udevadm trigger --action=add --subsystem-match=tty
    udevadm settle --timeout=10
fi
# wlan0 is born before udevd; NM leaves it unmanaged without a net trigger.
udevadm trigger --action=add --subsystem-match=net >/dev/null 2>&1
udevadm settle --timeout=5 >/dev/null 2>&1

# v57 ramdisk still pins USB-C as a gadget. Release the UDC so a pad can
# enumerate; /root/usb-role.sh gadget brings ACM+RNDIS back if needed.
if [ -x /root/usb-role.sh ]; then
    busybox sh /root/usb-role.sh auto >> /root/usb-role.log 2>&1
fi

# System bus is required for NetworkManager / Settings Wi-Fi. Test the bus
# itself: /run survives reboots here, so the socket and pid file can be stale.
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
# hw-up.sh drops this marker when it fell back to a hand-rolled wpa_supplicant;
# starting NM on top of that leaves wlan0 "unavailable".
if [ ! -e /run/gta8-wifi-manual ] && [ -x /usr/sbin/NetworkManager ] \
    && ! busybox pidof NetworkManager >/dev/null 2>&1; then
    busybox setsid /usr/sbin/NetworkManager --no-daemon </dev/null >/root/nm.log 2>&1 &
fi

# Bring up LTE modem on SM-X205 and start ModemManager
if [ -x /root/lte-up.sh ] && busybox grep -q 'androidboot.em.model=SM-X205' /proc/cmdline; then
    busybox sh /root/lte-up.sh >> /root/lte-up.log 2>&1 &
fi
if [ -x /usr/sbin/ModemManager ] && ! busybox pidof ModemManager >/dev/null 2>&1; then
    busybox setsid /usr/sbin/ModemManager </dev/null >/root/mm.log 2>&1 &
fi

for p in $(busybox pidof python3); do
    cmd=$(busybox tr "\0" " " < "/proc/$p/cmdline" 2>/dev/null)
    case "$cmd" in
        *gsd-power-stub.py*) kill "$p" 2>/dev/null ;;
    esac
done
for p in $(busybox pidof phoc) $(busybox pidof phosh) $(busybox pidof wayfire) \
         $(busybox pidof waybar) $(busybox pidof wofi) $(busybox pidof squeekboard) \
         $(busybox pidof Xwayland) $(busybox pidof drmstep-fb2); do
    kill "$p" 2>/dev/null
done
busybox sleep 1
busybox sleep 3
for p in $(busybox pidof phoc) $(busybox pidof phosh) $(busybox pidof wayfire) \
         $(busybox pidof waybar) $(busybox pidof wofi) $(busybox pidof squeekboard) \
         $(busybox pidof Xwayland) $(busybox pidof drmstep-fb2); do
    kill -9 "$p" 2>/dev/null
done
busybox sleep 2
busybox rm -f /run/user/0/wayland-0 /run/user/0/wayland-0.lock
busybox mkdir -p /run/user/0
busybox chmod 700 /run/user/0

export XDG_RUNTIME_DIR=/run/user/0
export XDG_SESSION_TYPE=wayland
export XDG_CURRENT_DESKTOP=Phosh
export WAYLAND_DISPLAY=wayland-0
export PULSE_RUNTIME_PATH=/run/user/0/pulse
export PULSE_SERVER=unix:/run/user/0/pulse/native
export WLR_BACKENDS=drm,libinput
export WLR_DRM_DEVICES=/dev/dri/card0
export WLR_NO_HARDWARE_CURSORS=1

# GPU path: the Mali-G52 works through the r13p0 libmali blob, whose GBM uses
# the armsoc backend and so accepts our sprd display device (the newer r24p0
# blob allocates from dma-heap, which 4.14 does not have). The blob predates
# gbm_bo_get_fd_for_plane(), so a one-symbol shim is preloaded for wlroots.
#
# Touch /root/gpu-disable to fall back to software rendering.
MALI=/opt/mali13
if [ ! -f /root/gpu-disable ] && [ -f "$MALI/libEGL.so.1" ] && [ -c /dev/mali0 ]; then
    export LD_LIBRARY_PATH="$MALI${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export LD_PRELOAD="$MALI/libgbm-shim.so"
    export WLR_RENDERER=gles2
    unset LIBGL_ALWAYS_SOFTWARE
    export GSK_RENDERER=gl
    GPU_MODE=gles2
else
    export WLR_RENDERER=pixman
    export LIBGL_ALWAYS_SOFTWARE=1
    export GSK_RENDERER=cairo
    GPU_MODE=pixman
fi
echo "renderer: $GPU_MODE" > /root/phosh-renderer
export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1

# The v57 kernel has real DRM PRIME and CONFIG_VT, so both LD_PRELOAD shims
# (sprd-prime-shim.so, libseat-novt.so) are gone: seatd handles the seat.
if ! busybox pidof seatd >/dev/null 2>&1; then
    busybox setsid /usr/sbin/seatd -g video </dev/null >/root/seatd.log 2>&1 &
    busybox sleep 3
fi
export LIBSEAT_BACKEND=seatd
# In GPU mode LD_PRELOAD carries the GBM shim phoc needs; otherwise nothing
# should leak into the session.
[ "$GPU_MODE" = gles2 ] || unset LD_PRELOAD

: > /root/phoc.log
busybox setsid dbus-run-session -- /usr/bin/phoc -S -C /usr/share/phosh/phoc.ini >> /root/phoc.log 2>&1 &
busybox sleep 8

# If the GPU renderer did not come up, fall back to software rather than
# leaving the tablet with a dead screen.
if [ "$GPU_MODE" = gles2 ] && ! busybox pidof phoc >/dev/null 2>&1; then
    echo "gles2 phoc failed, falling back to pixman" >> /root/phoc.log
    export WLR_RENDERER=pixman
    export LIBGL_ALWAYS_SOFTWARE=1
    export GSK_RENDERER=cairo
    unset LD_PRELOAD LD_LIBRARY_PATH
    GPU_MODE=pixman
    echo "renderer: pixman (gles2 failed)" > /root/phosh-renderer
    busybox setsid dbus-run-session -- /usr/bin/phoc -S -C /usr/share/phosh/phoc.ini >> /root/phoc.log 2>&1 &
    busybox sleep 8
fi

pid=$(busybox pidof phoc | busybox cut -d" " -f1)
addr=$(busybox tr "\0" "\n" < "/proc/$pid/environ" | busybox grep "^DBUS_SESSION_BUS_ADDRESS=")
[ -n "$addr" ] && export "$addr"

# Apps render on the GPU through the r24p0 blob. By default it wants ARM's
# private mali_buffer_sharing protocol, which wlroots does not implement;
# MALI_WAYLAND_DMABUF_PROTOCOL=1 switches it to zwp_linux_dmabuf_v1, which
# phoc does advertise. That blob also needs dma_heap_compat.ko for its
# allocations. The compositor stays on r13p0, whose GBM drives the sprd
# display; the two only meet through dmabuf.
#
# The shim must not leak into apps: it is only for wlroots.
CLIENT_MALI=/opt/mali
if [ "$GPU_MODE" = gles2 ] && [ -f "$CLIENT_MALI/libEGL.so.1" ] && \
   [ -c /dev/dma_heap/system ]; then
    CLIENT_ENV="env -u LD_PRELOAD -u LIBGL_ALWAYS_SOFTWARE \
        LD_LIBRARY_PATH=$CLIENT_MALI MALI_WAYLAND_DMABUF_PROTOCOL=1 \
        GSK_RENDERER=gl"
elif [ "$GPU_MODE" = gles2 ]; then
    CLIENT_ENV="env -u LD_PRELOAD -u LD_LIBRARY_PATH GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1"
else
    CLIENT_ENV=""
fi

: > /root/phosh-shell.log
busybox setsid $CLIENT_ENV /usr/libexec/phosh >> /root/phosh-shell.log 2>&1 &
busybox sleep 8

# Squeekboard is Phosh's OSK. Debian's package has no sm.puri.OSK0 service file,
# so Phosh cannot D-Bus-activate it; start it on the same session bus instead.
if [ -x /usr/bin/squeekboard ] && ! busybox pidof squeekboard >/dev/null 2>&1; then
    : > /root/squeekboard.log
    LD_PRELOAD= busybox setsid $CLIENT_ENV /usr/bin/squeekboard >> /root/squeekboard.log 2>&1 &
fi

# QS brightness: Phosh 0.24 Properties.Set on GSD Power.Screen → sysfs.
if [ -x /root/gsd-power-stub.py ] && [ -n "$DBUS_SESSION_BUS_ADDRESS" ]; then
    : > /root/gsd-power-stub.log
    LD_PRELOAD= LD_LIBRARY_PATH= busybox setsid python3 -u /root/gsd-power-stub.py \
        >> /root/gsd-power-stub.log 2>&1 &
fi

# wayvnc captured continuously and cost ~60% of a core even with no client,
# which was the difference between smooth and stuttering video. The grim
# backend only shells out while a client is attached, so autostart is free.
# Remove /root/wayvnc-autostart to go back to starting it by hand.
if [ -f /root/wayvnc-autostart ] && [ -x /root/start-wayvnc.sh ]; then
    busybox sh /root/start-wayvnc.sh >> /root/wayvnc-start.log 2>&1
fi

echo 128 > /sys/class/backlight/sprd_backlight/brightness
echo 0 > /sys/class/backlight/sprd_backlight/bl_power

# BMI320 + STK3X1X: auto-rotate and auto-brightness. sensors-up.sh is
# idempotent and must never write /proc/pmic/stop.
if [ -x /root/sensors-up.sh ]; then
    busybox sh /root/sensors-up.sh >> /root/sensors-up.log 2>&1
fi
if [ -x /root/gta8-sensors.py ] && ! busybox ps | busybox grep -q '[g]ta8-sensors.py'; then
    busybox setsid python3 /root/gta8-sensors.py >> /root/gta8-sensors.log 2>&1 &
fi

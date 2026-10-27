#!/bin/busybox sh
# Cycle DSI-1: normal -> 90 -> 180 -> 270 -> normal (landscape is 90 or 270).
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
if [ -z "$WAYLAND_DISPLAY" ]; then
    for s in "$XDG_RUNTIME_DIR"/wayland-*; do
        case "$s" in
            *.lock) continue ;;
            *wayland-*) WAYLAND_DISPLAY=$(busybox basename "$s") ;;
        esac
    done
    export WAYLAND_DISPLAY
fi

cur=$(wlr-randr 2>/dev/null | busybox awk '/Transform:/{print $2; exit}')
[ -n "$cur" ] || cur=normal
case "$cur" in
    normal|0) next=90 ;;
    90) next=180 ;;
    180) next=270 ;;
    270) next=normal ;;
    *) next=90 ;;
esac

wlr-randr --output DSI-1 --transform "$next" || exit 1

for ini in /home/gta8/.config/wayfire.ini /root/.config/wayfire.ini; do
    [ -f "$ini" ] || continue
    if busybox grep -q '^\[output:DSI-1\]' "$ini"; then
        busybox sed -i "s/^transform = .*/transform = $next/" "$ini"
    fi
done
echo "$next"

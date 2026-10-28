#!/bin/busybox sh
# USB-C role on gta8wifi (Unisoc musb dual-role).
#
# auto  — default: unbind the debug gadget so Type-C CC can pick host (pad)
#         or device (PC). This is what RetroArch needs.
# host  — force host even if CC is shy (OTG adapter + pad).
# gadget — bind ACM+RNDIS again for a Mac / Pi at 10.99.0.2.
# status — print sysfs + input nodes.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin

USB=/sys/devices/platform/soc/soc:aon/5fff0000.usb
MODE=$USB/musb-hdrc.0.auto/mode
HOSTEN=$USB/musb_hostenable
UDC=musb-hdrc.0.auto
G=/sys/kernel/config/usb_gadget/g1
[ -d "$G" ] || G=/config/usb_gadget/g1

log() { echo "usb-role: $*"; }

unbind_gadget() {
    if [ -e "$G/UDC" ]; then
        echo "" > "$G/UDC" 2>/dev/null || echo none > "$G/UDC" 2>/dev/null || true
    fi
}

allow_notify() {
    echo 1 > /sys/class/usb_notify/usb_notify/usb_data_enabled 2>/dev/null || true
    echo 1 > /sys/class/usb_notify/usb_control/usb_data_enabled 2>/dev/null || true
    echo OFF > /sys/class/usb_notify/usb_notify/disable 2>/dev/null || true
    echo OFF > /sys/devices/virtual/usb_notify/usb_notify/disable 2>/dev/null || true
}

allow_host() {
    allow_notify
    echo on > "$USB/power/control" 2>/dev/null || true
    echo enable > "$HOSTEN" 2>/dev/null || true
}

set_mode() {
    want=$1
    [ -e "$MODE" ] || return 0
    echo "$want" > "$MODE" 2>/dev/null && return 0
    return 1
}

ensure_gadget_dirs() {
    busybox mkdir -p /sys/kernel/config /config
    busybox mount -t configfs configfs /sys/kernel/config 2>/dev/null || true
    [ -d "$G" ] && return 0
    G=/sys/kernel/config/usb_gadget/g1
    busybox mkdir -p "$G/strings/0x409" "$G/functions/acm.gs0" "$G/configs/b.1/strings/0x409"
    echo 0x1d6b > "$G/idVendor"
    echo 0x0104 > "$G/idProduct"
    echo 0x0200 > "$G/bcdUSB"
    echo 0xef > "$G/bDeviceClass"
    echo 0x02 > "$G/bDeviceSubClass"
    echo 0x01 > "$G/bDeviceProtocol"
    echo 0123456789abcdef > "$G/strings/0x409/serialnumber"
    echo Droidian > "$G/strings/0x409/manufacturer"
    echo gta8wifi-debug > "$G/strings/0x409/product"
    echo ACM > "$G/configs/b.1/strings/0x409/configuration"
    busybox ln -sfn "$G/functions/acm.gs0" "$G/configs/b.1/f1"
}

bind_gadget() {
    ensure_gadget_dirs
    echo disable > "$HOSTEN" 2>/dev/null || true
    set_mode peripheral || true
    echo 0xef > "$G/bDeviceClass"
    echo 0x02 > "$G/bDeviceSubClass"
    echo 0x01 > "$G/bDeviceProtocol"
    busybox mkdir -p "$G/functions/ncm.usb0" 2>/dev/null
    busybox mkdir -p "$G/functions/ecm.usb0" 2>/dev/null
    busybox mkdir -p "$G/functions/rndis.usb0" 2>/dev/null
    if [ -d "$G/functions/ncm.usb0" ]; then
        busybox ln -sfn "$G/functions/ncm.usb0" "$G/configs/b.1/f2"
    elif [ -d "$G/functions/ecm.usb0" ]; then
        busybox ln -sfn "$G/functions/ecm.usb0" "$G/configs/b.1/f2"
    elif [ -d "$G/functions/rndis.usb0" ]; then
        busybox ln -sfn "$G/functions/rndis.usb0" "$G/configs/b.1/f2"
    fi
    echo "" > "$G/UDC" 2>/dev/null || true
    busybox sleep 1
    echo "$UDC" > "$G/UDC"
    busybox sleep 1
    if [ -e /sys/class/net/usb0 ]; then
        ip addr add 10.99.0.2/24 dev usb0 2>/dev/null
        ip link set usb0 up 2>/dev/null
    fi
}

trigger_input() {
    if command -v udevadm >/dev/null 2>&1; then
        udevadm trigger --action=add --subsystem-match=usb >/dev/null 2>&1
        udevadm trigger --action=add --subsystem-match=hid >/dev/null 2>&1
        udevadm trigger --action=add --subsystem-match=input >/dev/null 2>&1
    fi
}

show_status() {
    echo "hostenable=$(busybox cat "$HOSTEN" 2>/dev/null)"
    echo "mode=$(busybox cat "$MODE" 2>/dev/null)"
    echo "udc=$(busybox cat "$G/UDC" 2>/dev/null)"
    echo "usb0=$(ip -4 addr show usb0 2>/dev/null | busybox grep inet || echo none)"
    echo "input:"
    busybox ls -l /dev/input 2>/dev/null || echo "  (no /dev/input)"
}

cmd=${1:-auto}
case "$cmd" in
    auto)
        unbind_gadget
        allow_host
        # otg lets CC pick; fall back to host if the sysfs only accepts that.
        set_mode otg || set_mode host || true
        trigger_input
        log "auto (gadget unbound, host/otg allowed)"
        show_status
        ;;
    host)
        unbind_gadget
        allow_host
        set_mode host || true
        trigger_input
        log "forced host"
        show_status
        ;;
    gadget)
        allow_notify
        bind_gadget
        log "gadget ACM+RNDIS on $UDC"
        show_status
        ;;
    status)
        show_status
        ;;
    *)
        echo "usage: $0 auto|host|gadget|status" >&2
        exit 1
        ;;
esac

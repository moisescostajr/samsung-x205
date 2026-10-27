#!/bin/busybox sh
# Hand Wi-Fi to NetworkManager so Phosh Settings can see it.
# Leaves usb0 unmanaged so the Pi gadget link survives a wlan drop.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin

log() { echo "nm-up [$(busybox cut -d. -f1 /proc/uptime)s]: $*"; }

mkdir -p /etc/NetworkManager/conf.d /etc/NetworkManager/system-connections /run/NetworkManager

cat > /etc/NetworkManager/conf.d/gta8.conf << 'EOF'
[main]
no-auto-default=*
dns=default

[device]
wifi.scan-rand-mac-address=no

[keyfile]
unmanaged-devices=interface-name:usb0
EOF

python3 - << 'PY'
import os, re, uuid
text = open("/etc/wpa_supplicant.conf").read()
ssid = re.search(r'ssid="([^"]+)"', text).group(1)
psk = re.search(r'psk="([^"]+)"', text).group(1)
path = "/etc/NetworkManager/system-connections/%s.nmconnection" % ssid
open(path, "w").write(
    "[connection]\n"
    "id=%s\n"
    "uuid=%s\n"
    "type=wifi\n"
    "autoconnect=true\n"
    "interface-name=wlan0\n"
    "\n"
    "[wifi]\n"
    "mode=infrastructure\n"
    "ssid=%s\n"
    "\n"
    "[wifi-security]\n"
    "key-mgmt=wpa-psk\n"
    "psk=%s\n"
    "\n"
    "[ipv4]\n"
    "method=auto\n"
    "\n"
    "[ipv6]\n"
    "method=disabled\n" % (ssid, uuid.uuid4(), ssid, psk)
)
os.chmod(path, 0o600)
print("wrote", path)
PY

# wlan0 is created before udevd; without this NM marks it unmanaged.
if command -v udevadm >/dev/null 2>&1; then
    udevadm trigger --action=add --subsystem-match=net
    udevadm trigger --action=add --subsystem-match=ieee80211
    udevadm settle --timeout=10
fi

if [ ! -S /run/dbus/system_bus_socket ]; then
    mkdir -p /run/dbus
    dbus-uuidgen --ensure
    busybox setsid dbus-daemon --system --nofork </dev/null >/root/dbus-system.log 2>&1 &
    busybox sleep 1
fi

if [ -x /usr/lib/polkit-1/polkitd ] && ! busybox pidof polkitd >/dev/null 2>&1; then
    busybox setsid /usr/lib/polkit-1/polkitd --no-debug </dev/null >/root/polkit.log 2>&1 &
    log polkit_started
fi

# Drop the hand-rolled wpa/udhcpc so NM can own wlan0.
busybox killall udhcpc 2>/dev/null
busybox killall wpa_supplicant 2>/dev/null
busybox sleep 2

if ! busybox pidof NetworkManager >/dev/null 2>&1; then
    busybox setsid /usr/sbin/NetworkManager --no-daemon </dev/null >/root/nm.log 2>&1 &
    log nm_started
fi

i=0
while [ "$i" -lt 15 ]; do
    if nmcli -t -f RUNNING general 2>/dev/null | grep -q running; then
        break
    fi
    i=$((i + 1))
    busybox sleep 1
done

nmcli radio wifi on >/dev/null 2>&1 || true
nmcli networking on >/dev/null 2>&1 || true
nmcli connection reload >/dev/null 2>&1 || true
nmcli device connect wlan0 >/tmp/nm-up.out 2>&1 || true
log "wlan=$(ip -4 addr show wlan0 2>/dev/null | busybox grep inet || echo none)"
nmcli -t -f DEVICE,STATE,CONNECTION device >>/tmp/nm-up.out 2>&1 || true
cat /tmp/nm-up.out
log DONE

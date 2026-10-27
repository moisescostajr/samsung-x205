#!/bin/busybox sh
# Put Wi-Fi back on the hand-rolled wpa_supplicant path if NM cannot drive sprdwl.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/wifi
busybox killall NetworkManager 2>/dev/null
busybox killall wpa_supplicant 2>/dev/null
busybox killall udhcpc 2>/dev/null
busybox sleep 1
ip link set wlan0 up
busybox mkdir -p /run/wpa_supplicant
busybox setsid /opt/wifi/wpa_supplicant -i wlan0 -Dnl80211 \
    -c /etc/wpa_supplicant.conf -f /tmp/wpa.log </dev/null >/dev/null 2>&1 &
i=0
while [ "$i" -lt 20 ]; do
    st=$(/opt/wifi/iw dev wlan0 link 2>/dev/null | busybox head -1)
    case "$st" in
        Connected*) break ;;
    esac
    i=$((i + 1))
    busybox sleep 2
done
busybox udhcpc -i wlan0 -n -t 10 -T 3 -s /usr/share/udhcpc/default.script
ip -4 addr show wlan0

#!/bin/busybox sh
# Wi-Fi bring-up only. Display and watchdog handling live in debian-init.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/wifi:/opt/kmsbin
export LD_LIBRARY_PATH=/opt/wifi/lib

log() {
    echo "gta8-hw [$(busybox cut -d. -f1 /proc/uptime)s]: $*" >> /root/hw-up.log
}

# NetworkManager only adopts an interface that udev has tagged, and wlan0 is
# created by insmod long before anything starts udevd.
start_udevd() {
    if ! busybox pidof systemd-udevd >/dev/null 2>&1; then
        busybox mkdir -p /run/udev
        /lib/systemd/systemd-udevd --daemon
        busybox sleep 2
        log udevd_started
    fi
    udevadm trigger --action=add --subsystem-match=net 2>/dev/null
    udevadm trigger --action=add --subsystem-match=ieee80211 2>/dev/null
    udevadm trigger --action=add --subsystem-match=input 2>/dev/null
    udevadm settle --timeout=10 2>/dev/null
}

# NetworkManager, polkit and Phosh Settings all need the system bus.
start_system_bus() {
    if dbus-send --system --dest=org.freedesktop.DBus --print-reply \
        /org/freedesktop/DBus org.freedesktop.DBus.ListNames >/dev/null 2>&1; then
        return 0
    fi
    busybox rm -f /run/dbus/pid /run/dbus/system_bus_socket
    busybox mkdir -p /run/dbus
    dbus-uuidgen --ensure 2>/dev/null
    busybox setsid dbus-daemon --system --nofork </dev/null >/root/dbus-system.log 2>&1 &
    i=0
    while [ "$i" -lt 10 ]; do
        busybox sleep 1
        if dbus-send --system --dest=org.freedesktop.DBus --print-reply \
            /org/freedesktop/DBus org.freedesktop.DBus.ListNames >/dev/null 2>&1; then
            log system_bus_up
            return 0
        fi
        i=$((i + 1))
    done
    log system_bus_fail
    return 1
}

: > /root/hw-up.log
log WIFI_START
busybox rm -f /dev/null
busybox mknod -m 666 /dev/null c 1 3 2>/dev/null

# /run is on the SD root here, so sockets and pid files survive a reboot and
# every daemon then refuses to start ("pid file exists"). Debian expects tmpfs.
if ! busybox grep -q " /run tmpfs " /proc/mounts && ! busybox pidof phoc >/dev/null 2>&1; then
    busybox mount -t tmpfs -o mode=755,nosuid,nodev tmpfs /run && log run_tmpfs \
        || log run_tmpfs_fail
fi
busybox mkdir -p /run/dbus /run/udev /run/user /run/NetworkManager /run/wpa_supplicant /run/lock
echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
for ko in /root/modules/pmicwdt_off.ko /modules/pmicwdt_off.ko /pmicwdt_off.ko /opt/kmsbin/pmicwdt_off.ko; do
    if [ -f "$ko" ]; then
        insmod "$ko" >> /root/hw-up.log 2>&1 && log "pmicwdt_insmod: $ko" && break
    fi
done

# X200 and X205 share the SoC but not the GPT index. LTE inserts
# l_modem/l_ldsp/l_gdsp and shifts boot/socko/super. Always resolve by name.
part_by_name() {
    want=$1
    for p in /sys/block/mmcblk0/mmcblk0p*; do
        n=$(busybox sed -n 's/^PARTNAME=//p' "$p/uevent" 2>/dev/null)
        if [ "$n" = "$want" ]; then
            echo "/dev/${p##*/}"
            return 0
        fi
    done
    return 1
}

busybox mkdir -p /mnt/vendor /mnt/socko /vendor /data/vendor/wifi
BN=/dev/block/platform/soc/soc:ap-apb/71400000.sdio/by-name
busybox mkdir -p "$BN"
busybox mknod /dev/loop0 b 7 0 2>/dev/null
busybox losetup -d /dev/loop0 2>/dev/null

SOCKO=$(part_by_name socko)
SUPER=$(part_by_name super)
WCN=$(part_by_name wcnmodem)
GNSS=$(part_by_name gnssmodem)
USERDATA=$(part_by_name userdata)
L_MODEM=$(part_by_name l_modem)
L_LDSP=$(part_by_name l_ldsp)
L_GDSP=$(part_by_name l_gdsp)
L_AGDSP=$(part_by_name l_agdsp)
PM_SYS=$(part_by_name pm_sys)
NVITEM=$(part_by_name nvitem)
PRODNV=$(part_by_name prodnv)
log "parts socko=$SOCKO super=$SUPER wcn=$WCN gnss=$GNSS l_modem=$L_MODEM l_ldsp=$L_LDSP"

if [ -n "$SUPER" ] && busybox losetup -o 4281335808 /dev/loop0 "$SUPER"; then
    if busybox mount -t ext4 -o ro /dev/loop0 /mnt/vendor; then
        busybox mount --bind /mnt/vendor /vendor
        log vendor_mounted
    else
        log vendor_mount_fail
    fi
else
    log losetup_fail
fi

if [ -n "$SOCKO" ]; then
    busybox mount -t ext4 -o ro "$SOCKO" /mnt/socko && log socko_mounted || log socko_fail
else
    log socko_missing
fi
log "socko_mods=$(busybox ls /mnt/socko 2>/dev/null | busybox tr '\n' ' ')"

[ -n "$GNSS" ] && ln -sf "$GNSS" "$BN/gnssmodem"
[ -n "$WCN" ] && ln -sf "$WCN" "$BN/wcnmodem"
[ -n "$USERDATA" ] && ln -sf "$USERDATA" "$BN/userdata"
[ -n "$SOCKO" ] && ln -sf "$SOCKO" "$BN/socko"
[ -n "$L_MODEM" ] && ln -sf "$L_MODEM" "$BN/l_modem"
[ -n "$L_LDSP" ] && ln -sf "$L_LDSP" "$BN/l_ldsp"
[ -n "$L_GDSP" ] && ln -sf "$L_GDSP" "$BN/l_gdsp"
[ -n "$L_AGDSP" ] && ln -sf "$L_AGDSP" "$BN/l_agdsp"
[ -n "$PM_SYS" ] && ln -sf "$PM_SYS" "$BN/pm_sys"
[ -n "$NVITEM" ] && ln -sf "$NVITEM" "$BN/nvitem"
[ -n "$PRODNV" ] && ln -sf "$PRODNV" "$BN/prodnv"

busybox mkdir -p /dev/block/by-name
for p in "$BN"/*; do
    [ -e "$p" ] && ln -sf "$p" "/dev/block/by-name/$(busybox basename "$p")"
done
# LTE and Wi-Fi boards must not share a MAC on the same AP.
if busybox grep -q 'androidboot.em.model=SM-X205' /proc/cmdline; then
    WIFI_MAC=02:00:00:00:00:02
else
    WIFI_MAC=02:00:00:00:00:01
fi
printf '%s\n' "$WIFI_MAC" > /data/vendor/wifi/wifimac_temp.txt
printf '%s\n' "$WIFI_MAC" > /data/vendor/wifi/wifimac.txt
log "wifi_mac=$WIFI_MAC"

echo on > /sys/devices/platform/sprd-marlin3/power/control 2>/dev/null || true
echo on > /sys/devices/virtual/misc/wcn/power/control 2>/dev/null || true

if [ -e /proc/mdbg/at_cmd ]; then
    echo startwcn > /proc/mdbg/at_cmd &
    log startwcn_sent
else
    log no_mdbg
fi
busybox sleep 5

# Bind-mount patched Wi-Fi driver over /mnt/socko/sprdwl_ng.ko if present
if [ -f /root/sprdwl_ng.ko ]; then
    busybox mount --bind /root/sprdwl_ng.ko /mnt/socko/sprdwl_ng.ko 2>/dev/null || true
elif [ -f /root/modules/sprdwl_ng.ko ]; then
    busybox mount --bind /root/modules/sprdwl_ng.ko /mnt/socko/sprdwl_ng.ko 2>/dev/null || true
fi

WL_KO=/mnt/socko/sprdwl_ng.ko
if [ -f /root/sprdwl_ng.ko ]; then
    WL_KO=/root/sprdwl_ng.ko
elif [ -f /root/modules/sprdwl_ng.ko ]; then
    WL_KO=/root/modules/sprdwl_ng.ko
fi

if busybox insmod "$WL_KO" 2>>/root/hw-up.log || busybox insmod -f "$WL_KO" 2>>/root/hw-up.log || insmod "$WL_KO" 2>>/root/hw-up.log; then
    log sprdwl_ok
else
    log sprdwl_fail
fi
busybox sleep 2
log "ifaces=$(busybox ls /sys/class/net 2>/dev/null | busybox tr '\n' ' ')"

if [ -e /sys/class/net/wlan0 ]; then
    echo on > /sys/devices/platform/sprd-marlin3/power/control 2>/dev/null || true
    echo on > /sys/devices/virtual/misc/wcn/power/control 2>/dev/null || true
    ip link set wlan0 address "$WIFI_MAC" 2>>/root/hw-up.log
    ip link set wlan0 up 2>>/root/hw-up.log && log wlan0_up || log wlan0_up_fail
    nm_ok=0
    if [ -x /usr/sbin/NetworkManager ]; then
        # Phosh Settings talks to NM, so give NM the interface if it comes up.
        start_system_bus
        start_udevd
        if [ -x /usr/lib/polkit-1/polkitd ] && ! busybox pidof polkitd >/dev/null 2>&1; then
            busybox setsid /usr/lib/polkit-1/polkitd --no-debug </dev/null >/root/polkit.log 2>&1 &
        fi
        if ! busybox pidof NetworkManager >/dev/null 2>&1; then
            busybox setsid /usr/sbin/NetworkManager --no-daemon </dev/null >/root/nm.log 2>&1 &
        fi
        i=0
        while [ "$i" -lt 20 ]; do
            if nmcli -t -f DEVICE,STATE device 2>/dev/null | busybox grep -q "^wlan0:connected"; then
                nm_ok=1
                break
            fi
            i=$((i + 1))
            busybox sleep 2
        done
        log "nm_wlan0=$nm_ok"
    fi
    if [ "$nm_ok" = 0 ]; then
        # NM did not take the radio; fall back to the hand-rolled path and tell
        # start-phosh.sh not to restart NM on top of it.
        : > /run/gta8-wifi-manual
        busybox killall NetworkManager 2>/dev/null
        busybox mkdir -p /run/wpa_supplicant /usr/share/udhcpc
        if [ -f /root/wpa_supplicant.conf ]; then
            busybox cp -f /root/wpa_supplicant.conf /etc/wpa_supplicant.conf 2>/dev/null || true
        fi
        busybox grep -q p2p_disabled /etc/wpa_supplicant.conf 2>/dev/null \
            || busybox sed -i '2ap2p_disabled=1' /etc/wpa_supplicant.conf
        # -B daemonize exits immediately on this image; setsid keeps it running.
        busybox killall wpa_supplicant 2>/dev/null
        busybox setsid /opt/wifi/wpa_supplicant -i wlan0 -Dnl80211 \
            -c /etc/wpa_supplicant.conf -f /tmp/wpa.log </dev/null >/dev/null 2>&1 &
        log wpa_started
        i=0
        while [ "$i" -lt 20 ]; do
            st=$(/opt/wifi/iw dev wlan0 link 2>/dev/null | busybox head -1)
            log "link[$i]=$st"
            case "$st" in
                Connected*) break ;;
            esac
            i=$((i + 1))
            busybox sleep 2
        done
        busybox udhcpc -i wlan0 -n -t 10 -T 3 -s /usr/share/udhcpc/default.script >>/root/hw-up.log 2>&1 && log dhcp_ok || log dhcp_fail
        log "addr=$(ip -4 addr show wlan0 2>/dev/null | busybox grep inet || echo none)"
    fi
    if command -v dropbear >/dev/null 2>&1; then
        mkdir -p /etc/dropbear
        [ -f /etc/dropbear/dropbear_rsa_host_key ] || dropbearkey -t rsa -f /etc/dropbear/dropbear_rsa_host_key >/dev/null 2>&1
        dropbear -E -p 22 >/tmp/dropbear.log 2>&1 &
        log dropbear_ok
    fi
else
    log no_wlan0
fi

# debian-init backgrounded a subshell that hammers brightness 40. Same cmdline
# as PID 1, PPID 1 — kill it so Phosh can keep the panel at 128.
initcmd=$(busybox tr "\0" " " < /proc/1/cmdline)
for d in /proc/[0-9]*; do
    pid=${d#/proc/}
    [ "$pid" = 1 ] && continue
    pp=$(busybox awk '{print $4}' "$d/stat" 2>/dev/null) || continue
    [ "$pp" = 1 ] || continue
    cmd=$(busybox tr "\0" " " < "$d/cmdline" 2>/dev/null)
    [ "$cmd" = "$initcmd" ] || continue
    kill "$pid" 2>/dev/null
    log "killed_init_subshell $pid"
done

busybox sync
log WIFI_DONE

# Headphone jack only. Speakers (aw882xx) oops this kernel.
if [ -x /root/audio-boot.sh ]; then
    log audio_boot
    busybox sh /root/audio-boot.sh </dev/null >>/root/audio-boot.log 2>&1
    log audio_boot_done
fi

# X205 Focaltech (FT8201): IC stays in boot ROM until focaltech_ts_fw_boe.bin
# is loaded. Debian ships a udev stub that NAK every firmware request.
if busybox grep -q 'androidboot.em.model=SM-X205' /proc/cmdline; then
    busybox mkdir -p /lib/firmware /vendor/firmware /sdcard /root/firmware
    if [ -f /root/firmware/focaltech_ts_fw_boe.bin ]; then
        busybox cp -n /root/firmware/focaltech_ts_fw_boe.bin /lib/firmware/ 2>/dev/null || true
        busybox cp -n /root/firmware/focaltech_ts_fw_boe.bin /vendor/firmware/ 2>/dev/null || true
        busybox cp -n /root/firmware/focaltech_ts_fw_boe.bin /sdcard/1 2>/dev/null || true
    fi
    if [ -f /lib/udev/rules.d/50-firmware.rules ]; then
        busybox mv /lib/udev/rules.d/50-firmware.rules \
            /lib/udev/rules.d/50-firmware.rules.disabled
        log fts_udev_stub_disabled
    fi
    if ! busybox grep -q 'Name="fts_ts"' /proc/bus/input/devices 2>/dev/null; then
        if [ ! -e /sys/class/gpio/gpio145 ]; then
            echo 145 > /sys/class/gpio/export 2>/dev/null || true
        fi
        echo out > /sys/class/gpio/gpio145/direction 2>/dev/null || true
        echo 0 > /sys/class/gpio/gpio145/value 2>/dev/null || true
        busybox sleep 1
        echo 1 > /sys/class/gpio/gpio145/value 2>/dev/null || true
        busybox sleep 1
        echo spi2.2 > /sys/bus/spi/drivers/fts_ts/bind 2>/dev/null || true
        log fts_reset_bind
    else
        log fts_already_present
    fi
    # No DEVTMPFS: a late-bound fts_ts has no /dev/input node until we mknod it.
    for e in /sys/class/input/event*; do
        [ -e "$e/device/name" ] || continue
        [ "$(busybox cat "$e/device/name")" = fts_ts ] || continue
        node=/dev/input/${e##*/}
        if [ ! -e "$node" ]; then
            majmin=$(busybox cat "$e/dev")
            busybox mknod -m 660 "$node" c "${majmin%:*}" "${majmin#*:}"
            busybox chown root:input "$node" 2>/dev/null || true
            log "fts_mknod $node"
        fi
    done
    udevadm trigger --action=add --subsystem-match=input 2>/dev/null || true
fi

# Mali must be up before start-phosh decides between gles2 and pixman.
if [ -x /root/gpu-up.sh ]; then
    log gpu_up
    busybox sh /root/gpu-up.sh </dev/null >>/root/gpu-up.log 2>&1
    log gpu_up_done
fi

# Ramdisk still starts drmstep; start-phosh kills it and takes the DRM master.
if [ -x /root/start-phosh.sh ] && ! busybox pidof phosh >/dev/null 2>&1; then
    log phosh_boot
    busybox sh /root/start-phosh.sh </dev/null >>/root/phosh-boot.log 2>&1
    log phosh_boot_done
fi

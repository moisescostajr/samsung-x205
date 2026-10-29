#!/bin/bash
# GTA8 vendor bring-up for the systemd image.
#
# The vendor 4.14 kernel has no devicetree entries for Debian's init, so this
# script does what the ramdisk used to do by hand: mount the Android vendor
# partitions, load the vendor Wi-Fi/Mali modules, hand Wi-Fi to
# NetworkManager, boot the LTE modem, and prepare the panel.
#
# It is started by gta8-hw.service before phosh.service. It must not start
# dbus, udev, NetworkManager, ModemManager or the compositor: systemd owns
# those here.
set -u

LOG=/var/log/gta8-bringup.log
mkdir -p /var/log
exec >>"$LOG" 2>&1
log() { echo "gta8-hw [$(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0)s]: $*"; }
log "=== bring-up start ==="

# systemd starts this before udev has necessarily finished coldplug. The
# vendor partitions are resolved through sysfs, but their /dev nodes must
# exist before losetup/mount can use them.
udevadm settle --timeout=15 2>/dev/null || true
for _i in $(seq 1 15); do
    [ -e /sys/block/mmcblk0 ] && break
    sleep 1
done

# Keep the USB-C ACM console and the usb0 network link across switch_root.
# (The initramfs configures the gadget, but its configfs mount disappears.)
if [ -x /root/usb-role.sh ]; then
    /bin/busybox sh /root/usb-role.sh gadget >/dev/null 2>&1 || \
        log "usb-role gadget setup failed"
fi

BY_NAME=/dev/block/platform/soc/soc:ap-apb/71400000.sdio/by-name

part_by_name() {
    local want="$1" p n
    for p in /sys/block/mmcblk0/mmcblk0p*; do
        [ -e "$p/uevent" ] || continue
        n=$(sed -n 's/^PARTNAME=//p' "$p/uevent")
        if [ "$n" = "$want" ]; then
            echo "/dev/${p##*/}"
            return 0
        fi
    done
    return 1
}

# ---------------------------------------------------------------- block nodes
mkdir -p "$BY_NAME" /dev/block/by-name /dev/socket /data/vendor/wifi
mknod /dev/loop0 b 7 0 2>/dev/null || true
mknod /dev/loop1 b 7 1 2>/dev/null || true
for name in l_modem l_ldsp l_gdsp l_agdsp pm_sys wcnmodem gnssmodem \
            nvitem prodnv miscdata socko super userdata; do
    dev=$(part_by_name "$name") || continue
    ln -sfn "$dev" "$BY_NAME/$name"
    ln -sfn "$dev" "/dev/block/by-name/$name"
done

# ------------------------------------------------------------------- vendor
SUPER=$(part_by_name super) || true
if [ -n "${SUPER:-}" ] && ! grep -q ' /vendor ' /proc/mounts; then
    mkdir -p /mnt/vendor /vendor
    # SM-X205 shifts the dynamic partitions; try the LTE offset first.
    for off in 4315938816 4281335808; do
        losetup -d /dev/loop0 2>/dev/null || true
        if losetup -o "$off" /dev/loop0 "$SUPER" 2>/dev/null && \
           mount -t ext4 -o ro /dev/loop0 /mnt/vendor 2>/dev/null; then
            mount --bind /mnt/vendor /vendor 2>/dev/null || true
            log "vendor mounted at offset $off"
            break
        fi
    done
fi

SOCKO=$(part_by_name socko) || true
if [ -n "${SOCKO:-}" ] && ! grep -q ' /mnt/socko ' /proc/mounts; then
    mkdir -p /mnt/socko
    mount -t ext4 -o ro "$SOCKO" /mnt/socko && log "socko mounted" \
        || log "socko mount failed"
fi

# --------------------------------------------------------------- Wi-Fi MAC
if grep -q 'androidboot.em.model=SM-X205' /proc/cmdline; then
    WIFI_MAC=02:00:00:00:00:02
else
    WIFI_MAC=02:00:00:00:00:01
fi
printf '%s\n' "$WIFI_MAC" > /data/vendor/wifi/wifimac_temp.txt
printf '%s\n' "$WIFI_MAC" > /data/vendor/wifi/wifimac.txt

echo on > /sys/devices/platform/sprd-marlin3/power/control 2>/dev/null || true
echo on > /sys/devices/virtual/misc/wcn/power/control 2>/dev/null || true
sleep 2

# -------------------------------------------------------------- Wi-Fi module
WL_KO=""
for k in /root/sprdwl_ng.ko /root/modules/sprdwl_ng.ko /mnt/socko/sprdwl_ng.ko; do
    [ -f "$k" ] && WL_KO="$k" && break
done
if [ -n "$WL_KO" ]; then
    # Prefer the patched module over the stock one in socko.
    case "$WL_KO" in
        /root/*)
            [ -f /mnt/socko/sprdwl_ng.ko ] && \
                mount --bind "$WL_KO" /mnt/socko/sprdwl_ng.ko 2>/dev/null || true
            ;;
    esac
    if ! lsmod | grep -q '^sprdwl_ng '; then
        if insmod "$WL_KO" 2>/dev/null || /bin/busybox insmod -f "$WL_KO" 2>/dev/null; then
            log "sprdwl_ng loaded from $WL_KO"
        else
            log "sprdwl_ng load failed: $WL_KO"
        fi
    fi
fi
sleep 2

if [ -e /sys/class/net/wlan0 ]; then
    ip link set wlan0 address "$WIFI_MAC" 2>/dev/null || true
    ip link set wlan0 up 2>/dev/null || true
    log "wlan0 up ($WIFI_MAC)"
else
    log "wlan0 missing"
fi

# ------------------------------------------------------------- Wi-Fi profile
BOOT_MNT=/mnt/gta8boot
mount_config_partition() {
    [ -d "$BOOT_MNT" ] || mkdir -p "$BOOT_MNT"
    grep -q " $BOOT_MNT " /proc/mounts && return 0
    mount -t vfat -o ro,noatime LABEL=GTA8CFG "$BOOT_MNT" 2>/dev/null || \
        mount -t vfat -o ro,noatime /dev/mmcblk1p2 "$BOOT_MNT" 2>/dev/null || true
}

ensure_wifi_profile() {
    local conf="" psk
    WIFI_SSID=""
    for c in "$BOOT_MNT/wpa_supplicant.conf" /root/wpa_supplicant.conf \
             /etc/wpa_supplicant.conf; do
        if [ -f "$c" ]; then conf="$c"; break; fi
    done
    [ -n "$conf" ] || { log "no wpa_supplicant.conf"; return 0; }

    WIFI_SSID=$(sed -n 's/^[[:space:]]*ssid[[:space:]]*=[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' "$conf" | head -1)
    psk=$(sed -n 's/^[[:space:]]*psk[[:space:]]*=[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' "$conf" | head -1)
    [ -n "$WIFI_SSID" ] || { log "wpa_supplicant.conf has no ssid"; return 0; }

    cp -f "$conf" /etc/wpa_supplicant.conf 2>/dev/null || true
    if nmcli -t -f NAME connection show 2>/dev/null | grep -Fxq "$WIFI_SSID"; then
        # Keep the profile in sync when the file on GTA8CFG changes.
        if [ -n "$psk" ]; then
            nmcli connection modify "$WIFI_SSID" \
                wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk" >/dev/null 2>&1 || \
                log "could not update Wi-Fi PSK"
        fi
        nmcli connection modify "$WIFI_SSID" connection.autoconnect yes \
            ipv4.method auto ipv6.method disabled >/dev/null 2>&1 || true
        log "NM profile already exists: $WIFI_SSID"
        return 0
    fi
    nmcli connection add type wifi con-name "$WIFI_SSID" ifname wlan0 \
        ssid "$WIFI_SSID" >/dev/null 2>&1 || {
            log "nmcli connection add failed"
            return 1
        }
    if [ -n "$psk" ]; then
        nmcli connection modify "$WIFI_SSID" \
            wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk" >/dev/null 2>&1 || \
            log "could not set Wi-Fi PSK"
    fi
    nmcli connection modify "$WIFI_SSID" connection.autoconnect yes \
        ipv4.method auto ipv6.method disabled >/dev/null 2>&1 || true
    log "created NM profile: $WIFI_SSID"
}

mkdir -p /etc/NetworkManager/conf.d /etc/NetworkManager/system-connections
cat > /etc/NetworkManager/conf.d/gta8.conf <<'EOF'
[main]
no-auto-default=*
dns=default

[device]
wifi.scan-rand-mac-address=no

[keyfile]
unmanaged-devices=interface-name:usb0
EOF

# wlan0 is created after udev's coldplug, so re-announce it and let NM reload.
udevadm trigger --action=add --subsystem-match=net 2>/dev/null || true
udevadm trigger --action=add --subsystem-match=ieee80211 2>/dev/null || true
udevadm settle --timeout=10 2>/dev/null || true

mount_config_partition

for _i in $(seq 1 20); do
    nmcli -t general status 2>/dev/null | grep -q '^connected' && break
    sleep 1
done
nmcli networking on >/dev/null 2>&1 || true
nmcli radio wifi on >/dev/null 2>&1 || true
if [ -e /sys/class/net/wlan0 ]; then
    nmcli device set wlan0 managed yes >/dev/null 2>&1 || true
fi
ensure_wifi_profile
nmcli connection reload >/dev/null 2>&1 || true
if [ -n "${WIFI_SSID:-}" ]; then
    nmcli connection up "$WIFI_SSID" >/dev/null 2>&1 || true
fi
if [ -e /sys/class/net/wlan0 ]; then
    nmcli device connect wlan0 >/dev/null 2>&1 || true
fi

# ------------------------------------------------------- Wi-Fi fallback
# NetworkManager normally drives the vendor driver, but the 4.14 cfg80211
# ABI is old and NM/wpa_supplicant can leave wlan0 unavailable on some boots.
# The image carries the wpa_supplicant/iw build that was validated on this
# board; use it if NM did not get a link.
wifi_connected() {
    nmcli -t -f DEVICE,STATE device 2>/dev/null | grep -qx 'wlan0:connected'
}

if [ -e /sys/class/net/wlan0 ] && ! wifi_connected; then
    if [ -f /etc/wpa_supplicant.conf ] && \
       [ -x /opt/wifi/wpa_supplicant ]; then
        log "NM did not connect wlan0; trying the vendor wpa_supplicant"
        nmcli device set wlan0 managed no >/dev/null 2>&1 || true
        systemctl stop wpa_supplicant.service >/dev/null 2>&1 || true
        /bin/busybox killall wpa_supplicant >/dev/null 2>&1 || true
        ip link set wlan0 up >/dev/null 2>&1 || true
        grep -q p2p_disabled /etc/wpa_supplicant.conf 2>/dev/null || \
            sed -i '2ap2p_disabled=1' /etc/wpa_supplicant.conf 2>/dev/null || true
        LD_LIBRARY_PATH=/opt/wifi/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} \
            /bin/busybox setsid /opt/wifi/wpa_supplicant -i wlan0 -Dnl80211 \
            -c /etc/wpa_supplicant.conf -f /tmp/wpa.log \
            </dev/null >/dev/null 2>&1 &
        i=0
        while [ "$i" -lt 30 ]; do
            st=$(LD_LIBRARY_PATH=/opt/wifi/lib /opt/wifi/iw dev wlan0 link 2>/dev/null | head -1)
            case "$st" in
                Connected*) break ;;
            esac
            i=$((i + 1))
            sleep 1
        done
        if LD_LIBRARY_PATH=/opt/wifi/lib /opt/wifi/iw dev wlan0 link 2>/dev/null | grep -q '^Connected'; then
            log "wpa_supplicant connected wlan0"
            /bin/busybox udhcpc -i wlan0 -n -t 10 -T 3 \
                -s /usr/share/udhcpc/default.script \
                >>/var/log/gta8-bringup.log 2>&1 && \
                log "udhcpc lease acquired" || log "udhcpc failed"
        else
            log "wpa_supplicant did not connect; see /tmp/wpa.log"
        fi
    else
        log "no /etc/wpa_supplicant.conf or /opt/wifi/wpa_supplicant"
    fi
fi

# --------------------------------------------------------------- touch panel
# X205 Focaltech: the controller stays in boot ROM until the firmware file is
# available. Harmless on Himax units.
if grep -q 'androidboot.em.model=SM-X205' /proc/cmdline; then
    mkdir -p /lib/firmware /vendor/firmware
    for src in /root/firmware/focaltech_ts_fw_boe.bin /mnt/socko/focaltech_ts_fw_boe.bin; do
        [ -f "$src" ] || continue
        cp -n "$src" /lib/firmware/ 2>/dev/null || true
        cp -n "$src" /vendor/firmware/ 2>/dev/null || true
    done
    [ -f /lib/udev/rules.d/50-firmware.rules ] && \
        mv /lib/udev/rules.d/50-firmware.rules \
           /lib/udev/rules.d/50-firmware.rules.disabled 2>/dev/null || true
    if ! grep -q 'Name="fts_ts"' /proc/bus/input/devices 2>/dev/null; then
        [ -e /sys/class/gpio/gpio145 ] || echo 145 > /sys/class/gpio/export 2>/dev/null || true
        echo out > /sys/class/gpio/gpio145/direction 2>/dev/null || true
        echo 0 > /sys/class/gpio/gpio145/value 2>/dev/null || true
        sleep 1
        echo 1 > /sys/class/gpio/gpio145/value 2>/dev/null || true
        sleep 1
        echo spi2.2 > /sys/bus/spi/drivers/fts_ts/bind 2>/dev/null || true
        log "fts_ts reset+bind"
    fi
fi

# ------------------------------------------------------------------- modules
if [ -x /root/gpu-up.sh ]; then
    log "gpu-up"
    /bin/busybox sh /root/gpu-up.sh >/dev/null 2>&1 || true
fi
if [ -x /root/audio-boot.sh ]; then
    log "audio-boot"
    /bin/busybox sh /root/audio-boot.sh >/dev/null 2>&1 || true
fi

# ----------------------------------------------------------------------- LTE
# ModemManager is already running; lte-up only creates the modem ports and
# starts the vendor modem daemon.
if grep -q 'androidboot.em.model=SM-X205' /proc/cmdline && [ -x /root/lte-up.sh ]; then
    log "lte-up"
    GTA8_FORCE_LTE=1 /bin/busybox sh /root/lte-up.sh --force >/dev/null 2>&1 &
fi

# -------------------------------------------------------------------- sensors
mkdir -p /tmp
if [ -f /opt/kmsbin/propstub.so ]; then
    cp -f /opt/kmsbin/propstub.so /tmp/propstub.so 2>/dev/null || true
fi
if [ -x /root/sensors-up.sh ]; then
    log "sensors-up"
    /bin/busybox sh /root/sensors-up.sh >/dev/null 2>&1 || true
    if [ -x /root/gta8-sensors.py ] && ! pidof python3 >/dev/null 2>&1; then
        XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 \
            setsid python3 /root/gta8-sensors.py >>/var/log/gta8-sensors.log 2>&1 &
    fi
fi

# -------------------------------------------------------------------- display
# The DPU writeback engine wipes the scanout layers after a few vsyncs unless
# it is turned off. start-phosh.sh did this on the manual image; do it here for
# systemd.
echo 0 > /sys/module/dpu_r4p0/parameters/max_vsync_count 2>/dev/null || true
echo 1 > /sys/class/display/dispc0/refresh 2>/dev/null || true
echo 128 > /sys/class/backlight/sprd_backlight/brightness 2>/dev/null || true
echo 0 > /sys/class/backlight/sprd_backlight/bl_power 2>/dev/null || true

log "=== bring-up done ==="

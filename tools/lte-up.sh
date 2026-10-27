#!/bin/busybox sh
# Bring up the Unisoc LTE modem (Communication Processor) on Samsung Galaxy Tab A8 SM-X205.
#
# Safe to run multiple times. Logs to /root/lte-up.log.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/kmsbin
LOG=/root/lte-up.log
: > "$LOG"

log() {
    echo "gta8-lte [$(busybox cut -d. -f1 /proc/uptime 2>/dev/null || echo 0)s]: $*" | tee -a "$LOG"
}

log "=== LTE BRING-UP START ==="

# 1. Check device model
if ! busybox grep -q 'androidboot.em.model=SM-X205' /proc/cmdline 2>/dev/null && [ "$GTA8_FORCE_LTE" != "1" ] && [ "$1" != "--force" ]; then
    log "Device is not SM-X205 (LTE). If you want to force bring-up, pass --force or GTA8_FORCE_LTE=1"
    # Still check if l_modem partition exists before bailing
    has_l_modem=0
    for u in /sys/block/mmcblk0/mmcblk0p*/uevent; do
        if busybox grep -q 'PARTNAME=l_modem' "$u" 2>/dev/null; then
            has_l_modem=1
            break
        fi
    done
    if [ "$has_l_modem" = "0" ]; then
        log "No l_modem partition found. Exiting."
        exit 0
    fi
    log "Found l_modem partition despite cmdline; continuing."
fi

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

# 2. Setup block-by-name symlinks
BN=/dev/block/platform/soc/soc:ap-apb/71400000.sdio/by-name
busybox mkdir -p "$BN" /dev/block/by-name /dev/socket /data/vendor

for name in l_modem l_ldsp l_gdsp l_agdsp pm_sys wcnmodem gnssmodem nvitem prodnv miscdata socko super userdata; do
    dev=$(part_by_name "$name")
    if [ -n "$dev" ]; then
        ln -sf "$dev" "$BN/$name"
        ln -sf "$dev" "/dev/block/by-name/$name"
        log "part $name -> $dev"
    fi
done

# 3. Mount vendor partition if missing
if ! busybox grep -q " /vendor " /proc/mounts && ! busybox grep -q " /mnt/vendor " /proc/mounts; then
    SUPER=$(part_by_name super)
    if [ -n "$SUPER" ]; then
        busybox mkdir -p /mnt/vendor /vendor
        busybox mknod /dev/loop0 b 7 0 2>/dev/null || true
        busybox losetup -d /dev/loop0 2>/dev/null || true
        if busybox losetup -o 4281335808 /dev/loop0 "$SUPER" 2>/dev/null; then
            if busybox mount -t ext4 -o ro /dev/loop0 /mnt/vendor 2>/dev/null; then
                busybox mount --bind /mnt/vendor /vendor 2>/dev/null || true
                log "vendor partition mounted"
            fi
        fi
    fi
fi

# 4. Mount system partition for Android runtime libraries if missing
if ! busybox grep -q " /system " /proc/mounts && ! busybox grep -q " /mnt/system " /proc/mounts; then
    SUPER=$(part_by_name super)
    if [ -n "$SUPER" ]; then
        busybox mkdir -p /mnt/system /system
        busybox mknod /dev/loop1 b 7 1 2>/dev/null || true
        busybox losetup -d /dev/loop1 2>/dev/null || true
        if busybox losetup -o 1048576 /dev/loop1 "$SUPER" 2>/dev/null; then
            if busybox mount -t ext4 -o ro /dev/loop1 /mnt/system 2>/dev/null; then
                busybox mount --bind /mnt/system/system /system 2>/dev/null || true
                log "system partition mounted"
            fi
        fi
    fi
fi

if [ -d /system/bin/bootstrap ]; then
    busybox mkdir -p /apex/com.android.runtime/bin
    if ! busybox grep -q " /apex/com.android.runtime/bin " /proc/mounts; then
        busybox mount --bind /system/bin/bootstrap /apex/com.android.runtime/bin 2>/dev/null || true
    fi
fi

# 5. Build/ensure propstub.so (wifionly=0 for SM-X205)
PROP_SRC=""
for p in /root/propstub.c /tmp/propstub.c /opt/kmsbin/propstub.c /tools/propstub.c; do
    [ -f "$p" ] && PROP_SRC="$p" && break
done

if [ -n "$PROP_SRC" ]; then
    gcc -shared -fPIC -nostdlib -O2 -o /tmp/propstub.so "$PROP_SRC" 2>/dev/null && log "compiled propstub.so from $PROP_SRC"
fi

if [ ! -f /tmp/propstub.so ]; then
    log "warning: /tmp/propstub.so missing"
fi

# 6. Ensure device nodes have proper permissions
chmod 666 /proc/pmic/* /dev/pmic /dev/trusty-ipc-dev0 /dev/sctl_pm /dev/sctl_ldsp /dev/cproc* 2>/dev/null || true
touch /tmp/gta8-lte

# 7. Start or restart modem_control daemon
if busybox pidof modem_control >/dev/null 2>&1; then
    # If already running, check if stty_lte* exists; if not, restart it to apply new props
    if ! ls /dev/stty_lte* >/dev/null 2>&1; then
        log "restarting existing modem_control with LTE configuration"
        busybox killall modem_control 2>/dev/null || true
        busybox sleep 1
    else
        log "modem_control already running and stty_lte ports exist"
    fi
fi

if ! busybox pidof modem_control >/dev/null 2>&1 && [ -x /vendor/bin/modem_control ]; then
    log "starting /vendor/bin/modem_control"
    export LD_LIBRARY_PATH=/vendor/lib64:/system/lib64
    export LD_PRELOAD=/tmp/propstub.so
    export ANDROID_ROOT=/system
    export ANDROID_DATA=/data
    cd /root
    busybox setsid /vendor/bin/modem_control >> /root/modem_control.err 2>&1 &
fi

# 8. Wait for modem TTY interfaces
log "waiting for modem serial channels..."
found=0
for i in $(busybox seq 1 20); do
    if ls /dev/stty_lte* >/dev/null 2>&1; then
        found=1
        break
    fi
    busybox sleep 1
done

if [ "$found" = "1" ]; then
    STTY_DEVS=$(ls -d /dev/stty_lte* 2>/dev/null | busybox tr '\n' ' ')
    SPIPE_DEVS=$(ls -d /dev/spipe_lte* 2>/dev/null | busybox tr '\n' ' ')
    log "SUCCESS: Found modem ports: $STTY_DEVS"
    log "Pipe ports: $SPIPE_DEVS"
    chmod 666 /dev/stty_lte* /dev/spipe_lte* /dev/sbuf_lte* 2>/dev/null || true
    chown root:dialout /dev/stty_lte* 2>/dev/null || true
else
    log "WARNING: /dev/stty_lte* not detected after 20s. Check /root/modem_control.err and dmesg."
fi

# 9. Check for network data plane interfaces
NET_DEVS=$(ls /sys/class/net 2>/dev/null | busybox grep -E 'lte|seth|sipa|wwan|rmnet' | busybox tr '\n' ' ')
if [ -n "$NET_DEVS" ]; then
    log "Found cellular network interface(s): $NET_DEVS"
    for dev in $NET_DEVS; do
        ip link set "$dev" up 2>/dev/null || true
    done
fi

# 10. Notify udev and ModemManager
if [ -d /run/udev ]; then
    udevadm control --reload 2>/dev/null || true
    udevadm trigger --subsystem-match=tty 2>/dev/null || true
    udevadm trigger --subsystem-match=net 2>/dev/null || true
fi

if [ -x /usr/sbin/ModemManager ] && ! busybox pidof ModemManager >/dev/null 2>&1; then
    log "starting ModemManager"
    busybox setsid /usr/sbin/ModemManager </dev/null >/root/mm.log 2>&1 &
fi

log "=== LTE BRING-UP FINISHED ==="

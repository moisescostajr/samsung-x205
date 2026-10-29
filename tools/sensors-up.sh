#!/bin/busybox sh
# Bring up SM-X200 AON (pm_sys) + BMI320 / STK3X1X / MMC5603 on the sensor hub.
# Never write /proc/pmic/stop — that hard-resets the board.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/kmsbin

log() { echo "gta8-sensors [$(busybox cut -d. -f1 /proc/uptime)s]: $*" >> /root/sensors-up.log; }

HUB=/sys/devices/virtual/sprd_sensorhub/sensor_hub
SHUB_STORE=/root/sensorhub

already_up() {
    [ "$(cat /proc/pmic/status 2>/dev/null)" = "started" ] || return 1
    busybox grep -q accelerometer_bmi320 "$HUB/sensor_info" 2>/dev/null
}

setup_android() {
    busybox mknod /dev/loop1 b 7 1 2>/dev/null || true
    if ! busybox grep -q " /mnt/system " /proc/mounts; then
        busybox mkdir -p /mnt/system
        # X200/X205 put Super at different GPT indexes; resolve by name.
        super=""
        for u in /sys/block/mmcblk0/mmcblk0p*/uevent; do
            if busybox grep -q 'PARTNAME=super' "$u" 2>/dev/null; then
                super=/dev/$(busybox basename "$(busybox dirname "$u")")
                break
            fi
        done
        [ -n "$super" ] || return 1
        busybox losetup -d /dev/loop1 2>/dev/null || true
        busybox losetup -o 1048576 /dev/loop1 "$super"
        busybox mount -t ext4 -o ro /dev/loop1 /mnt/system || return 1
    fi
    if ! busybox grep -q " /system " /proc/mounts; then
        busybox mkdir -p /system
        busybox mount --bind /mnt/system/system /system || return 1
    fi
    busybox mkdir -p /apex/com.android.runtime/bin
    if ! busybox grep -q " /apex/com.android.runtime/bin " /proc/mounts; then
        busybox mount --bind /system/bin/bootstrap /apex/com.android.runtime/bin
    fi
    ln -sf /dev/pmic /dev/pmsys
    busybox mkdir -p /dev/block/by-name /dev/socket /data/vendor
    for u in /sys/block/mmcblk0/mmcblk0p*/uevent; do
        name=$(busybox grep PARTNAME "$u" | busybox cut -d= -f2)
        dev=/dev/$(busybox basename $(busybox dirname "$u"))
        [ -n "$name" ] && ln -sf "$dev" "/dev/block/by-name/$name"
    done
    # modem_control concatenates a missing path_read with "pm_sys"
    ln -sf /dev/mmcblk0p20 /root/not_findpm_sys
    ln -sf /dev/mmcblk0p20 /not_findpm_sys
    chmod 666 /proc/pmic/* /dev/mmcblk0p20 /dev/pmic /dev/trusty-ipc-dev0 /dev/sctl_pm 2>/dev/null || true
    # Precompiled in CI; the image does not need a compiler.
    [ -f /tmp/propstub.so ] || \
        busybox cp -f /opt/kmsbin/propstub.so /tmp/propstub.so 2>/dev/null || true
}

setup_sensorhub_fs() {
    busybox mkdir -p /tmp/vupper /tmp/vwork "$SHUB_STORE"
    if ! busybox grep -q "overlay on /mnt/vendor" /proc/mounts; then
        mount -t overlay overlay -o lowerdir=/mnt/vendor,upperdir=/tmp/vupper,workdir=/tmp/vwork /mnt/vendor || true
    fi
    busybox mkdir -p /mnt/vendor/sensorhub
    if [ -z "$(ls -A /mnt/vendor/sensorhub 2>/dev/null)" ] && [ -n "$(ls -A "$SHUB_STORE" 2>/dev/null)" ]; then
        cp -a "$SHUB_STORE"/. /mnt/vendor/sensorhub/
    fi
}

extract_opcodes() {
    if [ -f /mnt/vendor/sensorhub/shub_fw_accelerometer_bmi320 ]; then
        return 0
    fi
    [ -f /opt/kmsbin/extract.so ] || { log no_extract_so; return 1; }
    LD_LIBRARY_PATH=/vendor/lib64:/system/lib64 \
        LD_PRELOAD=/tmp/propstub.so:/vendor/lib64/libsensorsdrvcfg.so:/opt/kmsbin/extract.so \
        ANDROID_ROOT=/system /system/bin/true || true
    cp -a /mnt/vendor/sensorhub/. "$SHUB_STORE/" 2>/dev/null || true
}

start_modem_control() {
    if busybox pidof modem_control >/dev/null 2>&1; then
        return 0
    fi
    busybox mkdir -p /dev/socket
    [ -f /tmp/logdw.py ] && ! busybox ps | busybox grep -q '[l]ogdw.py' && \
        busybox setsid python3 /tmp/logdw.py >> /root/logdw.out 2>&1 &
    export LD_LIBRARY_PATH=/vendor/lib64:/system/lib64
    export LD_PRELOAD=/tmp/propstub.so
    export ANDROID_ROOT=/system
    export ANDROID_DATA=/data
    cd /root
    busybox setsid /vendor/bin/modem_control >> /root/modem_control.err 2>&1 &
    i=0
    while [ "$i" -lt 20 ]; do
        busybox sleep 1
        [ "$(cat /proc/pmic/status 2>/dev/null)" = "started" ] && return 0
        i=$((i + 1))
    done
    return 1
}

load_opcodes() {
    echo "accelerometer_bmi320,accelerometer_bmi220,accelerometer_icm42607" \
        > /sys/module/shub_core/parameters/acc_firms
    echo "gyroscope_bmi320,gyroscope_bmi220,gyroscope_icm42607" \
        > /sys/module/shub_core/parameters/gryo_firms
    echo "magnetic_mmc5603,magnetic_qmc6308" \
        > /sys/module/shub_core/parameters/mag_firms
    echo "light_stk3x1x,light_ltr578als,light_ls8500,dual_light" \
        > /sys/module/shub_core/parameters/light_firms
    echo 0 > "$HUB/mcu_mode"
    timeout 25 cat "$HUB/op_download" >/dev/null 2>&1 || true
}

enable_sensors() {
    echo "1 1" > "$HUB/enable"
    echo "5 1" > "$HUB/enable"
    echo "1 1 10 0" > "$HUB/batch"
    echo "5 1 2 0" > "$HUB/batch"
    IIO=/sys/bus/iio/devices/iio:device0
    echo 0 > "$IIO/buffer/enable" 2>/dev/null || true
    echo 0 > "$IIO/scan_elements/in_accel_x&y_en" 2>/dev/null || true
    echo 1 > "$IIO/scan_elements/in_accel_x_en"
    echo 1 > "$IIO/scan_elements/in_accel_y_en"
    echo 1 > "$IIO/scan_elements/in_accel_z_en"
    echo 1 > "$IIO/scan_elements/in_timestamp_en"
    echo sprd-sensor-dev0 > "$IIO/trigger/current_trigger"
    echo 1 > "$IIO/buffer/enable"
}

: > /root/sensors-up.log
log start
if already_up; then
    log already_up
    enable_sensors
    log enabled
    exit 0
fi
setup_android || { log android_fail; exit 1; }
setup_sensorhub_fs
start_modem_control || { log modem_control_fail status=$(cat /proc/pmic/status); exit 1; }
log pmic=$(cat /proc/pmic/status)
extract_opcodes
load_opcodes
log info="$(busybox tr '\n' ' ' < "$HUB/sensor_info")"
enable_sensors
log done

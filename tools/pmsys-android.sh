#!/bin/busybox sh
# Bind enough of Android userspace for /vendor/bin/modem_control.
set -e
busybox mknod /dev/loop1 b 7 1 2>/dev/null || true
if ! busybox grep -q " /mnt/system " /proc/mounts; then
	busybox mkdir -p /mnt/system
	busybox losetup -d /dev/loop1 2>/dev/null || true
	busybox losetup -o 1048576 /dev/loop1 /dev/mmcblk0p46
	busybox mount -t ext4 -o ro /dev/loop1 /mnt/system
fi
if ! busybox grep -q " /system " /proc/mounts; then
	busybox mkdir -p /system
	busybox mount --bind /mnt/system/system /system
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
chmod 666 /proc/pmic/* /dev/mmcblk0p20 /dev/pmic /dev/trusty-ipc-dev0 /dev/sctl_pm 2>/dev/null || true
gcc -shared -fPIC -nostdlib -O2 -o /tmp/propstub.so /tmp/propstub.c
echo android_ok

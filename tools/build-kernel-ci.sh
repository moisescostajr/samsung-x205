#!/bin/bash
set -e

echo "=== 1. Cloning Kernel ==="
if [ ! -d "kernel" ]; then
    git clone --depth 1 https://github.com/handicraftsman/kernel_samsung_gta8lte.git kernel
fi

echo "=== 2. Applying Patches ==="
# Patch 1: Neutralize SC2730 PMIC watchdog in kernel driver (prevents cm4_watchdog_timeout)
(cd kernel && python3 ../tools/patch-watchdog.py)

# Patch 2: Wire real DRM PRIME export for wlroots/compositor
(cd kernel && python3 ../tools/patch-prime-vt.py)

# Force NO_YAML in dtc to avoid host libyaml mismatch
sed -i 's/HOST_EXTRACFLAGS := -I\$(src)\/libfdt/HOST_EXTRACFLAGS := -I\$(src)\/libfdt -DNO_YAML/' kernel/scripts/dtc/Makefile
sed -i 's/dtc-objs.*+=.*yamltree.o/# disabled yaml/' kernel/scripts/dtc/Makefile 2>/dev/null || true

# Strip -Werror and variants from all Makefiles across kernel tree
python3 -c "
import os, re
for root, _, files in os.walk('kernel'):
    for f in files:
        if f.startswith('Makefile') or f.startswith('Kbuild') or f.endswith('.mk'):
            p = os.path.join(root, f)
            try:
                with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                    content = fp.read()
                new_c = re.sub(r'-Werror([a-zA-Z0-9_=-]+)?', '-Wno-error', content)
                if new_c != content:
                    with open(p, 'w', encoding='utf-8') as fp:
                        fp.write(new_c)
            except Exception:
                pass
"

# Fix mm/filemap.c non-prototype declaration
sed -i 's/static void filemap_tracing_mark_end()/static void filemap_tracing_mark_end(void)/' kernel/mm/filemap.c 2>/dev/null || true

# Fix Samsung hx9031a.c stack buffer overflow in Is_Wifi_Version (causes crashdump on SM-X205)
sed -i 's/char board_string\[12\]/char board_string[128]/' kernel/drivers/misc/sar/hx9031/hx9031a.c 2>/dev/null || true
sed -i 's/BOARD_INFO"%s"/BOARD_INFO"%127s"/' kernel/drivers/misc/sar/hx9031/hx9031a.c 2>/dev/null || true

# Fix relative TRACE_INCLUDE_PATH . in trace headers (sprd_dfs_trace.h etc.)
python3 -c "
import os, re

pat = re.compile(r'#define\s+TRACE_INCLUDE_PATH\s+\.\s*$', re.MULTILINE)
for root, _, files in os.walk('kernel'):
    for f in files:
        if f.endswith('.h'):
            p = os.path.join(root, f)
            try:
                with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                    content = fp.read()
                if pat.search(content):
                    rel_dir = os.path.relpath(root, 'kernel')
                    fixed = pat.sub(f'#define TRACE_INCLUDE_PATH ../../{rel_dir}', content)
                    with open(p, 'w', encoding='utf-8') as fp:
                        fp.write(fixed)
                    print(f'Fixed trace path in {p} -> ../../{rel_dir}')
            except Exception:
                pass
"
echo 'ccflags-y += -I$(src)' >> kernel/drivers/devfreq/sprd/Makefile 2>/dev/null || true

# Ensure KBUILD_CFLAGS silences GCC 11 warning-errors
echo 'KBUILD_CFLAGS += -Wno-error -Wno-strict-prototypes -Wno-format-zero-length -Wno-pointer-sign -Wno-array-bounds' >> kernel/Makefile

echo "=== 3. Configuring Kernel ==="
cd kernel
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- sprd_sharkl5Pro_defconfig
scripts/config --enable CONFIG_PID_NS
scripts/config --enable CONFIG_IKCONFIG
scripts/config --enable CONFIG_IKCONFIG_PROC

# Enable Virtual Terminal & Framebuffer Console on tablet display (fbcon)
scripts/config --enable CONFIG_FB
scripts/config --enable CONFIG_VT
scripts/config --enable CONFIG_VT_CONSOLE
scripts/config --enable CONFIG_HW_CONSOLE
scripts/config --enable CONFIG_FRAMEBUFFER_CONSOLE
scripts/config --enable CONFIG_FRAMEBUFFER_CONSOLE_DETECT_PRIMARY
scripts/config --enable CONFIG_FRAMEBUFFER_CONSOLE_ROTATION
scripts/config --enable CONFIG_FONTS
scripts/config --enable CONFIG_FONT_8x16
scripts/config --enable CONFIG_FONT_SUPPORT
scripts/config --enable CONFIG_LOGO
scripts/config --enable CONFIG_DRM_FBDEV_EMULATION

# Default console command line
scripts/config --enable CONFIG_CMDLINE_EXTEND
scripts/config --set-str CONFIG_CMDLINE "console=tty0 console=ttyGS0,115200 androidboot.wdten=NULL"

echo "=== 4. Compiling Kernel Image ==="
make -j"$(nproc)" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error" Image
cd ..

echo "=== 5. Compiling Kernel Modules ==="
KDIR="$(pwd)/kernel"
mkdir -p boot-pack/modules tools/modules

make -C "$KDIR" M="$(pwd)/tools/pmicwdt" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error" modules 2>/dev/null || true
cp -f tools/pmicwdt/pmicwdt_off.ko boot-pack/modules/ 2>/dev/null || true
cp -f tools/pmicwdt/pmicwdt_off.ko tools/modules/ 2>/dev/null || true

make -C "$KDIR" M="$(pwd)/tools/agdspup" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error" modules 2>/dev/null || true
cp -f tools/agdspup/*.ko boot-pack/modules/ 2>/dev/null || true
cp -f tools/agdspup/*.ko tools/modules/ 2>/dev/null || true

make -C "$KDIR" M="$(pwd)/tools/dmaheap" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error" modules 2>/dev/null || true
cp -f tools/dmaheap/*.ko boot-pack/modules/ 2>/dev/null || true
cp -f tools/dmaheap/*.ko tools/modules/ 2>/dev/null || true

echo "=== 6. Building Ramdisk ==="
mkdir -p ramdisk_root/bin ramdisk_root/sbin ramdisk_root/dev ramdisk_root/proc ramdisk_root/sys ramdisk_root/mnt/root ramdisk_root/tmp ramdisk_root/config ramdisk_root/modules

wget -q -O busybox.deb http://ports.ubuntu.com/pool/main/b/busybox/busybox-static_1.30.1-7ubuntu3_arm64.deb
dpkg-deb -x busybox.deb bb_temp
cp -f bb_temp/bin/busybox ramdisk_root/bin/busybox
rm -rf bb_temp busybox.deb
chmod 755 ramdisk_root/bin/busybox

# Install modules into ramdisk
cp -f boot-pack/modules/pmicwdt_off.ko ramdisk_root/pmicwdt_off.ko 2>/dev/null || true
cp -f boot-pack/modules/*.ko ramdisk_root/modules/ 2>/dev/null || true

# Bundle tools inside ramdisk for automatic initial setup
tar -czf ramdisk_root/tools.tar.gz -C tools .

cat > ramdisk_root/debian-init << 'DEBEOF'
#!/bin/busybox sh
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/kmsbin
export HOME=/root
trap '' HUP INT QUIT TSTP TTIN TTOU

busybox mount -o remount,rw /
busybox mkdir -p /dev/pts /dev/shm /run /tmp /dev/dri /config /root/modules
busybox mount -t tmpfs -o mode=755,nosuid,nodev tmpfs /run 2>/dev/null || true
busybox mount -t tmpfs tmpfs /tmp 2>/dev/null || true
busybox mount -t devpts devpts /dev/pts 2>/dev/null || true

# Neutralize hardware watchdog
echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
for ko in /root/modules/pmicwdt_off.ko /modules/pmicwdt_off.ko /pmicwdt_off.ko; do
    if [ -f "$ko" ]; then
        busybox insmod "$ko" 2>/dev/null && break
    fi
done

# Keep watchdog timer fed
for w in /sys/class/watchdog/watchdog*; do
    [ -e "$w/dev" ] || continue
    wdev=$(busybox cat "$w/dev")
    wname=${w##*/}
    busybox mknod -m 600 "/dev/$wname" c "${wdev%:*}" "${wdev#*:}" 2>/dev/null || true
done
busybox mknod -m 666 /dev/watchdog c 10 130 2>/dev/null || true
busybox sh -c 'trap "" HUP INT QUIT; while true; do
    for n in /dev/watchdog /dev/watchdog0 /dev/watchdog1; do
        [ -c "$n" ] && echo 1 > "$n" 2>/dev/null || true
        [ -c "$n" ] && echo V > "$n" 2>/dev/null || true
    done
    echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
    busybox sleep 4
done' </dev/null >/dev/null 2>&1 &

busybox mknod -m 600 /dev/console c 5 1 2>/dev/null || true
busybox mknod -m 666 /dev/tty0 c 4 0 2>/dev/null || true
busybox mknod -m 666 /dev/tty1 c 4 1 2>/dev/null || true
busybox mknod -m 666 /dev/null c 1 3 2>/dev/null || true
busybox mknod -m 666 /dev/zero c 1 5 2>/dev/null || true
busybox mknod -m 600 /dev/ttyGS0 c 509 0 2>/dev/null || true
busybox mount -t proc proc /proc 2>/dev/null || true
busybox mount -t sysfs sysfs /sys 2>/dev/null || true
busybox mdev -s 2>/dev/null || true

# Run hardware bringup in background
if [ -x /root/hw-up.sh ]; then
    busybox sh /root/hw-up.sh </dev/null >> /root/hw-up.log 2>&1 &
fi

# Shell on tablet screen console
busybox setsid sh -c 'trap "" HUP INT QUIT TSTP TTIN TTOU
while true; do
    echo "" > /dev/tty1
    echo "==========================================================" > /dev/tty1
    echo "  Debian 12 (bookworm) - Samsung Galaxy Tab A8 LTE (X205)  " > /dev/tty1
    echo "==========================================================" > /dev/tty1
    echo "Type commands here or connect via USB serial (ttyGS0)." > /dev/tty1
    busybox sh <>/dev/tty1 >&0 2>&0
    busybox sleep 1
done' </dev/null >/dev/null 2>&1 &

# Serial shell on USB ACM
busybox setsid sh -c 'trap "" HUP INT QUIT TSTP TTIN TTOU
while true; do
    echo "gta8lte debian prompt" > /dev/ttyGS0
    busybox sh <>/dev/ttyGS0 >&0 2>&0
    busybox sleep 1
done' </dev/null >/dev/null 2>&1 &

while true; do
    echo V > /dev/watchdog 2>/dev/null || true
    busybox sleep 5
done
DEBEOF
chmod 755 ramdisk_root/debian-init

cat > ramdisk_root/init << 'EOF'
#!/bin/busybox sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
BUSYBOX=/bin/busybox
trap '' HUP INT QUIT TSTP TTIN TTOU

$BUSYBOX mkdir -p /proc /sys /dev /tmp /run /mnt/root /config /modules
$BUSYBOX mount -t proc proc /proc
$BUSYBOX mount -t sysfs sysfs /sys
$BUSYBOX mount -t tmpfs tmpfs /dev

$BUSYBOX mknod -m 600 /dev/console c 5 1 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/tty c 5 0 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/tty0 c 4 0 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/tty1 c 4 1 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/null c 1 3 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/zero c 1 5 2>/dev/null || true
$BUSYBOX mknod -m 600 /dev/kmsg c 1 11 2>/dev/null || true
$BUSYBOX mdev -s 2>/dev/null || true

# Direct output to console (tablet display)
exec </dev/console >/dev/console 2>&1

echo ""
echo "============================================================"
echo "    Debian GNU/Linux 12 - Samsung Galaxy Tab A8 LTE (X205)   "
echo "============================================================"
echo "[*] Kernel booted successfully."

# 1. Neutralize hardware watchdogs immediately
echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
if [ -f /pmicwdt_off.ko ]; then
    $BUSYBOX insmod /pmicwdt_off.ko 2>/dev/null && echo "[*] SC2730 PMIC watchdog neutralized." || true
elif [ -f /modules/pmicwdt_off.ko ]; then
    $BUSYBOX insmod /modules/pmicwdt_off.ko 2>/dev/null && echo "[*] SC2730 PMIC watchdog neutralized." || true
fi

for w in /sys/class/watchdog/watchdog*; do
    [ -e "$w/dev" ] || continue
    wdev=$($BUSYBOX cat "$w/dev")
    wname=${w##*/}
    $BUSYBOX mknod -m 600 "/dev/$wname" c "${wdev%:*}" "${wdev#*:}" 2>/dev/null || true
done
$BUSYBOX mknod -m 666 /dev/watchdog c 10 130 2>/dev/null || true

# Background keepalive loop
$BUSYBOX sh -c 'trap "" HUP INT QUIT
while true; do
    for n in /dev/watchdog /dev/watchdog0 /dev/watchdog1; do
        [ -c "$n" ] && echo 1 > "$n" 2>/dev/null || true
        [ -c "$n" ] && echo V > "$n" 2>/dev/null || true
    done
    echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
    $BUSYBOX sleep 4
done' </dev/null >/dev/null 2>&1 &

# 2. Setup USB ACM gadget
$BUSYBOX mount -t configfs none /config 2>/dev/null || true
G=/config/usb_gadget/g1
if [ -d /config/usb_gadget ]; then
    $BUSYBOX mkdir -p "$G/strings/0x409" "$G/functions/acm.gs0" "$G/configs/b.1/strings/0x409" 2>/dev/null || true
    echo 0x1d6b > "$G/idVendor" 2>/dev/null || true
    echo 0x0104 > "$G/idProduct" 2>/dev/null || true
    echo "Galaxy Tab A8 LTE" > "$G/strings/0x409/product" 2>/dev/null || true
    $BUSYBOX ln -sfn "$G/functions/acm.gs0" "$G/configs/b.1/f1" 2>/dev/null || true
    echo musb-hdrc.0.auto > "$G/UDC" 2>/dev/null || true
fi
$BUSYBOX mknod -m 600 /dev/ttyGS0 c 509 0 2>/dev/null || true

# 3. Search for MicroSD root partition
echo "[*] Scanning for MicroSD card partitions..."
ROOT_DEV=""
for i in $($BUSYBOX seq 1 25); do
    $BUSYBOX mdev -s 2>/dev/null || true
    for p in /sys/class/block/mmcblk1p* /sys/class/block/mmcblk0p*; do
        [ -e "$p/dev" ] || continue
        pdev=$($BUSYBOX cat "$p/dev")
        pname=${p##*/}
        $BUSYBOX mknod -m 660 "/dev/$pname" b "${pdev%:*}" "${pdev#*:}" 2>/dev/null || true
    done

    # Probe mmcblk1 partitions (microSD)
    for p in /dev/mmcblk1p1 /dev/mmcblk1p2 /dev/mmcblk1p*; do
        [ -b "$p" ] || continue
        if $BUSYBOX mount -t ext4 -o ro "$p" /mnt/root 2>/dev/null; then
            if [ -d /mnt/root/etc ] && [ -d /mnt/root/bin -o -d /mnt/root/usr ]; then
                ROOT_DEV="$p"
                $BUSYBOX umount /mnt/root
                break 2
            fi
            $BUSYBOX umount /mnt/root 2>/dev/null || true
        fi
    done
    $BUSYBOX sleep 1
done

if [ -n "$ROOT_DEV" ] && $BUSYBOX mount -t ext4 -o rw "$ROOT_DEV" /mnt/root 2>/dev/null; then
    echo "[*] MicroSD card found: $ROOT_DEV mounted successfully!"

    # 4. Install latest debian-init
    $BUSYBOX cp -f /debian-init /mnt/root/sbin/init 2>/dev/null || true
    $BUSYBOX chmod 755 /mnt/root/sbin/init 2>/dev/null || true

    # 5. Extract/update tools and modules
    echo "[*] Deploying userspace tools & kernel modules..."
    $BUSYBOX mkdir -p /mnt/root/root /mnt/root/root/modules /mnt/root/etc/udev/rules.d /mnt/root/etc/dpkg/dpkg.cfg.d
    echo 'path-exclude=/sbin/init' > /mnt/root/etc/dpkg/dpkg.cfg.d/protect-sbin-init
    if [ -f /tools.tar.gz ]; then
        $BUSYBOX tar -xzf /tools.tar.gz -C /mnt/root/root/ 2>/dev/null || true
        $BUSYBOX cp -f /mnt/root/root/udev/*.rules /mnt/root/etc/udev/rules.d/ 2>/dev/null || true
        $BUSYBOX chmod +x /mnt/root/root/*.sh /mnt/root/root/*.py 2>/dev/null || true
    fi
    if [ -d /modules ]; then
        $BUSYBOX cp -rf /modules/* /mnt/root/root/modules/ 2>/dev/null || true
    fi

    # 6. Bind mounts
    $BUSYBOX mkdir -p /mnt/root/proc /mnt/root/sys /mnt/root/dev /mnt/root/dev/pts /mnt/root/run /mnt/root/config
    $BUSYBOX mount -o bind /proc /mnt/root/proc 2>/dev/null || true
    $BUSYBOX mount -o bind /sys /mnt/root/sys 2>/dev/null || true
    $BUSYBOX mount -o bind /dev /mnt/root/dev 2>/dev/null || true

    echo "[*] Starting Debian GNU/Linux system (switch_root)..."
    exec $BUSYBOX switch_root /mnt/root /sbin/init
fi

echo "[!] ERROR: Failed to find or mount Debian root partition on microSD card!"
echo "[!] Spawning rescue shell on console..."
while true; do
    $BUSYBOX sh
    $BUSYBOX sleep 2
done
EOF
chmod 755 ramdisk_root/init

(cd ramdisk_root && find . | cpio -H newc -o) | gzip -9 > boot-pack/ramdisk.cpio.gz

echo "=== 7. Assembling Boot Pack Artifacts ==="
cp kernel/arch/arm64/boot/Image boot-pack/Image-v57

echo "[OK] Boot pack successfully assembled in boot-pack/:"
ls -lh boot-pack/

#!/bin/bash
set -e

echo "=== 1. Cloning Kernel ==="
if [ ! -d "kernel" ]; then
    git clone --depth 1 https://github.com/handicraftsman/kernel_samsung_gta8lte.git kernel
fi

echo "=== 2. Applying Patches ==="
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
scripts/config --enable CONFIG_VT
scripts/config --enable CONFIG_VT_CONSOLE
scripts/config --enable CONFIG_IKCONFIG
scripts/config --enable CONFIG_IKCONFIG_PROC

echo "=== 4. Compiling Kernel Image ==="
make -j"$(nproc)" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error" Image
cd ..

echo "=== 5. Compiling Kernel Modules ==="
KDIR="$(pwd)/kernel"
mkdir -p boot-pack/modules

make -C "$KDIR" M="$(pwd)/tools/pmicwdt" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error" modules 2>/dev/null || true
cp -f tools/pmicwdt/pmicwdt_off.ko boot-pack/modules/ 2>/dev/null || true

make -C "$KDIR" M="$(pwd)/tools/agdspup" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error" modules 2>/dev/null || true
cp -f tools/agdspup/*.ko boot-pack/modules/ 2>/dev/null || true

make -C "$KDIR" M="$(pwd)/tools/dmaheap" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error" modules 2>/dev/null || true
cp -f tools/dmaheap/*.ko boot-pack/modules/ 2>/dev/null || true

echo "=== 6. Building Ramdisk ==="
mkdir -p ramdisk_root/bin ramdisk_root/sbin ramdisk_root/dev ramdisk_root/proc ramdisk_root/sys ramdisk_root/mnt/root ramdisk_root/tmp ramdisk_root/config

wget -q -O busybox.deb http://ports.ubuntu.com/pool/main/b/busybox/busybox-static_1.30.1-7ubuntu3_arm64.deb
dpkg-deb -x busybox.deb bb_temp
cp -f bb_temp/bin/busybox ramdisk_root/bin/busybox
rm -rf bb_temp busybox.deb
chmod 755 ramdisk_root/bin/busybox

cat > ramdisk_root/init << 'EOF'
#!/bin/busybox sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
BUSYBOX=/bin/busybox
trap '' HUP INT QUIT TSTP TTIN TTOU

$BUSYBOX mkdir -p /proc /sys /dev /tmp /run /mnt/root /config
$BUSYBOX mount -t proc proc /proc
$BUSYBOX mount -t sysfs sysfs /sys
$BUSYBOX mount -t tmpfs tmpfs /dev
$BUSYBOX mknod -m 666 /dev/null c 1 3 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/zero c 1 5 2>/dev/null || true
$BUSYBOX mknod -m 600 /dev/kmsg c 1 11 2>/dev/null || true
$BUSYBOX mdev -s 2>/dev/null || true

$BUSYBOX sh -c 'trap "" HUP INT QUIT; while true; do echo V > /dev/watchdog 2>/dev/null; sleep 8; done' </dev/null >/dev/null 2>&1 &

echo "gta8-init: waiting for mmcblk1p1 (microSD)..."
for i in $(busybox seq 1 15); do
    [ -e /dev/mmcblk1p1 ] && break
    $BUSYBOX sleep 1
done

if $BUSYBOX mount -t ext4 -o rw /dev/mmcblk1p1 /mnt/root 2>/dev/null || $BUSYBOX mount /dev/mmcblk1p1 /mnt/root; then
    echo "gta8-init: microSD mounted successfully, switching root to Debian!"
    exec $BUSYBOX switch_root /mnt/root /sbin/init
fi

echo "gta8-init: FAIL - could not mount /dev/mmcblk1p1"
while true; do $BUSYBOX sleep 10; done
EOF
chmod 755 ramdisk_root/init

(cd ramdisk_root && find . | cpio -H newc -o) | gzip -9 > boot-pack/ramdisk.cpio.gz

echo "=== 7. Assembling Boot Pack Artifacts ==="
cp kernel/arch/arm64/boot/Image boot-pack/Image-v57

echo "[OK] Boot pack successfully assembled in boot-pack/:"
ls -lh boot-pack/

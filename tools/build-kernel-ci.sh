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

# Patch 3: keep the panel alive once a compositor takes over
(cd kernel && python3 ../tools/patch-display.py)

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

# Patch kernel/module.c: allow vendor modules with mismatched genksyms CRC (GCC vs Clang),
# bypass vermagic strict matching, and neutralize mod_sysfs_setup crash caused by mismatched vendor ELF section attributes
python3 -c "
import re

with open('kernel/kernel/module.c', 'r') as f:
    c = f.read()

# 1. CRC & Vermagic bypass for vendor modules (mali_gondul.ko, sprdwl_ng.ko)
pat_ver = re.compile(r'static (?:inline )?int check_version\(const struct load_info \*info,\s+const char \*symname,\s+struct module \*mod,\s+const s32 \*crc\)\s*\{.*?\n\}', re.DOTALL)
c = pat_ver.sub('''static int check_version(const struct load_info *info,
			 const char *symname,
			 struct module *mod,
			 const s32 *crc)
{
	return 1;
}''', c)

pat_magic = re.compile(r'static (?:inline )?int same_magic\(const char \*amagic,\s+const char \*bmagic,\s+bool has_crcs\)\s*\{.*?\n\}', re.DOTALL)
c = pat_magic.sub('''static inline int same_magic(const char *amagic, const char *bmagic,
			     bool has_crcs)
{
	return 1;
}''', c)

# 2. Prevent kernel crash in mod_sysfs_setup due to vendor module ELF section/attribute mismatch
pat_setup = re.compile(r'static int mod_sysfs_setup\(struct module \*mod,\s+const struct load_info \*info,\s+struct kernel_param \*kparam,\s+unsigned int num_params\)\s*\{.*?\n\}', re.DOTALL)
c = pat_setup.sub('''static int mod_sysfs_setup(struct module *mod,
			   const struct load_info *info,
			   struct kernel_param *kparam,
			   unsigned int num_params)
{
	return 0;
}''', c)

pat_fini = re.compile(r'static void mod_sysfs_fini\(struct module \*mod\)\s*\{.*?\n\}', re.DOTALL)
c = pat_fini.sub('''static void mod_sysfs_fini(struct module *mod)
{
}''', c)

pat_tear = re.compile(r'static void mod_sysfs_teardown\(struct module \*mod\)\s*\{.*?\n\}', re.DOTALL)
c = pat_tear.sub('''static void mod_sysfs_teardown(struct module *mod)
{
}''', c)

with open('kernel/kernel/module.c', 'w') as f:
    f.write(c)
print('Patched kernel/module.c: bypassed CRC/vermagic and neutralized mod_sysfs_setup crash')
"

# Patch kernel/arch/arm64/lib/strlen.S: add safety guard to WEAK(strlen) / __pi_strlen against NULL or invalid low addresses
python3 -c "
with open('kernel/arch/arm64/lib/strlen.S', 'r') as f:
    s = f.read()

if '.Lsafe_strlen_entry' not in s:
    s = s.replace('WEAK(strlen)', '''WEAK(strlen)
	cmp	srcin, #0x1000
	b.lo	.Lsafe_strlen_entry
''')
    s = s.replace('ENDPIPROC(strlen)', '''.Lsafe_strlen_entry:
	mov	len, #0
	ret
ENDPIPROC(strlen)''')
    with open('kernel/arch/arm64/lib/strlen.S', 'w') as f:
        f.write(s)
    print('Patched kernel/arch/arm64/lib/strlen.S: guarded strlen against page zero faults')
"

# Patch drivers/misc/sprdwcn/wcn_bus.c: export missing symbols for sprdwl_ng.ko Wi-Fi
python3 -c "
with open('kernel/drivers/misc/sprdwcn/wcn_bus.c', 'r') as f:
    c = f.read()
if 'sprd_wlan_power_status_sync' not in c:
    c += '''

int sprd_wlan_power_status_sync(int status)
{
	return 0;
}
EXPORT_SYMBOL_GPL(sprd_wlan_power_status_sync);

int marlin_get_wcn_xpe_efuse_data(void *data, int size)
{
	return 0;
}
EXPORT_SYMBOL_GPL(marlin_get_wcn_xpe_efuse_data);
'''
    with open('kernel/drivers/misc/sprdwcn/wcn_bus.c', 'w') as f:
        f.write(c)
    print('Exported sprd_wlan_power_status_sync and marlin_get_wcn_xpe_efuse_data in wcn_bus.c')
"

# Ensure KBUILD_CFLAGS silences GCC 11 warning-errors
echo 'KBUILD_CFLAGS += -Wno-error -Wno-strict-prototypes -Wno-format-zero-length -Wno-pointer-sign -Wno-array-bounds' >> kernel/Makefile

echo "=== 3. Configuring Kernel ==="
cd kernel
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- sprd_sharkl5Pro_defconfig

# Match exact stock Samsung X205 firmware vermagic so /mnt/socko vendor modules (sprdwl_ng.ko, mali_gondul.ko) load cleanly
scripts/config --set-str CONFIG_LOCALVERSION "-29056031-abX205XXS6DYG7"
scripts/config --disable CONFIG_LOCALVERSION_AUTO
scripts/config --enable CONFIG_MODULE_FORCE_LOAD
touch .scmversion

scripts/config --enable CONFIG_PID_NS
scripts/config --enable CONFIG_IKCONFIG
scripts/config --enable CONFIG_IKCONFIG_PROC

# systemd / udev / Phosh need a real /dev and a few namespace options that the
# Android defconfig leaves out. DEVTMPFS is what lets udev populate /dev.
scripts/config --enable CONFIG_DEVTMPFS
scripts/config --enable CONFIG_DEVTMPFS_MOUNT
scripts/config --enable CONFIG_FHANDLE
scripts/config --enable CONFIG_SYSVIPC
scripts/config --enable CONFIG_IPC_NS
scripts/config --enable CONFIG_USER_NS
scripts/config --enable CONFIG_AUTOFS4_FS
scripts/config --enable CONFIG_KCMP
scripts/config --enable CONFIG_NAMESPACES
scripts/config --enable CONFIG_UTS_NS
scripts/config --enable CONFIG_NET_NS
scripts/config --enable CONFIG_CGROUPS
scripts/config --enable CONFIG_CGROUP_DEVICE
scripts/config --enable CONFIG_CGROUP_PIDS
scripts/config --enable CONFIG_CGROUP_NET_PRIO
scripts/config --enable CONFIG_CGROUP_NET_CLASSID
scripts/config --enable CONFIG_TMPFS
scripts/config --enable CONFIG_EXT4_FS
scripts/config --enable CONFIG_INOTIFY_USER
scripts/config --enable CONFIG_SIGNALFD
scripts/config --enable CONFIG_TIMERFD
scripts/config --enable CONFIG_EPOLL
scripts/config --enable CONFIG_EVENTFD
scripts/config --enable CONFIG_SECCOMP
scripts/config --enable CONFIG_SECCOMP_FILTER

# The microSD provisioning partition is FAT32. The vendor defconfig does not
# always include FAT/VFAT, and without it /mnt/gta8boot silently fails.
scripts/config --enable CONFIG_FAT_FS
scripts/config --enable CONFIG_VFAT_FS
scripts/config --enable CONFIG_MSDOS_FS
scripts/config --enable CONFIG_NLS
scripts/config --enable CONFIG_NLS_CODEPAGE_437
scripts/config --enable CONFIG_NLS_ISO8859_1
scripts/config --enable CONFIG_NLS_UTF8

# losetup is used to mount the vendor super/socko images at boot.
scripts/config --enable CONFIG_BLK_DEV_LOOP

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
scripts/config --disable CONFIG_CMDLINE_FORCE
scripts/config --disable CONFIG_CMDLINE_FROM_BOOTLOADER
scripts/config --enable CONFIG_CMDLINE_EXTEND
scripts/config --set-str CONFIG_CMDLINE "console=tty0 console=ttyGS0,115200 androidboot.wdten=NULL systemd.unified_cgroup_hierarchy=0"

# Enable native USB Ethernet networking (CDC-ECM and CDC-NCM) for macOS and Linux host sharing
scripts/config --enable CONFIG_USB_CONFIGFS_ECM
scripts/config --enable CONFIG_USB_CONFIGFS_ECM_SUBSET
scripts/config --enable CONFIG_USB_CONFIGFS_NCM

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

# Precompiled property stub for the vendor modem daemon. Doing it here keeps a
# cross compiler out of the Debian image.
echo "=== 5a. Compiling propstub ==="
aarch64-linux-gnu-gcc -shared -fPIC -nostdlib -O2 \
    -o boot-pack/propstub.so tools/propstub.c

# Sensor-hub opcode extractor: same idea, precompiled so the image needs no gcc.
cat > /tmp/gta8-extract.c <<'EOF'
void _Z23SensorHubOpcodeExtratorv(void);
__attribute__((constructor)) void go(void)
{
	_Z23SensorHubOpcodeExtratorv();
}
EOF
aarch64-linux-gnu-gcc -shared -fPIC -nostdlib -O2 \
    -o boot-pack/extract.so /tmp/gta8-extract.c

echo "=== 5b. Compiling drmstep bootsplash ==="
mkdir -p libdrm_temp boot-pack/opt/kmsbin tools/opt/kmsbin
rm -rf libdrm_temp/root libdrm_temp/libdrm2.deb libdrm_temp/libdrm-dev.deb
DRM_POOL="https://ports.ubuntu.com/pool/main/libd/libdrm"
DRM_VER="2.4.113-2~ubuntu0.22.04.1"

drm_fetch() {
    if curl -fsSL --retry 3 --connect-timeout 20 -o "$2" "$1"; then
        return 0
    fi
    echo "[WARN] download failed: $1" >&2
    return 1
}

drm_ok=1
drm_fetch "$DRM_POOL/libdrm2_${DRM_VER}_arm64.deb" libdrm_temp/libdrm2.deb || drm_ok=0
drm_fetch "$DRM_POOL/libdrm-dev_${DRM_VER}_arm64.deb" libdrm_temp/libdrm-dev.deb || drm_ok=0

if [ "$drm_ok" = 1 ]; then
    dpkg-deb -x libdrm_temp/libdrm2.deb libdrm_temp/root || drm_ok=0
    dpkg-deb -x libdrm_temp/libdrm-dev.deb libdrm_temp/root || drm_ok=0
fi

# Recreate relative symlink for libdrm.so in extracted tree
LIBDIR="$(pwd)/libdrm_temp/root/usr/lib/aarch64-linux-gnu"
if [ "$drm_ok" = 1 ] && [ -f libdrm_temp/root/usr/include/libdrm/xf86drm.h ] && [ -d "$LIBDIR" ]; then
    (cd "$LIBDIR" && ln -sf libdrm.so.2.4.0 libdrm.so && ln -sf libdrm.so.2.4.0 libdrm.so.2)
    aarch64-linux-gnu-gcc -O2 -Wall tools/drmstep.c \
        -Ilibdrm_temp/root/usr/include/libdrm \
        -Llibdrm_temp/root/usr/lib/aarch64-linux-gnu \
        -ldrm -Wl,-rpath,/lib:/usr/lib \
        -o boot-pack/drmstep-fb2 && echo "[OK] built drmstep-fb2" ||
        echo "[WARN] drmstep-fb2 build failed (splash disabled, boot continues)" >&2
else
    echo "[WARN] libdrm aarch64 headers/libs unavailable; skipping drmstep-fb2" >&2
fi

python3 -c "
import struct
from PIL import Image
try:
    im = Image.open('tools/splash/splash.png').convert('RGBA')
    r, g, b, a = im.split()
    bgra = Image.merge('RGBA', (b, g, r, a))
    w, h = im.size
    with open('boot-pack/splash.bgra', 'wb') as f:
        f.write(struct.pack('<II', w, h))
        f.write(bgra.tobytes())
    print(f'[OK] Generated splash.bgra ({w}x{h})')
except Exception as e:
    print(f'[WARN] splash.bgra generation: {e}')
" 2>/dev/null || true

cp -f boot-pack/drmstep-fb2 tools/drmstep-fb2 2>/dev/null || true
cp -f boot-pack/splash.bgra tools/splash.bgra 2>/dev/null || true

echo "=== 6. Building Ramdisk ==="
# The initramfs sources live in tools/initramfs and are shared with the local
# repack path. Download a static aarch64 busybox if the tree does not have one.
if [ ! -f tools/busybox-arm64 ]; then
    wget -q -O busybox.deb http://ports.ubuntu.com/pool/main/b/busybox/busybox-static_1.30.1-7ubuntu3_arm64.deb
    dpkg-deb -x busybox.deb bb_temp
    cp -f bb_temp/bin/busybox tools/busybox-arm64
    rm -rf bb_temp busybox.deb
fi
chmod +x tools/busybox-arm64 tools/build-ramdisk.sh
./tools/build-ramdisk.sh

echo "=== 7. Assembling Boot Pack Artifacts ==="
cp kernel/arch/arm64/boot/Image boot-pack/Image-v57

echo "[OK] Boot pack successfully assembled in boot-pack/:"
ls -lh boot-pack/

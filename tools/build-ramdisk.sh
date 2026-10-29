#!/bin/bash
# Build boot-pack/ramdisk.cpio.gz from tools/initramfs plus the kernel modules
# and vendor helper binaries collected in boot-pack/.
#
# Works both in CI (root) and on macOS (no root needed for cpio).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BOOT_PACK="${GTA8_BOOT_PACK:-$ROOT/boot-pack}"
TOOLS="$ROOT/tools"
BUSYBOX_BIN="${BUSYBOX:-$TOOLS/busybox-arm64}"
OUT="${RAMDISK_OUT:-$BOOT_PACK/ramdisk.cpio.gz}"

if [ ! -f "$BUSYBOX_BIN" ]; then
    echo "missing busybox: $BUSYBOX_BIN" >&2
    echo "run ./tools/build-kernel-ci.sh once or place an arm64 static busybox there" >&2
    exit 1
fi

stage="$(mktemp -d "${TMPDIR:-/tmp}/gta8-ramdisk.XXXXXX")"
trap 'rm -rf "$stage"' EXIT

mkdir -p "$stage"/{bin,dev,proc,sys,mnt/root,tmp,config,modules,opt/kmsbin,opt/wifi/lib,lib,usr/lib}

install -m 755 "$BUSYBOX_BIN" "$stage/bin/busybox"
install -m 755 "$TOOLS/initramfs/init" "$stage/init"
install -m 755 "$TOOLS/initramfs/debian-init" "$stage/debian-init"

# Kernel modules built by the kernel job (pmicwdt, dma_heap_compat, agdspup).
if [ -d "$BOOT_PACK/modules" ]; then
    cp -R "$BOOT_PACK/modules/." "$stage/modules/" 2>/dev/null || true
fi
if [ -f "$BOOT_PACK/modules/pmicwdt_off.ko" ]; then
    cp -f "$BOOT_PACK/modules/pmicwdt_off.ko" "$stage/pmicwdt_off.ko"
fi

# Early splash (optional).
for f in drmstep-fb2 splash.bgra; do
    if [ -f "$BOOT_PACK/$f" ]; then
        cp -f "$BOOT_PACK/$f" "$stage/opt/kmsbin/$f"
    elif [ -f "$TOOLS/$f" ]; then
        cp -f "$TOOLS/$f" "$stage/opt/kmsbin/$f"
    fi
done
# drmstep-fb2 is linked against libdrm in CI. Carry the matching library so
# the splash can run before the real rootfs exists.
for d in "$ROOT/libdrm_temp/root/usr/lib/aarch64-linux-gnu" \
         /usr/lib/aarch64-linux-gnu; do
    if [ -d "$d" ]; then
        cp -P "$d"/libdrm.so* "$stage/lib/" 2>/dev/null || true
        cp -P "$d"/libdrm.so* "$stage/usr/lib/" 2>/dev/null || true
        break
    fi
done

# Standalone wpa_supplicant/iw for the fallback path when NetworkManager
# cannot take the vendor interface.
if [ -d "$TOOLS/opt/wifi" ]; then
    cp -R "$TOOLS/opt/wifi/." "$stage/opt/wifi/"
fi

# Precompiled bionic property stub for the vendor modem daemon.
if [ -f "$BOOT_PACK/propstub.so" ]; then
    cp -f "$BOOT_PACK/propstub.so" "$stage/propstub.so"
fi

# Whole tools tree for /root. wpa_supplicant.conf is gitignored but lives here
# on a real checkout, so a locally built ramdisk carries the Wi-Fi profile.
tar -czf "$stage/tools.tar.gz" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    -C "$TOOLS" .

mkdir -p "$(dirname "$OUT")"
(
    cd "$stage"
    find . | cpio -H newc -o 2>/dev/null | gzip -9
) > "$OUT"

size=$(wc -c < "$OUT")
echo "ramdisk: $OUT ($size bytes)"
if [ "$size" -lt 100000 ]; then
    echo "ramdisk looks too small; refusing to use it" >&2
    exit 1
fi

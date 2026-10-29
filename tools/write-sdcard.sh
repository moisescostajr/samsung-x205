#!/bin/bash
# Write the GTA8 Debian + Phosh image to a microSD card on macOS.
#
# Usage:
#   sudo ./tools/write-sdcard.sh /dev/diskX [--force]
#
# The image is downloaded automatically with tools/fetch-image.py when
# rootfs/disk.raw is missing. The card gets two partitions:
#   gta8root  ext4  Debian + Phosh
#   GTA8CFG   FAT   copy wpa_supplicant.conf here before booting
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RAW_IMG="$REPO/rootfs/disk.raw"
FORCE=0

args=()
for a in "$@"; do
    case "$a" in
        --force) FORCE=1 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) args+=("$a") ;;
    esac
done

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root / with sudo:"
    echo "  sudo $0 /dev/diskX"
    exit 1
fi

if [ "${#args[@]}" -lt 1 ]; then
    echo "Error: target disk not specified."
    echo ""
    echo "Available external disks:"
    diskutil list external || true
    echo ""
    echo "Usage: sudo $0 /dev/diskX  (replace X with your SD card number, e.g. /dev/disk4)"
    exit 1
fi

TARGET="${args[0]}"
DISK=$(echo "$TARGET" | sed -E 's#(/dev/)?(disk[0-9]+).*#\2#')
case "$DISK" in
    disk[0-9]*) ;;
    *)
        echo "Error: '$TARGET' is not a macOS disk (expected /dev/diskX)."
        exit 1
        ;;
esac
RDISK="/dev/r${DISK}"

if [ "$FORCE" -ne 1 ]; then
    if diskutil info "$DISK" 2>/dev/null | grep -Eq 'Internal:[[:space:]]+Yes'; then
        echo "Refusing to erase internal disk $DISK. Pass --force if you really mean it."
        exit 1
    fi
fi

if [ ! -f "$RAW_IMG" ]; then
    echo "Image not found; downloading the latest release..."
    python3 "$REPO/tools/fetch-image.py"
fi
[ -f "$RAW_IMG" ] || { echo "Error: $RAW_IMG is still missing."; exit 1; }

IMG_SIZE=$(stat -f%z "$RAW_IMG")
CARD_BYTES=$(diskutil info "$DISK" 2>/dev/null | sed -n 's/.*Disk Size:.*(\([0-9]*\) Bytes).*/\1/p' | head -1)
if [ -n "${CARD_BYTES:-}" ] && [ "$CARD_BYTES" -lt "$IMG_SIZE" ]; then
    echo "Error: image is $((IMG_SIZE / 1073741824)) GiB but the card reports $((CARD_BYTES / 1073741824)) GiB."
    exit 1
fi

echo "=========================================================="
echo " Target Disk: /dev/$DISK ($RDISK)"
echo " Image File:  $RAW_IMG ($((IMG_SIZE / 1073741824)) GiB)"
echo "=========================================================="
echo "WARNING: ALL DATA ON /dev/$DISK WILL BE ERASED!"
echo ""
read -r -p "Type YES to proceed: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "Aborted by user."
    exit 1
fi

echo "1. Unmounting $DISK..."
diskutil unmountDisk "$DISK" || true

echo "2. Writing image to $RDISK (this can take several minutes)..."
dd if="$RAW_IMG" of="$RDISK" bs=4m
sync

echo "3. Syncing and re-reading the partition table..."
sync
diskutil list "$DISK" || true
diskutil mount GTA8CFG >/dev/null 2>&1 || true

echo "4. Done."
echo ""
echo "The GTA8CFG volume should appear shortly. To enable Wi-Fi at boot:"
echo "  cp tools/gta8boot/wpa_supplicant.conf.example /Volumes/GTA8CFG/wpa_supplicant.conf"
echo "  edit ssid/psk, then: diskutil eject /dev/$DISK"
echo ""
echo "Then flash the AP tar with Odin and boot the tablet."

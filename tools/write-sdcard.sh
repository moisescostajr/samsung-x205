#!/bin/bash
# Automatically write Debian 12 arm64 image and deploy Sm-x205 tools to a microSD card on macOS.
#
# Usage:
#   sudo ./tools/write-sdcard.sh /dev/diskX
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root / with sudo:"
    echo "  sudo ./tools/write-sdcard.sh /dev/diskX"
    exit 1
fi

if [ -z "$1" ]; then
    echo "Error: target disk not specified."
    echo ""
    echo "Available external disks:"
    diskutil list external
    echo ""
    echo "Usage: sudo $0 /dev/diskX  (replace X with your SD card number, e.g. /dev/disk4)"
    exit 1
fi

TARGET="$1"
# Strip partition number if passed (e.g. /dev/disk4s1 -> /dev/disk4)
DISK=$(echo "$TARGET" | sed -E 's/(disk[0-9]+).*/\1/')
RDISK="/dev/r${DISK##*/}"

RAW_IMG="rootfs/disk.raw"
if [ ! -f "$RAW_IMG" ]; then
    if [ -f "rootfs/debian-12-nocloud-arm64.tar.xz" ]; then
        echo "Extracting $RAW_IMG from archive..."
        tar -xf rootfs/debian-12-nocloud-arm64.tar.xz -C rootfs/
    else
        echo "Error: neither $RAW_IMG nor rootfs/debian-12-nocloud-arm64.tar.xz found."
        exit 1
    fi
fi

echo "=========================================================="
echo " Target Disk: $DISK ($RDISK)"
echo " Image File:  $RAW_IMG ($(du -h "$RAW_IMG" | cut -f1))"
echo "=========================================================="
echo "WARNING: ALL DATA ON $DISK WILL BE ERASED!"
echo ""
read -p "Type YES to proceed: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "Aborted by user."
    exit 1
fi

echo "1. Unmounting $DISK..."
diskutil unmountDisk "$DISK" || true

echo "2. Writing image to $RDISK (this may take 1-2 minutes)..."
dd if="$RAW_IMG" of="$RDISK" bs=4m status=progress

echo "3. Syncing disks..."
sync

echo "4. Probing partitions..."
diskutil list "$DISK"

echo "5. MicroSD card base system written successfully!"
echo "   If mounted, run: ./tools/deploy-to-sdcard.sh /Volumes/<VolumeName>"

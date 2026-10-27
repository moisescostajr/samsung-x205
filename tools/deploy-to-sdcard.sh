#!/bin/bash
# Deploy Sm-x205 userspace scripts and configs to a mounted Debian microSD card.
#
# Usage:
#   ./tools/deploy-to-sdcard.sh /path/to/mounted/sdcard
set -e

if [ -z "$1" ] || [ ! -d "$1" ]; then
    echo "Usage: $0 /path/to/mounted/sdcard"
    echo "Example (macOS): $0 /Volumes/DebianRoot"
    echo "Example (Linux): $0 /media/$USER/rootfs"
    exit 1
fi

DEST="$1"
echo "Deploying Sm-x205 userspace to: $DEST"

# Ensure target directories exist
mkdir -p "$DEST/root" "$DEST/etc/udev/rules.d" "$DEST/etc/dpkg/dpkg.cfg.d"

# 1. Protect /sbin/init from being overwritten by apt systemd updates
echo 'path-exclude=/sbin/init' > "$DEST/etc/dpkg/dpkg.cfg.d/protect-sbin-init"

# 2. Copy udev rules
if [ -d "tools/udev" ]; then
    echo "Installing udev rules..."
    cp -v tools/udev/*.rules "$DEST/etc/udev/rules.d/"
fi

# 3. Copy scripts and tools to /root
echo "Copying scripts to /root..."
cp -rv tools/* "$DEST/root/"

# Ensure execution permissions on scripts
chmod +x "$DEST/root"/*.sh "$DEST/root"/*.py "$DEST/root"/dash-open 2>/dev/null || true

echo ""
echo "[OK] Deployment complete! The microSD card now has all required tools in /root."

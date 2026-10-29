#!/bin/bash
# Build a bootable-for-the-initramfs Debian 12 arm64 rootfs image for the
# Samsung Galaxy Tab A8 LTE (SM-X205).
#
# The tablet's boot.img carries the kernel and our initramfs. This script only
# produces the microSD card image:
#
#   p1  ext4  LABEL=gta8root   Debian + Phosh
#   p2  vfat  LABEL=GTA8CFG    64 MiB provisioning area (Wi-Fi credentials)
#
# It must run as root on a Linux host with binfmt_misc for arm64 (GitHub
# Actions ubuntu-22.04 does this for us). It is not meant to run on macOS.
#
# Usage:
#   sudo ./tools/build-rootfs.sh
#
# Environment:
#   GTA8_IMAGE_SIZE    image size, default 6G (accepts 6G/6144M/bytes)
#   GTA8_BOOT_PACK     boot-pack directory, default ./boot-pack
#   GTA8_OUT_DIR       output directory, default ./rootfs
#   GTA8_ROOTFS_SUITE  Debian suite, default bookworm
#   GTA8_KEEP_WORK     keep the chroot/stage after building (debug)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${GTA8_OUT_DIR:-$REPO/rootfs}"
BOOT_PACK="${GTA8_BOOT_PACK:-$REPO/boot-pack}"
SUITE="${GTA8_ROOTFS_SUITE:-bookworm}"
ARCH=arm64
IMAGE_SIZE="${GTA8_IMAGE_SIZE:-6G}"
MIRROR="${GTA8_MIRROR:-http://deb.debian.org/debian}"

WORK="${GTA8_WORK:-$OUT/build}"
ROOTDIR="$WORK/root"
STAGE="$WORK/stage"
DISK="$OUT/disk.raw"
RELEASE="$OUT/release"
FAT_LABEL=GTA8CFG
FAT_BYTES=$((64 * 1024 * 1024))
TAIL_BYTES=$((1024 * 1024))

log()  { echo "gta8-rootfs: $*"; }
die()  { echo "gta8-rootfs: ERROR: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo $0)"
[ -x /usr/sbin/chroot ] || die "chroot not found"
command -v mmdebstrap >/dev/null || die "mmdebstrap not installed"
command -v mkfs.ext4 >/dev/null || die "e2fsprogs not installed"
command -v mkfs.vfat >/dev/null || die "dosfstools not installed"
command -v parted >/dev/null || die "parted not installed"
command -v losetup >/dev/null || die "losetup not available"
[ -f "$REPO/tools/rootfs-configure.sh" ] || die "missing tools/rootfs-configure.sh"

# Make sure the foreign-architecture handler is active. On CI the package
# postinst normally registers it; this is just belt and braces.
if [ "$(uname -m)" != aarch64 ] && [ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
    update-binfmts --enable qemu-aarch64 2>/dev/null || \
        die "arm64 binfmt handler missing (install qemu-user-static binfmt-support)"
fi

to_bytes() {
    case "$1" in
        *[Gg][Ii][Bb]|*[Gg][Bb]) echo $(( ${1%[Gg]*} * 1024 * 1024 * 1024 )) ;;
        *[Mm][Ii][Bb]|*[Mm][Bb]) echo $(( ${1%[Mm]*} * 1024 * 1024 )) ;;
        *[Kk][Ii][Bb]|*[Kk][Bb]) echo $(( ${1%[Kk]*} * 1024 )) ;;
        *[Gg]) echo $(( ${1%[Gg]} * 1024 * 1024 * 1024 )) ;;
        *[Mm]) echo $(( ${1%[Mm]} * 1024 * 1024 )) ;;
        *[Kk]) echo $(( ${1%[Kk]} * 1024 )) ;;
        *[0-9]) echo "$1" ;;
        *) die "cannot parse size: $1" ;;
    esac
}
SIZE_BYTES="$(to_bytes "$IMAGE_SIZE")"
[ "$SIZE_BYTES" -ge $((4 * 1024 * 1024 * 1024)) ] || \
    die "image must be at least 4G (got $IMAGE_SIZE)"

# ------------------------------------------------------------------ packages
# Keep this list explicit. phosh only Recommends the GNOME session pieces, so
# relying on recommends would make the image fragile across mirror updates.
PACKAGES="
systemd systemd-sysv systemd-timesyncd udev
dbus dbus-user-session
libpam-systemd polkitd pkexec
network-manager modemmanager wpasupplicant iw rfkill
mobile-broadband-provider-info libqmi-utils
phosh phoc squeekboard phosh-mobile-tweaks phosh-plugins
gnome-session-bin gnome-session-common gnome-settings-daemon
feedbackd iio-sensor-proxy
xwayland xdg-user-dirs xdg-utils
gnome-terminal epiphany-browser
gnome-keyring libpam-gnome-keyring
gvfs gvfs-backends udisks2 upower
adwaita-icon-theme hicolor-icon-theme shared-mime-info desktop-file-utils
fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji fonts-lato
libgl1-mesa-dri libegl-mesa0 libgles2 libgbm1 mesa-utils
alsa-utils alsa-ucm-conf pulseaudio pulseaudio-utils
gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav
mpv ffmpeg
zram-tools
login kbd sudo locales ca-certificates openssh-server
python3 python3-gi python3-dbus
busybox-static kmod iproute2 iputils-ping procps psmisc
e2fsprogs dosfstools fdisk parted
vim-tiny nano less htop curl wget rsync
strace lsof usbutils pciutils evtest i2c-tools libinput-tools
"

export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C

log "preparing $WORK"
rm -rf "$WORK"
mkdir -p "$WORK" "$OUT" "$RELEASE"

# mmdebstrap wants a comma-separated list, not the readable multi-line one.
PACKAGE_LIST="$(echo $PACKAGES | tr ' ' ',')"

# ------------------------------------------------------------------ bootstrap
log "bootstrapping Debian $SUITE/$ARCH (this takes a while)"
mmdebstrap \
    --arch="$ARCH" \
    --variant=apt \
    --components=main \
    --aptopt='Acquire::Retries "5"' \
    --aptopt='Acquire::http::Timeout "60"' \
    --aptopt='Apt::Install-Recommends "true"' \
    --include="$PACKAGE_LIST" \
    "$SUITE" "$ROOTDIR" "$MIRROR"

# ---------------------------------------------------------------------- stage
log "staging tools, modules and vendor helpers"
mkdir -p "$STAGE/tools" "$STAGE/modules" "$STAGE/kmsbin"
cp -a "$REPO/tools/." "$STAGE/tools/"
rm -rf "$STAGE/tools/__pycache__"
find "$STAGE/tools" -name '*.pyc' -delete 2>/dev/null || true

# Kernel modules built by the CI kernel job. sprdwl_ng.ko is optional: the
# stock copy on the socko partition is used when no patched build is present.
shopt -s nullglob
for f in "$BOOT_PACK"/modules/*.ko "$REPO"/tools/*.ko \
         "$REPO"/stock/sprdwl_ng_patched.ko "$REPO"/stock/sprdwl_ng.ko; do
    if [ -f "$f" ]; then
        cp -f "$f" "$STAGE/modules/"
        cp -f "$f" "$STAGE/kmsbin/"
    fi
done
# Vendor helper binaries are precompiled in CI so the image needs no gcc.
for f in "$BOOT_PACK"/propstub.so "$BOOT_PACK"/extract.so \
         "$BOOT_PACK"/drmstep-fb2 "$BOOT_PACK"/splash.bgra \
         "$BOOT_PACK"/opt/kmsbin/* \
         "$REPO"/tools/drmstep-fb2 "$REPO"/tools/splash.bgra; do
    [ -f "$f" ] && cp -f "$f" "$STAGE/kmsbin/"
done
shopt -u nullglob

# ---------------------------------------------------------------- chroot setup
log "configuring the rootfs (users, services, Phosh, Wi-Fi profile)"
cp -a "$STAGE" "$ROOTDIR/tmp/gta8-stage"
cp -f "$REPO/tools/rootfs-configure.sh" "$ROOTDIR/tmp/rootfs-configure.sh"
chmod +x "$ROOTDIR/tmp/rootfs-configure.sh"

mkdir -p "$ROOTDIR/proc" "$ROOTDIR/sys" "$ROOTDIR/dev" "$ROOTDIR/dev/pts"
cleanup_chroot() {
    mountpoint -q "$ROOTDIR/dev/pts" && umount -l "$ROOTDIR/dev/pts" 2>/dev/null || true
    mountpoint -q "$ROOTDIR/dev" && umount -l "$ROOTDIR/dev" 2>/dev/null || true
    mountpoint -q "$ROOTDIR/proc" && umount -l "$ROOTDIR/proc" 2>/dev/null || true
    mountpoint -q "$ROOTDIR/sys" && umount -l "$ROOTDIR/sys" 2>/dev/null || true
}
trap cleanup_chroot EXIT
mount --bind /dev "$ROOTDIR/dev"
mount --bind /dev/pts "$ROOTDIR/dev/pts" 2>/dev/null || true
mount -t proc proc "$ROOTDIR/proc"
mount -t sysfs sysfs "$ROOTDIR/sys"

chroot "$ROOTDIR" /usr/bin/env \
    STAGE=/tmp/gta8-stage \
    GTA8_USER=gta8 \
    DEBIAN_FRONTEND=noninteractive \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    /bin/bash /tmp/rootfs-configure.sh

rm -rf "$ROOTDIR/tmp/gta8-stage" "$ROOTDIR/tmp/rootfs-configure.sh"
cleanup_chroot
trap - EXIT

log "rootfs size: $(du -sh "$ROOTDIR" | cut -f1)"

# -------------------------------------------------------------------- image
log "creating GPT image ($IMAGE_SIZE) at $DISK"
rm -f "$DISK"
truncate -s "$SIZE_BYTES" "$DISK"

TOTAL="$(stat -c%s "$DISK")"
P2_START=$((TOTAL - TAIL_BYTES - FAT_BYTES))
P1_END=$((P2_START - 1024 * 1024))
P2_END=$((TOTAL - TAIL_BYTES))
[ "$P1_END" -gt $((2 * 1024 * 1024 * 1024)) ] || die "image too small for a rootfs plus 64M config partition"
ROOT_BYTES="$(du -sB1 "$ROOTDIR" | cut -f1)"
ROOT_AVAIL=$((P1_END - 1048576))
log "rootfs uses $((ROOT_BYTES / 1048576)) MiB of $((ROOT_AVAIL / 1048576)) MiB"
[ "$ROOT_BYTES" -lt "$ROOT_AVAIL" ] || \
    die "rootfs does not fit in $IMAGE_SIZE (raise GTA8_IMAGE_SIZE)"

parted -s "$DISK" mklabel gpt
parted -s "$DISK" unit B mkpart gta8root ext4 1048576 "$P1_END"
parted -s "$DISK" unit B mkpart "$FAT_LABEL" fat32 "$P2_START" "$P2_END"
parted -s "$DISK" unit B print

LOOP="$(losetup --find --show --partscan "$DISK")"
cleanup_loop() {
    [ -n "${MNT:-}" ] && mountpoint -q "$MNT" && umount "$MNT" 2>/dev/null || true
    [ -n "${LOOP:-}" ] && losetup -d "$LOOP" 2>/dev/null || true
}
trap cleanup_loop EXIT

for _ in $(seq 1 20); do
    [ -b "${LOOP}p1" ] && [ -b "${LOOP}p2" ] && break
    partx -u "$LOOP" 2>/dev/null || true
    udevadm settle --timeout=2 2>/dev/null || true
    sleep 1
done
[ -b "${LOOP}p1" ] || die "kernel did not expose ${LOOP}p1"
[ -b "${LOOP}p2" ] || die "kernel did not expose ${LOOP}p2"

# ext4 features must stay readable by the vendor 4.14 kernel. Newer e2fsprogs
# enable orphan_file and metadata_csum_seed by default; 4.14 knows neither.
FEATURES="^metadata_csum_seed"
if mke2fs -O help 2>&1 | grep -qw orphan_file; then
    FEATURES="$FEATURES,^orphan_file"
fi
log "mkfs.ext4 features: -O $FEATURES"
mkfs.ext4 -F -q -L gta8root -m 0 -O "$FEATURES" -d "$ROOTDIR" "${LOOP}p1"

log "validating ext4 rootfs"
e2fsck -fn "${LOOP}p1" || {
    rc=$?
    [ "$rc" -le 1 ] || die "e2fsck failed with status $rc"
}

log "creating $FAT_LABEL provisioning partition"
mkfs.vfat -F 32 -n "$FAT_LABEL" "${LOOP}p2" >/dev/null
MNT="$WORK/mnt-fat"
mkdir -p "$MNT"
mount -t vfat "${LOOP}p2" "$MNT"
cp -f "$REPO/tools/gta8boot/README.txt" "$MNT/README.TXT"
cp -f "$REPO/tools/gta8boot/wpa_supplicant.conf.example" "$MNT/wpa_supplicant.conf.example"
sync
umount "$MNT"
MNT=""

losetup -d "$LOOP"
LOOP=""
trap - EXIT
sync

# The chroot is no longer needed and can be several GiB. Drop it before xz and
# split so the runner does not need room for the tree, the raw image and the
# compressed copy at the same time.
[ "${GTA8_KEEP_WORK:-0}" = 1 ] || rm -rf "$WORK"

# --------------------------------------------------------------- release bits
log "compressing image (xz)"
XZ="$RELEASE/gta8-rootfs.img.xz"
rm -f "$XZ" "$RELEASE"/gta8-rootfs.img.xz.part.*
xz -T0 -6 -c "$DISK" > "$XZ"

log "splitting for GitHub release assets (1.8 GiB parts)"
split -b 1800M -d -a 2 "$XZ" "$RELEASE/gta8-rootfs.img.xz.part."
( cd "$RELEASE" && sha256sum gta8-rootfs.img.xz.part.* > SHA256SUMS )

{
    echo "image: gta8-rootfs.img.xz"
    echo "size_bytes: $TOTAL"
    echo "sha256_xz: $(sha256sum "$XZ" | cut -d' ' -f1)"
    echo "part_count: $(ls "$RELEASE"/gta8-rootfs.img.xz.part.* | wc -l | tr -d ' ')"
    echo "suite: $SUITE"
    echo "built_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "git_commit: ${GITHUB_SHA:-$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)}"
} > "$RELEASE/manifest.txt"

# The split parts are the release payload; the monolith is not needed.
rm -f "$XZ"

log "release assets:"
ls -lh "$RELEASE"
log "done; write $OUT/disk.raw to the microSD with tools/write-sdcard.sh"

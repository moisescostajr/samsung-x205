#!/usr/bin/env python3
"""Pack boot-only v42: v32 switch_root + debian-init runs /root/hw-up.sh."""
from pathlib import Path
import gzip, hashlib, os, struct, tarfile, tempfile

BOOT_PACK = Path(os.environ.get("GTA8_BOOT_PACK", Path(__file__).resolve().parents[1] / "boot-pack"))

src_path = BOOT_PACK / "boot-gta8wifi-debug-v32.img"
out_img = BOOT_PACK / "boot-gta8wifi-debug-v42.img"
out_tar = BOOT_PACK / "AP-boot-only-debug-v42.tar"

INIT = r"""#!/bin/busybox sh
# v36: ACM first, recv debian tar over ttyGS0, ext4 SD, switch_root.
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
BUSYBOX=/bin/busybox
trap '' HUP INT QUIT TSTP TTIN TTOU

log() {
    echo "gta8-init: $*"
    echo "gta8-init: $*" > /dev/kmsg 2>/dev/null || true
}

$BUSYBOX mkdir -p /proc /sys /dev /tmp /run /mnt /config
$BUSYBOX mount -t proc proc /proc
$BUSYBOX mount -t sysfs sysfs /sys
$BUSYBOX mount -t tmpfs tmpfs /dev
$BUSYBOX mkdir -p /dev/pts /dev/shm
$BUSYBOX mount -t devpts devpts /dev/pts 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/null c 1 3 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/zero c 1 5 2>/dev/null || true
$BUSYBOX mknod -m 600 /dev/kmsg c 1 11 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/tty c 5 0 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/ptmx c 5 2 2>/dev/null || true
$BUSYBOX sh -c 'trap "" HUP INT QUIT; while true; do echo V > /dev/watchdog; sleep 8; done' </dev/null >/dev/null 2>&1 &

log "v36 waiting 12s for UDC"
$BUSYBOX sleep 12
echo disable > /sys/devices/platform/soc/soc:aon/5fff0000.usb/musb_hostenable 2>/dev/null || true
echo peripheral > /sys/devices/platform/soc/soc:aon/5fff0000.usb/musb-hdrc.0.auto/mode 2>/dev/null || true
echo on > /sys/devices/platform/soc/soc:aon/5fff0000.usb/power/control 2>/dev/null || true
echo 1 > /sys/class/usb_notify/usb_control/usb_data_enabled 2>/dev/null || true
echo 1 > /sys/class/usb_notify/usb_notify/usb_data_enabled 2>/dev/null || true
echo OFF > /sys/class/usb_notify/usb_notify/disable 2>/dev/null || true
echo OFF > /sys/devices/virtual/usb_notify/usb_notify/disable 2>/dev/null || true
for f in /sys/class/usb_notify/*/usb_data_enabled /sys/class/usb_notify/*/disable; do
    [ -e "$f" ] || continue
    case "$f" in
        *disable) echo OFF > "$f" 2>/dev/null || true ;;
        *) echo 1 > "$f" 2>/dev/null || true ;;
    esac
done
$BUSYBOX mount -t configfs none /config 2>/dev/null || true
$BUSYBOX mount -t configfs configfs /sys/kernel/config 2>/dev/null || true
i=0
while [ $i -lt 20 ]; do
    [ -e /sys/class/udc/musb-hdrc.0.auto ] && break
    $BUSYBOX sleep 1
    i=$((i+1))
done
G=/config/usb_gadget/g1
[ -d /config/usb_gadget ] || G=/sys/kernel/config/usb_gadget/g1
$BUSYBOX mkdir -p "$G/strings/0x409" "$G/functions/acm.gs0" "$G/configs/b.1/strings/0x409"
echo 0x1d6b > "$G/idVendor"
echo 0x0104 > "$G/idProduct"
echo 0x0200 > "$G/bcdUSB"
echo 239 > "$G/bDeviceClass" 2>/dev/null || true
echo 0x02 > "$G/bDeviceSubClass" 2>/dev/null || true
echo 0x01 > "$G/bDeviceProtocol" 2>/dev/null || true
echo 0123456789abcdef > "$G/strings/0x409/serialnumber"
echo Droidian > "$G/strings/0x409/manufacturer"
echo gta8wifi-debug > "$G/strings/0x409/product"
echo ACM > "$G/configs/b.1/strings/0x409/configuration"
echo 0x80 > "$G/configs/b.1/bmAttributes" 2>/dev/null || true
echo 500 > "$G/configs/b.1/MaxPower" 2>/dev/null || true
$BUSYBOX ln -sfn "$G/functions/acm.gs0" "$G/configs/b.1/f1"
maj=509; min=0
if [ -e /sys/class/tty/ttyGS0/dev ]; then
    dev=$($BUSYBOX cat /sys/class/tty/ttyGS0/dev)
    maj=${dev%:*}
    min=${dev#*:}
fi
$BUSYBOX mknod -m 600 /dev/ttyGS0 c "$maj" "$min" 2>/dev/null || true
exec 9<>/dev/ttyGS0 || true
UDC=musb-hdrc.0.auto
n=0
while [ $n -lt 15 ]; do
    echo none > "$G/UDC" 2>/dev/null || echo "" > "$G/UDC" 2>/dev/null || true
    $BUSYBOX sleep 1
    echo "$UDC" > "$G/UDC" 2>/dev/null && break
    echo disable > /sys/devices/platform/soc/soc:aon/5fff0000.usb/musb_hostenable 2>/dev/null || true
    echo peripheral > /sys/devices/platform/soc/soc:aon/5fff0000.usb/musb-hdrc.0.auto/mode 2>/dev/null || true
    $BUSYBOX sleep 2
    n=$((n+1))
done
echo 322f0000.watchdog > /sys/bus/platform/drivers/sprd-wdt-fiq/unbind 2>/dev/null || true
echo v36 > /gta8-booted
log "v36 ACM bound"

$BUSYBOX mdev -s 2>/dev/null || true
$BUSYBOX mkdir -p /mnt/root
if [ -e /sys/class/block/mmcblk1p1/dev ]; then
    dev=$($BUSYBOX cat /sys/class/block/mmcblk1p1/dev)
    $BUSYBOX mknod -m 660 /dev/mmcblk1p1 b "${dev%:*}" "${dev#*:}" 2>/dev/null || true
fi

do_switch() {
    $BUSYBOX cp /debian-init /mnt/root/sbin/init
    $BUSYBOX chmod 755 /mnt/root/sbin/init
    $BUSYBOX mkdir -p /mnt/root/proc /mnt/root/sys /mnt/root/dev /mnt/root/dev/pts /mnt/root/run /mnt/root/config
    $BUSYBOX mount -o bind /proc /mnt/root/proc 2>/dev/null || true
    $BUSYBOX mount -o bind /sys /mnt/root/sys 2>/dev/null || true
    $BUSYBOX mount -o bind /dev /mnt/root/dev 2>/dev/null || true
    $BUSYBOX mount -o bind /config /mnt/root/config 2>/dev/null || true
    log "switch_root debian"
    exec $BUSYBOX switch_root /mnt/root /sbin/init
}

if $BUSYBOX mount -t ext4 /dev/mmcblk1p1 /mnt/root 2>/dev/null || $BUSYBOX mount /dev/mmcblk1p1 /mnt/root; then
    if [ -x /mnt/root/bin/busybox ] || [ -d /mnt/root/etc ]; then
        do_switch
    fi
    $BUSYBOX umount /mnt/root 2>/dev/null || true
    log "sd not debian, will recv tar"
fi

$BUSYBOX mount -t tmpfs -o size=256m tmpfs /tmp
$BUSYBOX stty raw -echo < /dev/ttyGS0 2>/dev/null || true
echo GTA8RECV > /dev/ttyGS0
log "GTA8RECV"
HDR=$($BUSYBOX dd if=/dev/ttyGS0 bs=16 count=1 2>/dev/null)
SIZE=$(echo "$HDR" | $BUSYBOX sed 's/[^0-9]//g')
log "size $SIZE"
if [ -n "$SIZE" ] && [ "$SIZE" -gt 1000000 ]; then
    BLOCKS=$(( (SIZE + 4095) / 4096 ))
    $BUSYBOX dd if=/dev/ttyGS0 of=/tmp/debian.tar.gz bs=4096 count=$BLOCKS
    $BUSYBOX umount /mnt/root 2>/dev/null || true
    $BUSYBOX mke2fs -F /dev/mmcblk1p1 || $BUSYBOX mke2fs /dev/mmcblk1p1
    $BUSYBOX mount -t ext4 /dev/mmcblk1p1 /mnt/root || $BUSYBOX mount /dev/mmcblk1p1 /mnt/root
    if $BUSYBOX tar -xzf /tmp/debian.tar.gz -C /mnt/root; then
        do_switch
    fi
    log "tar unpack failed"
fi

log "ramdisk shell"
$BUSYBOX setsid sh -c 'trap "" HUP INT QUIT TSTP TTIN TTOU
while true; do
    echo "gta8wifi ramdisk v36" > /dev/ttyGS0
    $BUSYBOX sh <>/dev/ttyGS0 >&0 2>&0
    $BUSYBOX sleep 1
done' </dev/null >/dev/null 2>&1 &
while true; do
    echo V > /dev/watchdog 2>/dev/null || true
    $BUSYBOX sleep 8
done
"""

DEBIAN_INIT = r"""#!/bin/busybox sh
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/wifi:/opt/kmsbin
export HOME=/root
trap '' HUP INT QUIT TSTP TTIN TTOU
busybox mkdir -p /dev/pts /run /tmp
[ -e /dev/ttyGS0 ] || busybox mknod -m 600 /dev/ttyGS0 c 509 0
[ -e /dev/watchdog ] || busybox mknod -m 666 /dev/watchdog c 10 130
[ -e /dev/null ] || busybox mknod -m 666 /dev/null c 1 3
busybox mount -t devpts devpts /dev/pts 2>/dev/null
busybox sh -c 'trap "" HUP; while true; do echo V > /dev/watchdog; sleep 8; done' </dev/null >/dev/null 2>&1 &
busybox hostname gta8wifi
cd /root
if [ -x /root/hw-up.sh ]; then
    busybox sh /root/hw-up.sh </dev/null >/tmp/hw-up.log 2>&1 &
fi
busybox setsid sh -c 'trap "" HUP INT QUIT TSTP TTIN TTOU
while true; do
    echo "gta8wifi debian v42" > /dev/ttyGS0
    busybox sh <>/dev/ttyGS0 >&0 2>&0
    busybox sleep 1
done' </dev/null >/dev/null 2>&1 &
while true; do
    echo V > /dev/watchdog 2>/dev/null || true
    busybox sleep 8
done
"""


def parse_cpio(data):
    off = 0
    entries = []
    while off + 110 <= len(data):
        hdr = data[off : off + 110]
        if not hdr.startswith(b"070701"):
            raise SystemExit(f"bad cpio magic at {off}")
        namesize = int(hdr[94:102], 16)
        filesize = int(hdr[54:62], 16)
        name = data[off + 110 : off + 110 + namesize - 1].decode("utf-8", "replace")
        data_off = (off + 110 + namesize + 3) // 4 * 4
        payload = data[data_off : data_off + filesize]
        next_off = (data_off + filesize + 3) // 4 * 4
        entries.append((hdr, name, payload))
        if name == "TRAILER!!!":
            break
        off = next_off
    return entries


def emit_cpio(entries):
    out = bytearray()
    for hdr, name, payload in entries:
        name_b = name.encode("utf-8") + b"\x00"
        hdr = bytearray(hdr)
        hdr[54:62] = f"{len(payload):08X}".encode()
        hdr[94:102] = f"{len(name_b):08X}".encode()
        out.extend(hdr)
        out.extend(name_b)
        while len(out) % 4:
            out.append(0)
        out.extend(payload)
        while len(out) % 4:
            out.append(0)
    return bytes(out)


def pad(n, page=2048):
    return (n + page - 1) // page * page


def main():
    src = src_path.read_bytes()
    ksz = struct.unpack_from("<I", src, 8)[0]
    old_rsz = struct.unpack_from("<I", src, 16)[0]
    ssz = struct.unpack_from("<I", src, 24)[0]
    rec_dtbo_size = struct.unpack_from("<I", src, 1632)[0]
    dtb_size = struct.unpack_from("<I", src, 1644)[0]
    r_off = 2048 + pad(ksz)
    d_off = r_off + pad(old_rsz) + pad(ssz) + pad(rec_dtbo_size)
    kernel = src[2048 : 2048 + ksz]
    dtb = src[d_off : d_off + dtb_size]
    cpio = gzip.decompress(src[r_off : r_off + old_rsz])
    entries = parse_cpio(cpio)
    got_deb = False
    for i, (hdr, name, payload) in enumerate(entries):
        if name == "debian-init":
            entries[i] = (hdr, name, DEBIAN_INIT.encode())
            got_deb = True
            print("debian-init", len(payload), "->", len(DEBIAN_INIT.encode()))
    assert got_deb
    new_cpio = emit_cpio(entries)
    gz = gzip.compress(new_cpio, compresslevel=9)
    print("gz", len(gz), "slot", pad(old_rsz))
    assert len(gz) <= pad(old_rsz), f"ramdisk {len(gz)} > {pad(old_rsz)}"
    out = bytearray(src)
    out[16:20] = struct.pack("<I", len(gz))
    out[r_off : r_off + pad(old_rsz)] = b"\x00" * pad(old_rsz)
    out[r_off : r_off + len(gz)] = gz
    second = src[r_off + pad(old_rsz) : r_off + pad(old_rsz) + ssz] if ssz else b""
    h = hashlib.sha1()
    h.update(kernel)
    h.update(gz)
    h.update(second)
    h.update(dtb)
    out[1648 : 1648 + 32] = h.digest() + b"\x00" * 12
    assert bytes(out)[0x1600000:0x1600004] == b"AVB0"
    assert bytes(out).rfind(b"AVBf") == 67108800
    rd = gzip.decompress(bytes(out[r_off : r_off + len(gz)]))
    assert b"switch_root" in rd and b"debian v42" in rd and b"/root/hw-up.sh" in rd
    out_img.write_bytes(bytes(out))
    os.environ["COPYFILE_DISABLE"] = "1"
    td = tempfile.mkdtemp()
    boot = Path(td) / "boot.img"
    boot.write_bytes(bytes(out))
    with tarfile.open(out_tar, "w") as tf:
        tf.add(boot, arcname="boot.img")
    os.system(f'xattr -c "{out_tar}" 2>/dev/null')
    print("wrote", out_tar, out_tar.stat().st_size)


if __name__ == "__main__":
    main()

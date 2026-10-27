#!/usr/bin/env python3
"""Pack boot-only v56: dim still panel, wget new drmstep-fb2 + pmicwdt_off.ko."""
from pathlib import Path
import gzip, hashlib, os, struct, tarfile, tempfile

BOOT_PACK = Path(os.environ.get("GTA8_BOOT_PACK", Path(__file__).resolve().parents[1] / "boot-pack"))

src_path = BOOT_PACK / "boot-gta8wifi-debug-v32.img"
out_img = BOOT_PACK / "boot-gta8wifi-debug-v56.img"
out_tar = BOOT_PACK / "AP-boot-only-debug-v56.tar"

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
# Do NOT unbind sprd-wdt-fiq. The bootloader arms the hardware timer, so
# unbinding removes the only thing feeding it and the tablet resets ~265s in.
# There is no devtmpfs here, so the node has to be made by hand.
for w in /sys/class/watchdog/watchdog*; do
    [ -e "$w/dev" ] || continue
    wdev=$($BUSYBOX cat "$w/dev")
    wname=${w##*/}
    $BUSYBOX mknod -m 600 "/dev/$wname" c "${wdev%:*}" "${wdev#*:}" 2>/dev/null || true
    log "wdt /dev/$wname $wdev timeout=$($BUSYBOX cat "$w/timeout" 2>/dev/null)"
done
$BUSYBOX sh -c 'trap "" HUP INT QUIT
while true; do
    for n in /dev/watchdog /dev/watchdog0 /dev/watchdog1; do
        [ -c "$n" ] && echo 1 > "$n" 2>/dev/null
    done
    sleep 5
done' </dev/null >/dev/null 2>&1 &
echo v53 > /gta8-booted
log "v53 ACM bound, watchdog kept alive"

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
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/kmsbin
export HOME=/root
trap '' HUP INT QUIT TSTP TTIN TTOU
busybox mount -o remount,rw /
busybox mkdir -p /dev/pts /run /tmp /dev/dri
[ -e /dev/ttyGS0 ] || busybox mknod -m 600 /dev/ttyGS0 c 509 0
[ -e /dev/watchdog ] || busybox mknod -m 666 /dev/watchdog c 10 130
[ -e /dev/null ] || busybox mknod -m 666 /dev/null c 1 3
busybox mount -t devpts devpts /dev/pts 2>/dev/null
busybox mdev -s 2>/dev/null
if [ -e /sys/class/drm/card0/dev ]; then
    d=$(busybox cat /sys/class/drm/card0/dev)
    busybox rm -f /dev/dri/card0
    busybox mknod -m 666 /dev/dri/card0 c ${d%:*} ${d#*:}
fi
echo v56 > /root/v56.ran
busybox timeout -s KILL 1 busybox sh -c 'echo "gta8wifi v56 dim+wdtko" > /dev/ttyGS0' 2>/dev/null || true
busybox hostname gta8wifi
cd /root

busybox mkdir -p /sys/fs/pstore
busybox mount -t pstore pstore /sys/fs/pstore 2>/dev/null
: > /root/lastboot.log
for f in /proc/last_kmsg /sys/fs/pstore/console-ramoops-0 /sys/fs/pstore/console-ramoops /sys/fs/pstore/dmesg-ramoops-0; do
    if [ -f "$f" ]; then
        echo "=== $f ===" >> /root/lastboot.log
        busybox tail -c 4000 "$f" >> /root/lastboot.log 2>/dev/null
    fi
done
busybox sync

/opt/kmsbin/wdinfo >/root/wdinfo.log 2>&1 &

# Leave the UDC free so Type-C CC / musb dual-role can become host (gamepad)
# or device (PC). /root/usb-role.sh gadget restores ACM+RNDIS.
G=/config/usb_gadget/g1
[ -d "$G" ] || G=/sys/kernel/config/usb_gadget/g1
if [ -d "$G" ]; then
    echo "" > "$G/UDC" 2>/dev/null
    echo usb_udc_unbound >> /root/hw-up.log
fi
USB=/sys/devices/platform/soc/soc:aon/5fff0000.usb
echo on > "$USB/power/control" 2>/dev/null || true
echo enable > "$USB/musb_hostenable" 2>/dev/null || true
if [ -e "$USB/musb-hdrc.0.auto/mode" ]; then
    echo otg > "$USB/musb-hdrc.0.auto/mode" 2>/dev/null \
        || echo host > "$USB/musb-hdrc.0.auto/mode" 2>/dev/null || true
fi
echo usb_role_auto >> /root/hw-up.log
busybox httpd -p 8080 -h /root 2>/dev/null && echo httpd_ok >> /root/boot.log || echo httpd_fail >> /root/boot.log
busybox sh -c 'while true; do busybox nc -ll -p 2323 -e /bin/sh; busybox sleep 1; done' </dev/null >/dev/null 2>&1 &
echo "shell_server 10.99.0.2:2323" >> /root/boot.log

# Pull dim drmstep + PMIC-wdt killer from the Pi (ramdisk gzip has no room).
n=0
while [ $n -lt 10 ]; do
    busybox wget -q -T 2 -O /tmp/drmstep-fb2 http://10.99.0.1:8081/drmstep-fb2 && break
    n=$((n + 1))
    busybox sleep 1
done
[ -s /tmp/drmstep-fb2 ] && busybox chmod 755 /tmp/drmstep-fb2 && echo wget_drm_ok >> /root/boot.log || echo wget_drm_fail >> /root/boot.log
n=0
while [ $n -lt 8 ]; do
    if busybox wget -q -T 2 -O /tmp/pmicwdt_off.ko http://10.99.0.1:8081/pmicwdt_off.ko; then
        echo wget_ko_ok >> /root/boot.log
        insmod /tmp/pmicwdt_off.ko >> /root/boot.log 2>&1
        echo insmod_ko_done >> /root/boot.log
        break
    fi
    n=$((n + 1))
    busybox sleep 1
done
echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
busybox dmesg | busybox grep -i -e pmicwdt -e "pmic wdt" -e sprd-pmic >> /root/boot.log 2>/dev/null || true

{
    echo "=== cmdline ==="
    busybox cat /proc/cmdline
    echo
    echo "=== version ==="
    busybox cat /proc/version
    echo "=== watchdogs ==="
    busybox ls /sys/class/watchdog 2>/dev/null || echo none
    echo "=== reset reason candidates ==="
    for f in /sys/module/sprd_debuglog/parameters/* /proc/sysdump_info; do
        [ -e "$f" ] && echo "$f: $(busybox cat "$f" 2>/dev/null)"
    done
} >> /root/boot.log 2>&1
busybox sync

(
    while true; do
        echo on > /sys/class/backlight/sprd_backlight/device/power/control 2>/dev/null || true
        echo 0 > /sys/class/backlight/sprd_backlight/bl_power 2>/dev/null || true
        echo 40 > /sys/class/backlight/sprd_backlight/brightness 2>/dev/null || true
        busybox sleep 1
    done
) </dev/null >/dev/null 2>&1 &

if [ -x /tmp/drmstep-fb2 ]; then
    /tmp/drmstep-fb2 >/root/drmstep-fb2.log 2>&1 &
else
    /opt/kmsbin/drmstep-fb2 >/root/drmstep-fb2.log 2>&1 &
fi
/opt/kmsbin/logpipe /root/hw-up.log >/dev/null 2>&1 &

if [ -x /root/hw-up.sh ]; then
    busybox sh /root/hw-up.sh </dev/null >>/root/wifi-stdout.log 2>&1 &
fi

while true; do
    busybox sleep 30
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
    # The base image's own /init still unbinds the watchdog. Patch that line in
    # place rather than replacing the whole script, which is known-good.
    unbind = (
        b"echo 322f0000.watchdog > /sys/bus/platform/drivers/sprd-wdt-fiq/unbind"
        b" 2>/dev/null || true"
    )
    keepalive = b"""for w in /sys/class/watchdog/watchdog*; do
    [ -e "$w/dev" ] || continue
    wdev=$($BUSYBOX cat "$w/dev")
    wname=${w##*/}
    $BUSYBOX mknod -m 600 "/dev/$wname" c "${wdev%:*}" "${wdev#*:}" 2>/dev/null || true
done
$BUSYBOX sh -c 'trap "" HUP INT QUIT
while true; do
    for n in /dev/watchdog /dev/watchdog0 /dev/watchdog1; do
        [ -c "$n" ] && echo 1 > "$n" 2>/dev/null
    done
    sleep 5
done' </dev/null >/dev/null 2>&1 &"""

    got_init = False
    for i, (hdr, name, payload) in enumerate(entries):
        if name == "init" and unbind in payload:
            entries[i] = (hdr, name, payload.replace(unbind, keepalive))
            got_init = True
            print("init: watchdog unbind -> keepalive")
    assert got_init, "watchdog unbind line not found in ramdisk init"

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
    assert b"switch_root" in rd and b"v56 dim+wdtko" in rd and b"nc -ll -p 2323" in rd and b"v56.ran" in rd
    assert b"pmicwdt_off.ko" in rd and b"drmstep-fb2" in rd and b"watchdog rstoff" in rd
    assert b"sprd-wdt-fiq/unbind" not in rd, "watchdog unbind still present"
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

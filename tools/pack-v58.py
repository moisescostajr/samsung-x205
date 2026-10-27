#!/usr/bin/env python3
"""Pack boot-only v58: v57 kernel + ramdisk, USB-C dual-role after switch_root.

v57 still binds ACM+RNDIS onto the musb UDC as PID 1 (debian-init), which
blocks host mode. v58 unbinds that gadget and re-enables musb_hostenable so
Type-C CC can pick a gamepad vs a PC. The ramdisk /init ACM bind is kept for
the first-boot tar-recv path; debian-init tears it down once the SD root is up.

Kernel is unchanged (HID/xpad already built in). Do not flash vbmeta.
"""
from pathlib import Path
import gzip, hashlib, os, struct, tarfile, tempfile

BOOT_PACK = Path(os.environ.get("GTA8_BOOT_PACK", Path(__file__).resolve().parents[1] / "boot-pack"))

base_path = BOOT_PACK / "boot-gta8wifi-debug-v57.img"
out_img = BOOT_PACK / "boot-gta8wifi-debug-v58.img"
out_tar = BOOT_PACK / "AP-boot-only-debug-v58.tar"

PART_SIZE = 64 * 1024 * 1024
FOOTER_OFF = PART_SIZE - 64

OLD_USB = b"""G=/config/usb_gadget/g1
[ -d "$G" ] || G=/sys/kernel/config/usb_gadget/g1
if [ -d "$G" ]; then
    echo "" > "$G/UDC" 2>/dev/null
    busybox sleep 1
    if busybox mkdir -p "$G/functions/rndis.usb0" 2>/dev/null; then
        busybox ln -sfn "$G/functions/rndis.usb0" "$G/configs/b.1/f2" 2>/dev/null
        echo rndis_ok >> /root/hw-up.log
    elif busybox mkdir -p "$G/functions/ecm.usb0" 2>/dev/null; then
        busybox ln -sfn "$G/functions/ecm.usb0" "$G/configs/b.1/f2" 2>/dev/null
        echo ecm_ok >> /root/hw-up.log
    else
        echo no_usbnet >> /root/hw-up.log
    fi
    if ! echo musb-hdrc.0.auto > "$G/UDC" 2>/dev/null; then
        busybox rm -f "$G/configs/b.1/f2"
        echo musb-hdrc.0.auto > "$G/UDC" 2>/dev/null
        echo usbnet_acm_only >> /root/hw-up.log
    fi
    busybox sleep 2
    for i in 1 2 3 4 5 6 7 8 9 10; do
        [ -e /sys/class/net/usb0 ] && break
        busybox sleep 1
    done
    if [ -e /sys/class/net/usb0 ]; then
        ip addr add 10.99.0.2/24 dev usb0 2>/dev/null
        ip link set usb0 up 2>/dev/null
        echo "usb0_up addr=10.99.0.2" >> /root/hw-up.log
    else
        echo usb0_missing >> /root/hw-up.log
    fi
fi
"""

NEW_USB = b"""# Leave the UDC free so Type-C CC / musb dual-role can become host (gamepad)
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
    echo otg > "$USB/musb-hdrc.0.auto/mode" 2>/dev/null || echo host > "$USB/musb-hdrc.0.auto/mode" 2>/dev/null || true
fi
echo usb_role_auto >> /root/hw-up.log
"""


def pad(n, page=2048):
    return (n + page - 1) // page * page


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


def patch_ramdisk(gz: bytes) -> bytes:
    entries = parse_cpio(gzip.decompress(gz))
    got = False
    for i, (hdr, name, payload) in enumerate(entries):
        if name != "debian-init":
            continue
        if OLD_USB not in payload:
            raise SystemExit("debian-init USB gadget block not found (already patched?)")
        entries[i] = (hdr, name, payload.replace(OLD_USB, NEW_USB, 1))
        got = True
        print("debian-init: UDC bind -> dual-role auto")
        break
    if not got:
        raise SystemExit("debian-init missing from ramdisk")
    new = gzip.compress(emit_cpio(entries), compresslevel=6)
    return new


def main():
    if not base_path.is_file():
        raise SystemExit(f"missing {base_path}")

    base = base_path.read_bytes()
    assert len(base) == PART_SIZE, len(base)

    page = struct.unpack_from("<I", base, 36)[0]
    ksz = struct.unpack_from("<I", base, 8)[0]
    old_rsz = struct.unpack_from("<I", base, 16)[0]
    ssz = struct.unpack_from("<I", base, 24)[0]
    assert page == 2048 and ssz == 0

    kernel = base[page : page + ksz]
    old_r_off = page + pad(ksz, page)
    old_rd = base[old_r_off : old_r_off + old_rsz]
    ramdisk = patch_ramdisk(old_rd)

    footer = base[FOOTER_OFF:PART_SIZE]
    assert footer[:4] == b"AVBf"
    orig_size = struct.unpack_from(">Q", footer, 12)[0]
    vb_off = struct.unpack_from(">Q", footer, 20)[0]
    vb_size = struct.unpack_from(">Q", footer, 28)[0]
    vbmeta = base[vb_off : vb_off + vb_size]
    assert vbmeta[:4] == b"AVB0"

    old_dt_off = old_r_off + pad(old_rsz, page)
    dt = base[old_dt_off:orig_size]
    assert dt[:4] == bytes.fromhex("d7b7ab1e"), dt[:4].hex()

    r_off = page + pad(ksz, page)
    dt_off = r_off + pad(len(ramdisk), page)
    content_end = dt_off + len(dt)
    new_vb_off = (content_end + 4095) // 4096 * 4096
    assert new_vb_off + vb_size < FOOTER_OFF

    out = bytearray(PART_SIZE)
    out[0:page] = base[0:page]
    out[page : page + ksz] = kernel
    out[r_off : r_off + len(ramdisk)] = ramdisk
    out[dt_off : dt_off + len(dt)] = dt
    out[new_vb_off : new_vb_off + vb_size] = vbmeta

    struct.pack_into("<I", out, 8, ksz)
    struct.pack_into("<I", out, 16, len(ramdisk))

    h = hashlib.sha1()
    h.update(kernel)
    h.update(ramdisk)
    h.update(dt)
    out[1648 : 1648 + 32] = h.digest() + b"\x00" * 12

    new_footer = bytearray(footer)
    struct.pack_into(">Q", new_footer, 12, content_end)
    struct.pack_into(">Q", new_footer, 20, new_vb_off)
    out[FOOTER_OFF:PART_SIZE] = new_footer

    blob = bytes(out)
    assert len(blob) == PART_SIZE
    assert blob.rfind(b"AVBf") == FOOTER_OFF
    rd = gzip.decompress(blob[r_off : r_off + len(ramdisk)])
    assert b"usb_role_auto" in rd and b"usb_udc_unbound" in rd
    assert b"rndis_ok" not in rd
    assert b"switch_root" in rd and b"pmicwdt_off.ko" in rd
    assert b"sprd-wdt-fiq/unbind" not in rd

    print(f"ramdisk {old_rsz} -> {len(ramdisk)}")
    print(f"dt at {old_dt_off} -> {dt_off}")
    print(f"vbmeta {vb_size} at {vb_off} -> {new_vb_off}")

    out_img.write_bytes(blob)
    os.environ["COPYFILE_DISABLE"] = "1"
    td = tempfile.mkdtemp()
    boot = Path(td) / "boot.img"
    boot.write_bytes(blob)
    with tarfile.open(out_tar, "w") as tf:
        tf.add(boot, arcname="boot.img")
    os.system(f'xattr -c "{out_tar}" 2>/dev/null')
    print("wrote", out_tar, out_tar.stat().st_size)


if __name__ == "__main__":
    main()

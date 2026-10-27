#!/usr/bin/env python3
"""Pack boot-only v57: v56 ramdisk with a new kernel (real DRM PRIME + CONFIG_VT).

The kernel grows, so unlike v56 this cannot patch in place: the ramdisk, the
appended DT image and the AVB vbmeta blob all shift.  The AVB footer records
where vbmeta lives, so it is rewritten to match.
"""
from pathlib import Path
import gzip, hashlib, os, struct, tarfile, tempfile

BOOT_PACK = Path(os.environ.get("GTA8_BOOT_PACK", Path(__file__).resolve().parents[1] / "boot-pack"))

base_path = BOOT_PACK / "boot-gta8wifi-debug-v56.img"
kernel_path = BOOT_PACK / "Image-v57"
out_img = BOOT_PACK / "boot-gta8wifi-debug-v57.img"
out_tar = BOOT_PACK / "AP-boot-only-debug-v57.tar"

PART_SIZE = 64 * 1024 * 1024
FOOTER_OFF = PART_SIZE - 64


def pad(n, page=2048):
    return (n + page - 1) // page * page


def main():
    base = base_path.read_bytes()
    kernel = kernel_path.read_bytes()
    assert len(base) == PART_SIZE, len(base)

    page = struct.unpack_from("<I", base, 36)[0]
    old_ksz = struct.unpack_from("<I", base, 8)[0]
    rsz = struct.unpack_from("<I", base, 16)[0]
    ssz = struct.unpack_from("<I", base, 24)[0]
    assert page == 2048 and ssz == 0

    old_r_off = page + pad(old_ksz, page)
    ramdisk = base[old_r_off : old_r_off + rsz]

    # Footer describes the content end and where the vbmeta blob sits.
    footer = base[FOOTER_OFF:PART_SIZE]
    assert footer[:4] == b"AVBf"
    orig_size = struct.unpack_from(">Q", footer, 12)[0]
    vb_off = struct.unpack_from(">Q", footer, 20)[0]
    vb_size = struct.unpack_from(">Q", footer, 28)[0]
    vbmeta = base[vb_off : vb_off + vb_size]
    assert vbmeta[:4] == b"AVB0"

    # Appended Android DT image; it has always sat at the offset the boot
    # header implies, so keep it there relative to the new ramdisk.
    old_dt_off = old_r_off + pad(rsz, page)
    dt = base[old_dt_off:orig_size]
    assert dt[:4] == bytes.fromhex("d7b7ab1e"), dt[:4].hex()

    r_off = page + pad(len(kernel), page)
    dt_off = r_off + pad(rsz, page)
    content_end = dt_off + len(dt)
    new_vb_off = (content_end + 4095) // 4096 * 4096
    assert new_vb_off + vb_size < FOOTER_OFF

    out = bytearray(PART_SIZE)
    out[0:page] = base[0:page]
    out[2048 : 2048 + len(kernel)] = kernel
    out[r_off : r_off + rsz] = ramdisk
    out[dt_off : dt_off + len(dt)] = dt
    out[new_vb_off : new_vb_off + vb_size] = vbmeta

    struct.pack_into("<I", out, 8, len(kernel))
    struct.pack_into("<I", out, 16, rsz)

    # Same id placement the v10..v56 images shipped with; this bootloader does
    # not check it, and deviating here would change two things at once.
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
    assert blob[new_vb_off : new_vb_off + 4] == b"AVB0"
    rd = gzip.decompress(blob[r_off : r_off + rsz])
    assert b"switch_root" in rd and b"v56 dim+wdtko" in rd and b"nc -ll -p 2323" in rd
    assert b"pmicwdt_off.ko" in rd and b"drmstep-fb2" in rd
    assert b"sprd-wdt-fiq/unbind" not in rd, "watchdog unbind still present"

    print(f"kernel {old_ksz} -> {len(kernel)}")
    print(f"ramdisk {rsz} at {old_r_off} -> {r_off}")
    print(f"dt {len(dt)} at {old_dt_off} -> {dt_off}")
    print(f"vbmeta {vb_size} at {vb_off} -> {new_vb_off}")
    print(f"content end {orig_size} -> {content_end}")

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

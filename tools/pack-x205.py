#!/usr/bin/env python3
"""Pack an SM-X205 (gta8 LTE) boot.img from the X200 v57 kernel + ramdisk.

The kernel Image is SoC-common. What must stay X205-specific is the DT table
inside boot.img: the Wi-Fi and LTE overlays disagree on reserved-memory sizes
and on the AVB partition list (LTE adds l_modem/l_ldsp/l_gdsp). The bootloader
then applies stock dtbo. Do not flash an X200 boot.img onto an X205.

Inputs (override with env):
  GTA8LTE_STOCK_BOOT   X205 stock boot.img (DT + AVB footer)
  GTA8_BOOT_PACK       directory with Image-v57 and boot-gta8wifi-debug-v57.img
  GTA8LTE_BOOT_PACK    output directory
"""
from pathlib import Path
import gzip, hashlib, os, struct, tarfile, tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]

# Default search paths: local repo first, then environment override, then fallback
env_stock = os.environ.get("GTA8LTE_STOCK_BOOT")
if env_stock:
    STOCK_BOOT = Path(env_stock)
elif (REPO_ROOT / "stock" / "boot.img").is_file():
    STOCK_BOOT = REPO_ROOT / "stock" / "boot.img"
elif (REPO_ROOT / "boot-pack" / "stock-boot.img").is_file():
    STOCK_BOOT = REPO_ROOT / "boot-pack" / "stock-boot.img"
else:
    STOCK_BOOT = Path("/Volumes/Untitled/gta8lte/stock/images/boot.img")

env_wifi_pack = os.environ.get("GTA8_BOOT_PACK")
if env_wifi_pack:
    WIFI_PACK = Path(env_wifi_pack)
elif (REPO_ROOT / "boot-pack" / "Image-v57").is_file():
    WIFI_PACK = REPO_ROOT / "boot-pack"
else:
    WIFI_PACK = Path("/Volumes/Untitled/gta8wifi/boot-pack")

env_out_pack = os.environ.get("GTA8LTE_BOOT_PACK")
if env_out_pack:
    OUT_PACK = Path(env_out_pack)
else:
    OUT_PACK = REPO_ROOT / "boot-pack"

kernel_path = WIFI_PACK / "Image-v57"
donor_path = WIFI_PACK / "boot-gta8wifi-debug-v57.img"
out_img = OUT_PACK / "boot-gta8lte-debug-v57.img"
out_tar = OUT_PACK / "AP-boot-only-debug-x205-v57.tar"

DT_MAGIC = bytes.fromhex("d7b7ab1e")


def pad(n, page=2048):
    return (n + page - 1) // page * page


def split_boot(blob: bytes):
    assert blob[:8] == b"ANDROID!", blob[:8]
    page = struct.unpack_from("<I", blob, 36)[0]
    ksz = struct.unpack_from("<I", blob, 8)[0]
    rsz = struct.unpack_from("<I", blob, 16)[0]
    ssz = struct.unpack_from("<I", blob, 24)[0]
    assert page == 2048 and ssz == 0
    r_off = page + pad(ksz, page)
    dt_off = r_off + pad(rsz, page)
    return page, ksz, rsz, r_off, dt_off


def find_avb(blob: bytes):
    footer_off = blob.rfind(b"AVBf")
    assert footer_off != -1 and footer_off + 64 <= len(blob)
    footer = blob[footer_off : footer_off + 64]
    orig_size = struct.unpack_from(">Q", footer, 12)[0]
    vb_off = struct.unpack_from(">Q", footer, 20)[0]
    vb_size = struct.unpack_from(">Q", footer, 28)[0]
    vbmeta = blob[vb_off : vb_off + vb_size]
    assert vbmeta[:4] == b"AVB0"
    return footer_off, footer, orig_size, vb_off, vb_size, vbmeta


def main():
    if not STOCK_BOOT.is_file():
        raise SystemExit(f"missing X205 stock boot: {STOCK_BOOT}\nRun 'python3 tools/extract-stock-boot.py <firmware.zip>' first.")

    if not kernel_path.is_file():
        raise SystemExit(f"missing v57 kernel: {kernel_path}\nPlace Image-v57 in {WIFI_PACK}")

    ramdisk_gz_path = WIFI_PACK / "ramdisk.cpio.gz"
    if ramdisk_gz_path.is_file():
        print(f"using standalone ramdisk: {ramdisk_gz_path}")
        ramdisk = ramdisk_gz_path.read_bytes()
    elif donor_path.is_file():
        print(f"extracting ramdisk from donor image: {donor_path}")
        donor = donor_path.read_bytes()
        _dp, _dk, drsz, donor_r_off, _ddt = split_boot(donor)
        ramdisk = donor[donor_r_off : donor_r_off + drsz]
    else:
        raise SystemExit(f"missing ramdisk: neither {ramdisk_gz_path} nor {donor_path} found")

    stock = STOCK_BOOT.read_bytes()
    kernel = kernel_path.read_bytes()
    part_size = len(stock)
    if part_size < 16 * 1024 * 1024:
        raise SystemExit(f"stock boot looks too small: {part_size} bytes")

    page, _sk, _sr, _sro, stock_dt_off = split_boot(stock)
    footer_off, footer, orig_size, _svb, vb_size, vbmeta = find_avb(stock)
    dt = stock[stock_dt_off:orig_size]
    assert dt[:4] == DT_MAGIC, f"stock DT magic {dt[:4].hex()} (want {DT_MAGIC.hex()})"

    rd = gzip.decompress(ramdisk)
    assert b"switch_root" in rd and b"mmcblk1p1" in rd

    r_off = page + pad(len(kernel), page)
    dt_off = r_off + pad(len(ramdisk), page)
    content_end = dt_off + len(dt)
    new_vb_off = (content_end + 4095) // 4096 * 4096
    if new_vb_off + vb_size >= footer_off:
        raise SystemExit("kernel+ramdisk+dt do not fit under the AVB footer")

    out = bytearray(part_size)
    out[0:page] = stock[0:page]
    out[page : page + len(kernel)] = kernel
    out[r_off : r_off + len(ramdisk)] = ramdisk
    out[dt_off : dt_off + len(dt)] = dt
    out[new_vb_off : new_vb_off + vb_size] = vbmeta

    struct.pack_into("<I", out, 8, len(kernel))
    struct.pack_into("<I", out, 16, len(ramdisk))

    h = hashlib.sha1()
    h.update(kernel)
    h.update(ramdisk)
    h.update(dt)
    out[1648 : 1648 + 32] = h.digest() + b"\x00" * 12

    new_footer = bytearray(footer)
    struct.pack_into(">Q", new_footer, 12, content_end)
    struct.pack_into(">Q", new_footer, 20, new_vb_off)
    out[footer_off : footer_off + 64] = new_footer

    blob = bytes(out)
    assert blob[:8] == b"ANDROID!"
    assert blob[dt_off : dt_off + 4] == DT_MAGIC
    assert blob[new_vb_off : new_vb_off + 4] == b"AVB0"

    OUT_PACK.mkdir(parents=True, exist_ok=True)
    out_img.write_bytes(blob)
    os.environ["COPYFILE_DISABLE"] = "1"
    td = tempfile.mkdtemp()
    boot = Path(td) / "boot.img"
    boot.write_bytes(blob)
    with tarfile.open(out_tar, "w", format=tarfile.USTAR_FORMAT) as tf:
        ti = tf.gettarinfo(boot, arcname="boot.img")
        ti.mtime = int(ti.mtime)
        ti.pax_headers = {}
        with open(boot, "rb") as f:
            tf.addfile(ti, f)
    os.system(f'xattr -c "{out_tar}" 2>/dev/null')

    print(f"stock {STOCK_BOOT} ({part_size} bytes)")
    print(f"kernel {len(kernel)} ramdisk {len(ramdisk)} dt {len(dt)}")
    print(f"dt {stock_dt_off} -> {dt_off}")
    print(f"vbmeta {vb_size} -> {new_vb_off}")
    print("wrote", out_tar, out_tar.stat().st_size)


if __name__ == "__main__":
    main()

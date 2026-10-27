#!/usr/bin/env python3
"""Extract and decompress stock boot.img from Samsung firmware files (.zip, AP_*.tar.md5, or boot.img.lz4).

Usage:
    python3 tools/extract-stock-boot.py /path/to/Samsung_Firmware.zip
    python3 tools/extract-stock-boot.py /path/to/AP_X205XX...tar.md5
    python3 tools/extract-stock-boot.py /path/to/boot.img.lz4
"""
from __future__ import annotations

import io
import os
import struct
import sys
import tarfile
import zipfile
from pathlib import Path


def decompress_lz4_block(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        token = data[i]
        i += 1
        lit_len = token >> 4
        if lit_len == 15:
            while i < n:
                b = data[i]
                i += 1
                lit_len += b
                if b != 255:
                    break
        out.extend(data[i : i + lit_len])
        i += lit_len
        if i >= n:
            break
        offset = struct.unpack_from("<H", data, i)[0]
        i += 2
        match_len = (token & 0x0F) + 4
        if match_len == 19:
            while i < n:
                b = data[i]
                i += 1
                match_len += b
                if b != 255:
                    break
        pos = len(out) - offset
        for _ in range(match_len):
            out.append(out[pos])
            pos += 1
    return bytes(out)


def decompress_lz4_frame(data: bytes) -> bytes:
    if data[:4] != b"\x04\x22\x4d\x18":
        raise ValueError("Not an LZ4 frame (magic mismatch)")
    flg = data[4]
    has_block_checksum = bool(flg & (1 << 4))
    has_content_size = bool(flg & (1 << 3))
    has_dict_id = bool(flg & 1)

    idx = 6
    if has_content_size:
        idx += 8
    if has_dict_id:
        idx += 4
    idx += 1  # header checksum

    out = bytearray()
    while idx < len(data):
        bsize = struct.unpack_from("<I", data, idx)[0]
        idx += 4
        if bsize == 0:  # EndMark
            break
        is_uncompressed = bool(bsize & 0x80000000)
        bsize = bsize & 0x7FFFFFFF
        block = data[idx : idx + bsize]
        idx += bsize
        if has_block_checksum:
            idx += 4
        if is_uncompressed:
            out.extend(block)
        else:
            out.extend(decompress_lz4_block(block))
    return bytes(out)


def extract_from_tar(tar_bytes_or_file) -> bytes | None:
    if isinstance(tar_bytes_or_file, bytes):
        tf = tarfile.open(fileobj=io.BytesIO(tar_bytes_or_file))
    else:
        tf = tarfile.open(tar_bytes_or_file, "r:*")

    for member in tf.getmembers():
        if member.name == "boot.img":
            print("  Found boot.img (uncompressed)")
            f = tf.extractfile(member)
            return f.read() if f else None
        elif member.name == "boot.img.lz4":
            print("  Found boot.img.lz4, decompressing...")
            f = tf.extractfile(member)
            if f:
                raw_lz4 = f.read()
                return decompress_lz4_frame(raw_lz4)
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    src = Path(sys.argv[1]).expanduser().resolve()
    if not src.is_file():
        print(f"Error: file not found: {src}")
        sys.exit(1)

    out_dir = Path("stock")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_boot = out_dir / "boot.img"

    print(f"Processing: {src}")
    boot_bytes: bytes | None = None

    if src.name.endswith(".zip"):
        print("Opening ZIP archive...")
        with zipfile.ZipFile(src, "r") as zf:
            ap_names = [n for n in zf.namelist() if n.startswith("AP_") and (n.endswith(".tar") or n.endswith(".tar.md5"))]
            if ap_names:
                print(f"Extracting {ap_names[0]} from ZIP...")
                with zf.open(ap_names[0]) as ap_file:
                    boot_bytes = extract_from_tar(ap_file.read())
            else:
                print("No AP_* archive found inside ZIP. Checking root of zip...")
                for zname in zf.namelist():
                    if zname == "boot.img":
                        boot_bytes = zf.read(zname)
                        break
                    elif zname == "boot.img.lz4":
                        boot_bytes = decompress_lz4_frame(zf.read(zname))
                        break

    elif src.name.startswith("AP_") or src.name.endswith(".tar") or src.name.endswith(".tar.md5"):
        print("Opening TAR archive...")
        boot_bytes = extract_from_tar(src)

    elif src.name == "boot.img.lz4":
        print("Decompressing LZ4 file...")
        boot_bytes = decompress_lz4_frame(src.read_bytes())

    elif src.name == "boot.img":
        print("Source is already boot.img, copying...")
        boot_bytes = src.read_bytes()

    if not boot_bytes:
        print("[!] Error: Could not locate boot.img or boot.img.lz4 in the provided file.")
        sys.exit(1)

    assert boot_bytes[:8] == b"ANDROID!", f"Invalid boot magic: {boot_bytes[:8]}"
    out_boot.write_bytes(boot_bytes)
    print(f"\n[OK] Successfully saved stock boot.img to: {out_boot} ({len(boot_bytes)} bytes)")
    print(f"     You can now run: python3 tools/pack-x205.py")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Patch Unisoc sprdwl_ng.ko Wi-Fi driver to remove task_struct ABI crash."""
from __future__ import annotations

import pathlib
import struct
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STOCK_KO = REPO_ROOT / "stock" / "sprdwl_ng.ko"
PATCHED_KO = REPO_ROOT / "stock" / "sprdwl_ng_patched.ko"


def patch_module(src: pathlib.Path, dst: pathlib.Path) -> bool:
    if not src.is_file():
        print(f"[!] Source module {src} not found")
        return False

    data = bytearray(src.read_bytes())

    # ELF header
    e_shoff = struct.unpack_from("<Q", data, 40)[0]
    e_shentsize = struct.unpack_from("<H", data, 58)[0]
    e_shnum = struct.unpack_from("<H", data, 60)[0]
    e_shstrndx = struct.unpack_from("<H", data, 62)[0]
    sh_str_offset = struct.unpack_from("<Q", data, e_shoff + e_shstrndx * e_shentsize + 24)[0]

    text_offset = None
    rela_text_offset = None
    rela_text_size = None

    for i in range(e_shnum):
        sec = e_shoff + i * e_shentsize
        sh_name = struct.unpack_from("<I", data, sec)[0]
        sh_offset = struct.unpack_from("<Q", data, sec + 24)[0]
        sh_size = struct.unpack_from("<Q", data, sec + 32)[0]
        name = data[sh_str_offset + sh_name:].split(b"\0")[0].decode()
        if name == ".text":
            text_offset = sh_offset
        elif name == ".rela.text":
            rela_text_offset = sh_offset
            rela_text_size = sh_size

    if not text_offset or not rela_text_offset:
        print("[!] Could not locate .text or .rela.text sections in module")
        return False

    # Crash sequence at 0x2240: 11 instructions (mrs x26, SP_EL0 ... bl memcpy)
    crash_start = text_offset + 0x2240
    nop = b"\x1f\x20\x03\xd5"
    for i in range(11):
        data[crash_start + i * 4 : crash_start + (i + 1) * 4] = nop

    # Change relocations for strlen (0x2258) and memcpy (0x2268) to R_AARCH64_NONE (0)
    num_relas = rela_text_size // 24
    relas_patched = 0
    for i in range(num_relas):
        r_off = rela_text_offset + i * 24
        r_offset, r_info, _ = struct.unpack_from("<QQq", data, r_off)
        if r_offset in (0x2258, 0x2268):
            sym = r_info >> 32
            new_info = (sym << 32) | 0  # R_AARCH64_NONE
            struct.pack_into("<QQq", data, r_off, r_offset, new_info, 0)
            relas_patched += 1

    dst.write_bytes(data)
    print(f"[OK] Successfully patched sprdwl_ng.ko ({relas_patched} relocs neutralized) -> {dst}")
    return True


if __name__ == "__main__":
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else STOCK_KO
    dst = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else PATCHED_KO
    patch_module(src, dst)

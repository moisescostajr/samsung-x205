#!/usr/bin/env python3
"""Read-only extractor for small files from an ext4 partition (macOS helper)."""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

EXT4_SUPER_OFFSET = 1024
EXT4_SUPER_MAGIC = 0xEF53
INODE_ROOT = 2
S_IFDIR = 0o040000
S_IFREG = 0o100000
INCOMPAT_FILETYPE = 0x2
INCOMPAT_EXTENTS = 0x40
INCOMPAT_64BIT = 0x80
EXT4_EXTENTS_FL = 0x00080000
EXT4_INDEX_FL = 0x00001000


class Ext4:
    def __init__(self, path: str):
        self.fd = os.open(path, os.O_RDONLY)
        raw = self._pread(EXT4_SUPER_OFFSET, 1024)
        magic = struct.unpack_from("<H", raw, 0x38)[0]
        if magic != EXT4_SUPER_MAGIC:
            raise SystemExit(f"not ext4 (magic {magic:#x}) at {path}")
        self.inodes_count = struct.unpack_from("<I", raw, 0x0)[0]
        self.blocks_count = struct.unpack_from("<I", raw, 0x4)[0]
        self.first_data_block = struct.unpack_from("<I", raw, 0x14)[0]
        log_block_size = struct.unpack_from("<I", raw, 0x18)[0]
        self.block_size = 1024 << log_block_size
        self.blocks_per_group = struct.unpack_from("<I", raw, 0x20)[0]
        self.inodes_per_group = struct.unpack_from("<I", raw, 0x28)[0]
        self.inode_size = struct.unpack_from("<H", raw, 0x58)[0]
        self.desc_size = struct.unpack_from("<H", raw, 0xFE)[0] or 32
        incompat = struct.unpack_from("<I", raw, 0x60)[0]
        self.has_filetype = bool(incompat & INCOMPAT_FILETYPE)
        self.has_extents = bool(incompat & INCOMPAT_EXTENTS)
        if not (incompat & INCOMPAT_64BIT):
            self.desc_size = 32
        self.blocks_count |= struct.unpack_from("<I", raw, 0x150)[0] << 32
        self.group_count = (
            self.blocks_count - self.first_data_block + self.blocks_per_group - 1
        ) // self.blocks_per_group
        print(
            f"super: block={self.block_size} blocks={self.blocks_count} "
            f"groups={self.group_count} desc={self.desc_size} "
            f"inode_size={self.inode_size} inodes/group={self.inodes_per_group} "
            f"first_data={self.first_data_block} incompat={incompat:#x}"
        )
        self._gdt = self._read_gdt()

    def close(self) -> None:
        os.close(self.fd)

    def _pread(self, off: int, n: int) -> bytes:
        # macOS raw disks require 512-byte aligned reads.
        align = 512
        aligned_off = off - (off % align)
        skip = off - aligned_off
        aligned_n = skip + n
        if aligned_n % align:
            aligned_n += align - (aligned_n % align)
        got = b""
        while len(got) < aligned_n:
            chunk = os.pread(self.fd, aligned_n - len(got), aligned_off + len(got))
            if not chunk:
                break
            got += chunk
        return got[skip : skip + n]

    def _read_gdt(self) -> list[tuple[int, int]]:
        gdt_block = self.first_data_block + 1
        raw = self._pread(gdt_block * self.block_size, self.group_count * self.desc_size)
        out = []
        for i in range(self.group_count):
            d = raw[i * self.desc_size : (i + 1) * self.desc_size]
            bg_inode_table = struct.unpack_from("<I", d, 0x8)[0]
            if self.desc_size >= 40:
                bg_inode_table |= struct.unpack_from("<I", d, 0x28)[0] << 32
            bg_free_inodes = struct.unpack_from("<H", d, 0xE)[0]
            out.append((bg_inode_table, bg_free_inodes))
        return out

    def inode(self, ino: int) -> bytes:
        if ino < 1:
            raise ValueError("bad inode")
        group = (ino - 1) // self.inodes_per_group
        index = (ino - 1) % self.inodes_per_group
        table_block = self._gdt[group][0]
        off = table_block * self.block_size + index * self.inode_size
        return self._pread(off, self.inode_size)

    def inode_meta(self, ino: int) -> dict:
        raw = self.inode(ino)
        mode, uid, size_lo, atime, ctime, mtime, dtime, gid, links, blocks_lo, flags = struct.unpack_from(
            "<HHIIIIIIIII", raw, 0
        )
        size_hi = struct.unpack_from("<I", raw, 0x6C)[0]
        i_block = raw[0x28:0x64]
        return {
            "mode": mode,
            "size": size_lo | (size_hi << 32),
            "flags": flags,
            "i_block": i_block,
            "raw": raw,
        }

    def _extent_blocks(self, node: bytes) -> list[tuple[int, int]]:
        magic, entries, max_entries, depth, _ = struct.unpack_from("<HHHHI", node, 0)
        if magic != 0xF30A:
            raise RuntimeError(f"bad extent magic {magic:#x}")
        out: list[tuple[int, int]] = []
        if depth == 0:
            for i in range(entries):
                ee_block, ee_len, ee_start_hi, ee_start_lo = struct.unpack_from("<IHHI", node, 12 + i * 12)
                start = ee_start_lo | (ee_start_hi << 32)
                length = ee_len & 0x7FFF
                out.append((start, length))
            return out
        for i in range(entries):
            _ei_block, ei_leaf_lo, ei_leaf_hi, _ = struct.unpack_from("<IIHH", node, 12 + i * 12)
            leaf = ei_leaf_lo | (ei_leaf_hi << 32)
            child = self._pread(leaf * self.block_size, self.block_size)
            out.extend(self._extent_blocks(child))
        return out

    def _read_block_ptrs(self, block: int) -> list[int]:
        raw = self._pread(block * self.block_size, self.block_size)
        n = self.block_size // 4
        return list(struct.unpack("<%dI" % n, raw))

    def _indirect_ranges(self, i_block: bytes, size: int) -> list[tuple[int, int]]:
        ptrs = list(struct.unpack_from("<15I", i_block))
        needed = (size + self.block_size - 1) // self.block_size
        blocks: list[int] = []

        def take(bs: list[int]) -> None:
            for b in bs:
                if len(blocks) >= needed:
                    return
                blocks.append(b)

        take(ptrs[:12])
        if len(blocks) < needed and ptrs[12]:
            take(self._read_block_ptrs(ptrs[12]))
        if len(blocks) < needed and ptrs[13]:
            for ib in self._read_block_ptrs(ptrs[13]):
                if not ib:
                    continue
                take(self._read_block_ptrs(ib))
                if len(blocks) >= needed:
                    break
        if len(blocks) < needed and ptrs[14]:
            for dib in self._read_block_ptrs(ptrs[14]):
                if not dib:
                    continue
                for ib in self._read_block_ptrs(dib):
                    if not ib:
                        continue
                    take(self._read_block_ptrs(ib))
                    if len(blocks) >= needed:
                        break
                if len(blocks) >= needed:
                    break
        ranges: list[tuple[int, int]] = []
        for b in blocks[:needed]:
            if b:
                ranges.append((b, 1))
            else:
                ranges.append((0, 1))
        return ranges

    def read_inode_data(self, ino: int, limit: int | None = None) -> bytes:
        meta = self.inode_meta(ino)
        size = meta["size"]
        if limit is not None:
            size = min(size, limit)
        if size == 0:
            return b""
        use_extents = bool(meta["flags"] & EXT4_EXTENTS_FL) or (
            self.has_extents and struct.unpack_from("<H", meta["i_block"], 0)[0] == 0xF30A
        )
        if use_extents:
            ranges = self._extent_blocks(meta["i_block"] + b"\x00" * 4)
        else:
            ranges = self._indirect_ranges(meta["i_block"], size)
        data = bytearray()
        remaining = size
        for start, nblocks in ranges:
            chunk_n = min(nblocks * self.block_size, remaining)
            if start == 0:
                data.extend(b"\x00" * chunk_n)
            else:
                data.extend(self._pread(start * self.block_size, chunk_n))
            remaining -= chunk_n
            if remaining <= 0:
                break
        return bytes(data[:size])

    def listdir(self, ino: int) -> list[tuple[str, int, int]]:
        meta = self.inode_meta(ino)
        if (meta["mode"] & 0o170000) != S_IFDIR:
            raise RuntimeError(f"inode {ino} is not a directory")
        raw = self.read_inode_data(ino)
        ents: list[tuple[str, int, int]] = []
        # Directory blocks are independent (needed for htree / dir_index).
        for block_off in range(0, len(raw), self.block_size):
            block = raw[block_off : block_off + self.block_size]
            off = 0
            while off + 8 <= len(block):
                inode, rec_len, name_len, file_type = struct.unpack_from("<IHBB", block, off)
                if rec_len < 8 or off + rec_len > len(block):
                    break
                if inode != 0 and 0 < name_len <= rec_len - 8:
                    name = block[off + 8 : off + 8 + name_len].decode("utf-8", "replace")
                    if name not in (".", "..") and "\x00" not in name:
                        ents.append((name, inode, file_type))
                off += rec_len
        return ents

    def used_inodes(self, max_groups: int = 4) -> list[int]:
        found: list[int] = []
        for g in range(min(max_groups, self.group_count)):
            base = g * self.inodes_per_group
            for idx in range(self.inodes_per_group):
                ino = base + idx + 1
                raw = self.inode(ino)
                mode = struct.unpack_from("<H", raw, 0)[0]
                if mode != 0:
                    found.append(ino)
        return found

    def resolve(self, path: str) -> int:
        ino = INODE_ROOT
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            return ino
        for part in parts:
            found = None
            for name, child, _ft in self.listdir(ino):
                if name == part:
                    found = child
                    break
            if found is None:
                raise FileNotFoundError(path)
            ino = found
        return ino


def dump_interesting(fs: Ext4, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    used = fs.used_inodes(max_groups=2)
    (dest / "used-inodes.txt").write_text(
        "\n".join(str(i) for i in used) + "\n", encoding="utf-8"
    )
    inode_listing = []
    for ino in used:
        try:
            meta = fs.inode_meta(ino)
            kind = meta["mode"] & 0o170000
            inode_listing.append(f"{ino} {oct(meta['mode'])} {meta['size']} flags={meta['flags']:#x}")
            if kind == S_IFREG and 0 < meta["size"] <= 8 * 1024 * 1024:
                data = fs.read_inode_data(ino)
                out = dest / f"ino{ino}.bin"
                out.write_bytes(data)
                written.append(str(out))
                # also as text if it looks like a log
                if b"\x00" not in data[:64]:
                    (dest / f"ino{ino}.txt").write_bytes(data)
        except Exception as e:
            inode_listing.append(f"{ino} ERR {e}")
    (dest / "inode-scan.txt").write_text("\n".join(inode_listing) + "\n", encoding="utf-8")
    root_raw = fs.inode(INODE_ROOT)
    (dest / "inode2.raw").write_bytes(root_raw)
    ptr0 = struct.unpack_from("<I", root_raw, 0x28)[0]
    if ptr0:
        (dest / "rootdir-block.bin").write_bytes(fs._pread(ptr0 * fs.block_size, fs.block_size))
    candidates = [
        "/root",
        "/mnt/root",
        "/tmp",
        "/",
    ]
    names_of_interest = (
        "dmesg",
        "netifs",
        "ifconfig",
        "udc",
        "booted",
        "v27",
        "v26",
        "v25",
        "v24",
        "v28",
        "kmsg",
        "log",
    )
    seen: set[int] = set()

    def consider(dir_path: str) -> None:
        try:
            ino = fs.resolve(dir_path)
        except FileNotFoundError:
            return
        except Exception as e:
            (dest / "listdir-errors.txt").write_text(
                ((dest / "listdir-errors.txt").read_text() if (dest / "listdir-errors.txt").exists() else "")
                + f"{dir_path}: {e}\n",
                encoding="utf-8",
            )
            return
        if ino in seen:
            return
        seen.add(ino)
        try:
            ents = fs.listdir(ino)
        except Exception as e:
            (dest / "listdir-errors.txt").write_text(
                (dest / "listdir-errors.txt").read_text() + f"{dir_path}: {e}\n"
                if (dest / "listdir-errors.txt").exists()
                else f"{dir_path}: {e}\n",
                encoding="utf-8",
            )
            return
        listing = []
        for name, child, ft in ents:
            try:
                meta = fs.inode_meta(child)
                listing.append(f"{oct(meta['mode'])} {meta['size']:10d} {name}")
                low = name.lower()
                if any(tok in low for tok in names_of_interest) and (meta["mode"] & 0o170000) == S_IFREG:
                    if meta["size"] > 8 * 1024 * 1024:
                        continue
                    data = fs.read_inode_data(child)
                    out = dest / f"{dir_path.strip('/').replace('/', '_')}_{name}"
                    out.write_bytes(data)
                    written.append(str(out))
            except Exception as e:
                listing.append(f"ERR {name}: {e}")
        listing_path = dest / f"{(dir_path.strip('/') or 'rootdir').replace('/', '_')}-listing.txt"
        listing_path.write_text("\n".join(listing) + "\n", encoding="utf-8")

    for path in candidates:
        consider(path)
    # Always try explicit v27 dump paths used by the ramdisk.
    for path in [
        "/root/dmesg-v27.txt",
        "/root/netifs-v27.txt",
        "/root/ifconfig-v27.txt",
        "/root/udc-v27.txt",
        "/root/booted-v27.txt",
        "/mnt/root/dmesg-v27.txt",
        "/mnt/root/netifs-v27.txt",
        "/mnt/root/ifconfig-v27.txt",
        "/mnt/root/udc-v27.txt",
        "/mnt/root/booted-v27.txt",
    ]:
        try:
            ino = fs.resolve(path)
            data = fs.read_inode_data(ino, 4 * 1024 * 1024)
            out = dest / path.strip("/").replace("/", "_")
            out.write_bytes(data)
            written.append(str(out))
        except FileNotFoundError:
            continue
        except Exception as e:
            (dest / "extract-errors.txt").write_text(
                ((dest / "extract-errors.txt").read_text() if (dest / "extract-errors.txt").exists() else "")
                + f"{path}: {e}\n",
                encoding="utf-8",
            )
    return written


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: ext4_extract_logs.py /dev/rdiskXsY /out/dir", file=sys.stderr)
        return 2
    src, dest_s = sys.argv[1], sys.argv[2]
    dest = Path(dest_s)
    fs = Ext4(src)
    try:
        sb = fs.inode_meta(INODE_ROOT)
        ptrs = struct.unpack_from("<15I", sb["i_block"])
        print(
            f"ext4 ok block={fs.block_size} groups={fs.group_count} "
            f"inodes/group={fs.inodes_per_group} root_mode={oct(sb['mode'])} "
            f"root_size={sb['size']} root_flags={sb['flags']:#x} "
            f"g0_itable={fs._gdt[0][0]} i_block={ptrs[:12]}"
        )
        sample = fs.read_inode_data(INODE_ROOT, 256)
        print("root data", len(sample), sample[:64].hex())
        super_raw = fs._pread(EXT4_SUPER_OFFSET, 256)
        print(
            "s_rev", struct.unpack_from("<I", super_raw, 0x4C)[0],
            "s_inode_size_field", struct.unpack_from("<H", super_raw, 0x58)[0],
            "compat", hex(struct.unpack_from("<I", super_raw, 0x5C)[0]),
            "incompat", hex(struct.unpack_from("<I", super_raw, 0x60)[0]),
            "ro_compat", hex(struct.unpack_from("<I", super_raw, 0x64)[0]),
        )
        itable = fs._gdt[0][0] * fs.block_size
        print("gdt0", fs._pread(fs.block_size, 32).hex())
        for i in range(1, 12):
            raw_i = fs._pread(itable + (i - 1) * fs.inode_size, 32)
            mode = struct.unpack_from("<H", raw_i, 0)[0]
            print(f"inode{i}", oct(mode), raw_i.hex())
        # Scan early disk for a root directory '.' entry.
        needle = bytes.fromhex("020000000c0001022e")
        blob = fs._pread(0, 8 * 1024 * 1024)
        pos = blob.find(needle)
        print("root dirent scan 8MiB", pos)
        written = dump_interesting(fs, dest)
        print("wrote", len(written), "files into", dest)
        for p in written:
            print(" ", p)
        # top-level names always
        names = [n for n, _i, _t in fs.listdir(INODE_ROOT)]
        print("root entries:", ", ".join(names[:40]))
    finally:
        fs.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

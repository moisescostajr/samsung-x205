#!/usr/bin/python3
"""Build the VBC profile blobs the SPRD kernel loads for the audio DSP.

sound/soc/sprd/dai/vbc/v4/vbc-codec.c opens /vendor/firmware/<name> directly
when userspace writes to "<X> Profile Update". On stock Android those paths
are symlinks into /data, which the Android audio HAL fills in at runtime by
compiling /vendor/etc/audio_params/<region>/<name>.xml into a flat blob. The
unlock wiped /data, so we regenerate the blobs from the same XML.

Layout (struct vbc_fw_header + modes):
    char magic[16]  "audio_profile"
    u32  num_mode
    u32  len_mode
    num_mode * len_mode bytes of mode structs

Each XML leaf carries everything needed: "id" is the byte offset inside the
mode struct, "t" the field type, and "offset"/"bits"/"val" the bitfield
placement, so the conversion is mechanical.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

MAGIC = b"audio_profile"
MAGIC_LEN = 16

TYPE_SIZE = {
    "u8": 1, "s8": 1, "i8": 1,
    "u16": 2, "s16": 2, "i16": 2,
    "u32": 4, "s32": 4, "i32": 4,
}


def field_size(t: str | None, bits_attr: str | None) -> int | None:
    if t in TYPE_SIZE:
        return TYPE_SIZE[t]
    # dsp_vbc uses t="<bitcount>" for reserved blocks, e.g. t="12288".
    for text in (t, bits_attr):
        if text is None:
            continue
        try:
            nbits = int(text, 0)
        except ValueError:
            continue
        if nbits % 8 == 0 and nbits > 0:
            return nbits // 8
    return None


def parse_int(text: str | None) -> int:
    if not text:
        return 0
    return int(text, 0)


def emit_field(buf: bytearray, elem: ET.Element) -> None:
    base = parse_int(elem.get("id"))
    size = field_size(elem.get("t"), elem.get("bits"))
    if size is None or base + size > len(buf):
        return

    children = [c for c in elem if c.get("bits") is not None]
    value = 0
    if children:
        for c in children:
            nbits = parse_int(c.get("bits"))
            shift = parse_int(c.get("offset"))
            mask = (1 << nbits) - 1 if nbits < 64 else ~0
            value |= (parse_int(c.get("val")) & mask) << shift
    else:
        nbits = parse_int(elem.get("bits"))
        shift = parse_int(elem.get("offset"))
        mask = (1 << nbits) - 1 if 0 < nbits < 64 else (1 << (size * 8)) - 1
        value = (parse_int(elem.get("val")) & mask) << shift

    value &= (1 << (size * 8)) - 1
    buf[base:base + size] = value.to_bytes(size, "little")


def build_mode(elem: ET.Element, length: int) -> bytearray:
    buf = bytearray(length)
    for child in elem:
        if child.get("id") is not None:
            emit_field(buf, child)
    return buf


def build(path: str, out: str) -> int:
    root = ET.parse(path).getroot()
    num_mode = parse_int(root.get("num_mode"))
    len_mode = parse_int(root.get("struct_size"))
    if not num_mode or not len_mode:
        print(f"{path}: missing num_mode/struct_size", file=sys.stderr)
        return 1

    modes: dict[int, bytearray] = {}
    names: dict[int, str] = {}
    for parent in root.iter():
        for elem in parent:
            m = elem.get("mode")
            if m is None:
                continue
            idx = parse_int(m)
            if idx in modes:
                continue
            modes[idx] = build_mode(elem, len_mode)
            names[idx] = f"{parent.tag}/{elem.tag}"

    blob = bytearray(MAGIC.ljust(MAGIC_LEN, b"\x00"))
    blob += num_mode.to_bytes(4, "little")
    blob += len_mode.to_bytes(4, "little")
    for i in range(num_mode):
        blob += modes.get(i, bytearray(len_mode))

    with open(out, "wb") as f:
        f.write(blob)

    missing = [i for i in range(num_mode) if i not in modes]
    print(f"{out}: num_mode={num_mode} len_mode={len_mode} "
          f"size={len(blob)} filled={len(modes)} missing={len(missing)}")
    return 0


def list_modes(path: str) -> int:
    root = ET.parse(path).getroot()
    for parent in root.iter():
        for elem in parent:
            m = elem.get("mode")
            if m is not None:
                print(f"  mode {parse_int(m):3d}  {parent.tag}/{elem.tag}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--list":
        return list_modes(argv[2])
    if len(argv) != 3:
        print(f"usage: {argv[0]} <in.xml> <out.bin> | --list <in.xml>",
              file=sys.stderr)
        return 2
    return build(argv[1], argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

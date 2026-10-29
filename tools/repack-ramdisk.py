#!/usr/bin/env python3
"""Rebuild boot-pack/ramdisk.cpio.gz and the X205 Odin tar locally.

The initramfs itself lives in tools/initramfs and is assembled by
tools/build-ramdisk.sh, which is also what CI runs.  This wrapper only adds
the locally patched vendor Wi-Fi module (if present) and then packs the boot
image with the stock SM-X205 DT/AVB footer.
"""
import pathlib
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
BOOT_PACK = REPO_ROOT / "boot-pack"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=REPO_ROOT, check=True, **kw)


def main() -> int:
    have_busybox = (TOOLS / "busybox-arm64").is_file()
    have_ramdisk = (BOOT_PACK / "ramdisk.cpio.gz").is_file()
    if not have_busybox and not have_ramdisk:
        raise SystemExit(
            "missing tools/busybox-arm64 and boot-pack/ramdisk.cpio.gz; run "
            "tools/fetch-image.py --boot-pack or tools/build-kernel-ci.sh first"
        )

    BOOT_PACK.mkdir(parents=True, exist_ok=True)

    # A patched sprdwl_ng.ko is kept out of git (vendor blob); use it when the
    # local checkout has one.
    patched = REPO_ROOT / "stock" / "sprdwl_ng_patched.ko"
    if patched.is_file():
        (BOOT_PACK / "modules").mkdir(parents=True, exist_ok=True)
        shutil.copy2(patched, BOOT_PACK / "modules" / "sprdwl_ng.ko")
        shutil.copy2(patched, TOOLS / "sprdwl_ng.ko")

    if have_busybox:
        run(["bash", "tools/build-ramdisk.sh"])
    else:
        print("[skip] tools/busybox-arm64 absent; using the release ramdisk")
    run([sys.executable, "tools/pack-x205.py"])

    out = BOOT_PACK / "AP-boot-only-debug-x205-v58.tar"
    if not out.is_file():
        raise SystemExit(f"packing finished but {out} is missing")
    print(f"[OK] {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

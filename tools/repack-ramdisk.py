#!/usr/bin/env python3
"""Assemble a robust ramdisk.cpio.gz and pack the final Odin tar locally."""
import gzip
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BOOT_PACK = REPO_ROOT / "boot-pack"
TOOLS_DIR = REPO_ROOT / "tools"
BUSYBOX_BIN = TOOLS_DIR / "busybox-arm64"

INIT_SCRIPT = r"""#!/bin/busybox sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
BUSYBOX=/bin/busybox
trap '' HUP INT QUIT TSTP TTIN TTOU

# Essential filesystems
$BUSYBOX mkdir -p /proc /sys /dev /tmp /run /mnt/root /config /modules
$BUSYBOX mount -t proc proc /proc 2>/dev/null || true
$BUSYBOX mount -t sysfs sysfs /sys 2>/dev/null || true
$BUSYBOX mount -t tmpfs tmpfs /dev 2>/dev/null || true

# Essential device nodes in /dev
$BUSYBOX mknod -m 600 /dev/console c 5 1 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/tty c 5 0 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/tty0 c 4 0 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/tty1 c 4 1 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/null c 1 3 2>/dev/null || true
$BUSYBOX mknod -m 666 /dev/zero c 1 5 2>/dev/null || true
$BUSYBOX mknod -m 600 /dev/kmsg c 1 11 2>/dev/null || true
$BUSYBOX mdev -s 2>/dev/null || true

log() {
    echo "gta8-init: $*" > /dev/kmsg 2>/dev/null || true
    echo "gta8-init: $*" > /dev/tty0 2>/dev/null || true
    echo "gta8-init: $*" 2>/dev/null || true
}

log "=== Kernel booted successfully! Starting initramfs ==="

# 1. Neutralize hardware watchdogs immediately
echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
for ko in /pmicwdt_off.ko /modules/pmicwdt_off.ko; do
    if [ -f "$ko" ]; then
        $BUSYBOX insmod "$ko" 2>/dev/null && log "SC2730 PMIC watchdog neutralized via $ko" && break
    fi
done

for w in /sys/class/watchdog/watchdog*; do
    [ -e "$w/dev" ] || continue
    wdev=$($BUSYBOX cat "$w/dev")
    wname=${w##*/}
    $BUSYBOX mknod -m 600 "/dev/$wname" c "${wdev%:*}" "${wdev#*:}" 2>/dev/null || true
done
$BUSYBOX mknod -m 666 /dev/watchdog c 10 130 2>/dev/null || true

# Background keepalive loop
$BUSYBOX sh -c 'trap "" HUP INT QUIT
while true; do
    for n in /dev/watchdog /dev/watchdog0 /dev/watchdog1; do
        [ -c "$n" ] && echo 1 > "$n" 2>/dev/null || true
        [ -c "$n" ] && echo V > "$n" 2>/dev/null || true
    done
    echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
    $BUSYBOX sleep 4
done' </dev/null >/dev/null 2>&1 &

# 2. Setup USB ACM gadget (optional, ignore errors)
$BUSYBOX mount -t configfs none /config 2>/dev/null || true
G=/config/usb_gadget/g1
if [ -d /config/usb_gadget ]; then
    $BUSYBOX mkdir -p "$G/strings/0x409" "$G/functions/acm.gs0" "$G/configs/b.1/strings/0x409" 2>/dev/null || true
    echo 0x1d6b > "$G/idVendor" 2>/dev/null || true
    echo 0x0104 > "$G/idProduct" 2>/dev/null || true
    echo "Galaxy Tab A8 LTE" > "$G/strings/0x409/product" 2>/dev/null || true
    $BUSYBOX ln -sfn "$G/functions/acm.gs0" "$G/configs/b.1/f1" 2>/dev/null || true
    echo musb-hdrc.0.auto > "$G/UDC" 2>/dev/null || true
fi
$BUSYBOX mknod -m 600 /dev/ttyGS0 c 509 0 2>/dev/null || true

# DRM node creation and early bootsplash
if [ -e /sys/class/drm/card0/dev ]; then
    d=$($BUSYBOX cat /sys/class/drm/card0/dev)
    $BUSYBOX mkdir -p /dev/dri
    $BUSYBOX rm -f /dev/dri/card0
    $BUSYBOX mknod -m 666 /dev/dri/card0 c "${d%:*}" "${d#*:}" 2>/dev/null || true
fi
if [ -x /opt/kmsbin/drmstep-fb2 ]; then
    /opt/kmsbin/drmstep-fb2 </dev/null >/dev/null 2>&1 &
fi

# Function to perform switch_root into Debian
do_switch() {
    log "Preparing Debian rootfs on $1..."

    # Ensure /bin/busybox and /bin/sh exist on target root!
    $BUSYBOX mkdir -p /mnt/root/bin /mnt/root/sbin /mnt/root/usr/bin /mnt/root/usr/sbin /mnt/root/opt/kmsbin
    $BUSYBOX cp -f /bin/busybox /mnt/root/bin/busybox 2>/dev/null || true
    $BUSYBOX chmod 755 /mnt/root/bin/busybox 2>/dev/null || true
    [ -e /mnt/root/bin/sh ] || $BUSYBOX ln -sf /bin/busybox /mnt/root/bin/sh 2>/dev/null || true

    # Install debian-init as /sbin/init
    $BUSYBOX cp -f /debian-init /mnt/root/sbin/init 2>/dev/null || true
    $BUSYBOX chmod 755 /mnt/root/sbin/init 2>/dev/null || true

    # Deploy tools and modules to /root
    $BUSYBOX mkdir -p /mnt/root/root /mnt/root/root/modules /mnt/root/etc/udev/rules.d /mnt/root/etc/dpkg/dpkg.cfg.d
    echo 'path-exclude=/sbin/init' > /mnt/root/etc/dpkg/dpkg.cfg.d/protect-sbin-init 2>/dev/null || true
    if [ -f /tools.tar.gz ]; then
        $BUSYBOX tar -xzf /tools.tar.gz -C /mnt/root/root/ 2>/dev/null || true
        $BUSYBOX cp -f /mnt/root/root/udev/*.rules /mnt/root/etc/udev/rules.d/ 2>/dev/null || true
        $BUSYBOX chmod +x /mnt/root/root/*.sh /mnt/root/root/*.py 2>/dev/null || true
    fi
    if [ -d /modules ]; then
        $BUSYBOX cp -rf /modules/* /mnt/root/root/modules/ 2>/dev/null || true
    fi
    if [ -d /opt/kmsbin ]; then
        $BUSYBOX cp -rf /opt/kmsbin/* /mnt/root/opt/kmsbin/ 2>/dev/null || true
    fi

    # Bind mounts
    $BUSYBOX mkdir -p /mnt/root/proc /mnt/root/sys /mnt/root/dev /mnt/root/dev/pts /mnt/root/run /mnt/root/config
    $BUSYBOX mount -o bind /proc /mnt/root/proc 2>/dev/null || true
    $BUSYBOX mount -o bind /sys /mnt/root/sys 2>/dev/null || true
    $BUSYBOX mount -o bind /dev /mnt/root/dev 2>/dev/null || true

    log "Executing switch_root to Debian..."
    exec $BUSYBOX switch_root /mnt/root /sbin/init
}

# 3. Search for MicroSD root partition
log "Scanning for MicroSD card partitions..."
for i in $($BUSYBOX seq 1 30); do
    $BUSYBOX mdev -s 2>/dev/null || true
    for p in /sys/class/block/mmcblk1p* /sys/class/block/mmcblk0p*; do
        [ -e "$p/dev" ] || continue
        pdev=$($BUSYBOX cat "$p/dev")
        pname=${p##*/}
        $BUSYBOX mknod -m 660 "/dev/$pname" b "${pdev%:*}" "${pdev#*:}" 2>/dev/null || true
    done

    # Probe mmcblk1 partitions (microSD)
    for p in /dev/mmcblk1p1 /dev/mmcblk1p2 /dev/mmcblk1p*; do
        [ -b "$p" ] || continue
        if $BUSYBOX mount -t ext4 "$p" /mnt/root 2>/dev/null || $BUSYBOX mount "$p" /mnt/root 2>/dev/null; then
            if [ -d /mnt/root/etc ] || [ -d /mnt/root/bin ] || [ -d /mnt/root/usr ]; then
                log "Found Debian on $p!"
                do_switch "$p"
            fi
            $BUSYBOX umount /mnt/root 2>/dev/null || true
        fi
    done
    $BUSYBOX sleep 1
done

log "FAIL: Could not find Debian rootfs on microSD."
log "Entering keepalive rescue loop (PID 1 will not exit)..."

# Spawns a background shell on serial ACM if connected
$BUSYBOX setsid sh -c 'while true; do
    echo "gta8lte rescue shell" > /dev/ttyGS0 2>/dev/null
    $BUSYBOX sh <>/dev/ttyGS0 >&0 2>&0
    $BUSYBOX sleep 1
done' </dev/null >/dev/null 2>&1 &

# Keep PID 1 alive FOREVER so the kernel never panics!
while true; do
    for n in /dev/watchdog /dev/watchdog0 /dev/watchdog1; do
        [ -c "$n" ] && echo 1 > "$n" 2>/dev/null || true
        [ -c "$n" ] && echo V > "$n" 2>/dev/null || true
    done
    echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
    $BUSYBOX sleep 5
done
"""

DEBIAN_INIT_SCRIPT = r"""#!/bin/busybox sh
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/opt/kmsbin
export HOME=/root
trap '' HUP INT QUIT TSTP TTIN TTOU

busybox mount -o remount,rw / 2>/dev/null || true
busybox mkdir -p /dev/pts /dev/shm /run /tmp /dev/dri /config /root/modules
busybox mount -t tmpfs -o mode=755,nosuid,nodev tmpfs /run 2>/dev/null || true
busybox mount -t tmpfs tmpfs /tmp 2>/dev/null || true
busybox mount -t devpts devpts /dev/pts 2>/dev/null || true

# Neutralize hardware watchdog
echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
for ko in /root/modules/pmicwdt_off.ko /modules/pmicwdt_off.ko /pmicwdt_off.ko; do
    if [ -f "$ko" ]; then
        busybox insmod "$ko" 2>/dev/null && break
    fi
done

# Keep watchdog timer fed in background
for w in /sys/class/watchdog/watchdog*; do
    [ -e "$w/dev" ] || continue
    wdev=$(busybox cat "$w/dev")
    wname=${w##*/}
    busybox mknod -m 600 "/dev/$wname" c "${wdev%:*}" "${wdev#*:}" 2>/dev/null || true
done
busybox mknod -m 666 /dev/watchdog c 10 130 2>/dev/null || true
busybox sh -c 'trap "" HUP INT QUIT; while true; do
    for n in /dev/watchdog /dev/watchdog0 /dev/watchdog1; do
        [ -c "$n" ] && echo 1 > "$n" 2>/dev/null || true
        [ -c "$n" ] && echo V > "$n" 2>/dev/null || true
    done
    echo "watchdog rstoff" > /proc/mdbg/at_cmd 2>/dev/null || true
    busybox sleep 4
done' </dev/null >/dev/null 2>&1 &

busybox mknod -m 600 /dev/console c 5 1 2>/dev/null || true
busybox mknod -m 666 /dev/tty0 c 4 0 2>/dev/null || true
busybox mknod -m 666 /dev/tty1 c 4 1 2>/dev/null || true
busybox mknod -m 666 /dev/null c 1 3 2>/dev/null || true
busybox mknod -m 666 /dev/zero c 1 5 2>/dev/null || true
busybox mknod -m 600 /dev/ttyGS0 c 509 0 2>/dev/null || true
busybox mount -t proc proc /proc 2>/dev/null || true
busybox mount -t sysfs sysfs /sys 2>/dev/null || true
busybox mdev -s 2>/dev/null || true

# Ensure DRM graphics node exists
if [ -e /sys/class/drm/card0/dev ]; then
    d=$(busybox cat /sys/class/drm/card0/dev)
    busybox rm -f /dev/dri/card0
    busybox mknod -m 666 /dev/dri/card0 c "${d%:*}" "${d#*:}" 2>/dev/null || true
fi

# Start drmstep bootsplash on screen (replaces frozen Samsung logo)
if ! busybox pidof drmstep-fb2 >/dev/null 2>&1; then
    for d in /opt/kmsbin/drmstep-fb2 /root/drmstep-fb2 /tmp/drmstep-fb2; do
        if [ -x "$d" ]; then
            busybox setsid "$d" >> /root/drmstep.log 2>&1 &
            break
        fi
    done
fi

# Save boot diagnostics
busybox dmesg > /root/dmesg.txt 2>/dev/null || true

# Deploy custom Wi-Fi config if present
if [ -f /root/wpa_supplicant.conf ]; then
    busybox cp -f /root/wpa_supplicant.conf /etc/wpa_supplicant.conf 2>/dev/null || true
fi

# Run hardware bringup in background
if [ -x /root/hw-up.sh ]; then
    busybox sh /root/hw-up.sh </dev/null >> /root/hw-up.log 2>&1 &
fi

# Shell on tablet screen console
busybox setsid sh -c 'trap "" HUP INT QUIT TSTP TTIN TTOU
while true; do
    echo "" > /dev/tty1 2>/dev/null
    echo "==========================================================" > /dev/tty1 2>/dev/null
    echo "  Debian 12 (bookworm) - Samsung Galaxy Tab A8 LTE (X205)  " > /dev/tty1 2>/dev/null
    echo "==========================================================" > /dev/tty1 2>/dev/null
    echo "Type commands here or connect via USB serial (ttyGS0)." > /dev/tty1 2>/dev/null
    busybox sh <>/dev/tty1 >&0 2>&0
    busybox sleep 1
done' </dev/null >/dev/null 2>&1 &

# Serial shell on USB ACM
busybox setsid sh -c 'trap "" HUP INT QUIT TSTP TTIN TTOU
while true; do
    echo "gta8lte debian prompt" > /dev/ttyGS0 2>/dev/null
    busybox sh <>/dev/ttyGS0 >&0 2>&0
    busybox sleep 1
done' </dev/null >/dev/null 2>&1 &

# Keep PID 1 running FOREVER
while true; do
    echo V > /dev/watchdog 2>/dev/null || true
    busybox sleep 5
done
"""


def main():
    if not BUSYBOX_BIN.is_file():
        raise SystemExit(f"Missing {BUSYBOX_BIN}")

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        for d in ["bin", "sbin", "dev", "proc", "sys", "mnt/root", "tmp", "config", "modules", "opt/kmsbin"]:
            (root / d).mkdir(parents=True, exist_ok=True)

        # 1. Install busybox
        bb_dest = root / "bin" / "busybox"
        shutil.copy2(BUSYBOX_BIN, bb_dest)
        bb_dest.chmod(0o755)

        # 2. Install modules
        for ko in BOOT_PACK.glob("modules/*.ko"):
            shutil.copy2(ko, root / "modules" / ko.name)
        if (BOOT_PACK / "modules" / "pmicwdt_off.ko").is_file():
            shutil.copy2(BOOT_PACK / "modules" / "pmicwdt_off.ko", root / "pmicwdt_off.ko")

        # 2b. Install bootsplash binaries if present
        for f in ["drmstep-fb2", "splash.bgra"]:
            src = BOOT_PACK / f
            if not src.is_file():
                src = TOOLS_DIR / f
            if src.is_file():
                shutil.copy2(src, root / "opt/kmsbin" / f)

        # 3. Create tools.tar.gz
        tar_path = root / "tools.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            for item in TOOLS_DIR.iterdir():
                if item.name.startswith(".") or item.name == "__pycache__":
                    continue
                tf.add(item, arcname=item.name)

        # 4. Install scripts
        init_file = root / "init"
        init_file.write_text(INIT_SCRIPT, encoding="utf-8")
        init_file.chmod(0o755)

        deb_init = root / "debian-init"
        deb_init.write_text(DEBIAN_INIT_SCRIPT, encoding="utf-8")
        deb_init.chmod(0o755)

        # 5. Pack cpio.gz
        cpio_gz_dest = BOOT_PACK / "ramdisk.cpio.gz"
        cmd = f"cd '{root}' && find . | cpio -H newc -o | gzip -9 > '{cpio_gz_dest}'"
        print(f"Creating new ramdisk at {cpio_gz_dest}...")
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"cpio failed: {res.stderr}")

        print(f"Ramdisk created successfully ({cpio_gz_dest.stat().st_size} bytes)")

    # 6. Repack boot.img and Odin tar
    print("Repacking AP-boot-only-debug-x205-v57.tar...")
    pack_script = TOOLS_DIR / "pack-x205.py"
    res = subprocess.run([sys.executable, str(pack_script)], capture_output=True, text=True)
    print(res.stdout)
    if res.returncode != 0:
        raise SystemExit(f"pack-x205.py failed: {res.stderr}")

    out_tar = BOOT_PACK / "AP-boot-only-debug-x205-v57.tar"
    print(f"[OK] Done! {out_tar} ({out_tar.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

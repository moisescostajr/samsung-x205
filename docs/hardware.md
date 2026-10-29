# Hardware notes — SM-X200 / gta8wifi

Samsung Galaxy Tab A8 Wi-Fi (SM-X200, `gta8wifi`).

- SoC: Unisoc T618 / UMS512 (`ums512_25c10`), 2× Cortex-A75 + 6× Cortex-A55, 3 GB RAM
- Display: 1200×1920 HX83102e, Himax touch, `sprd_backlight`
- Sensors (via the AON CM4 hub, `sprd-sensor`): BMI320 accel/gyro, MMC5603 mag, STK3X1X ALS. Auto-rotate and auto-brightness: `tools/sensors-up.sh` + `tools/gta8-sensors.py`. Do not write `/proc/pmic/stop` — that hard-resets the board.
- Phosh QS brightness and volume use the real GNOME Settings Daemon under systemd/logind. The old `tools/gsd-power-stub.py` remains for the manual BusyBox session only. Volume is Pulse software volume on the `sprd` pipe-sink.
- GPU: Mali-G52 MP2 (`gondul`, r34p0 kernel module from the vendor `socko` partition)
- Storage: 32 GB eMMC (`mmcblk0`), non-A/B, dynamic `super`, no `vendor_boot`
- Partitions used here: boot `p37`, recovery `p38`, dtbo `p39`, socko `p40`, vbmeta `p26`, super `p46`, userdata `p53` (FBE)
- Persistent GNU/Linux root: microSD `mmcblk1p1` ext4 `gta8root`, Debian 12 bookworm arm64 + Phosh; `mmcblk1p2` FAT32 `GTA8CFG` for Wi-Fi provisioning
- USB-C: Unisoc musb dual-role. The systemd image keeps an ACM console + NCM network link via `gta8-bringup.sh` / `tools/usb-role.sh gadget`; `tools/usb-role.sh auto` gives the port back to OTG host mode. Kernel already has `usbhid`/`xpad`/`hid-sony`.
- Wi-Fi: Unisoc WCN CP2 + `sprdwl_ng.ko` + vendor INI from `socko`
- Audio: VBC + four Awinic AW882XX smart amps
- Stock Android: One UI on Android 14, kernel 4.14.199, clang 11
- Boot image: Android boot header v2 + AVB footer, 64 MiB. MagiskBoot boot-only packing works.

## Kernel gaps on stock 4.14

Present: overlay, ext4, f2fs, loop, device-mapper, binder, USB ACM + NCM/ECM/RNDIS.

Added in the custom kernel used here: `CONFIG_PID_NS`, `CONFIG_USER_NS`,
`CONFIG_IPC_NS`, `CONFIG_DEVTMPFS`, `CONFIG_SYSVIPC`, FAT/VFAT, cgroup
controllers, seccomp, and the systemd/udev option set in
`tools/build-kernel-ci.sh`. The initramfs also works without `DEVTMPFS`.

v57 adds real DRM PRIME export, `CONFIG_VT`, the DPU plane-update fix, and the
Himax post-probe reset guard. v58 keeps that kernel and only changes the
userspace USB policy.

## Do not

Never flash a custom or empty `vbmeta`. That combination soft-bricks this board. Keep the stock `vbmeta` and sign or footer-patch boot images as the pack scripts do.

## Firmware this repo does not ship

- Samsung stock images (`boot`, `super`, `socko`, …)
- The Mali userspace blobs (`libmali` r13p0 for the compositor, r24p0 for apps)
- Vendor kernel modules (`mali_gondul.ko`, `sprdwl_ng.ko`, …)

Those stay on the device. Scripts here load them from `/mnt/socko` and `/opt/mali*`.

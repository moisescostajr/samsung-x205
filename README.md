# Linux on the Galaxy Tab A8 (SM-X200 / SM-X205)

Bring-up notes, boot-image packers, and userspace scripts for running **Debian 12 (bookworm) arm64** on a Samsung Galaxy Tab A8. Wi-Fi (`SM-X200`, `gta8wifi`) and LTE (`SM-X205`, `gta8`) share the Unisoc T618, the panel, Mali, and the Debian ramdisk. LTE needs its own `boot.img` DT table; see [docs/sm-x205.md](docs/sm-x205.md).

This is a research port, not a flashable ROM. You need an unlocked bootloader, a microSD card, and the stock firmware still on the eMMC (Mali, Wi-Fi, and the display firmware all come from there).

Hardware: [docs/hardware.md](docs/hardware.md) (X200). LTE differences: [docs/sm-x205.md](docs/sm-x205.md).

## What works today

- Debian 12 arm64 on the microSD, **systemd as PID 1**, booting directly into
  a graphical **Phosh** session (no display manager, no network install step)
- DRM/KMS on `DSI-1` (1200×1920 native, 1920×1200 after the 270° transform)
- Wi-Fi (`sprdwl_ng`), NetworkManager, Phosh Settings (with a vendor
  `wpa_supplicant` fallback if NetworkManager cannot take the radio)
- Speakers and headphones (VBC + AW882XX)
- VLC / mpv software decode, VLC volume keys remapped to playlist next/prev
- VNC with mouse and keyboard (macOS Screen Sharing talks to a small DES proxy
  in front of a grim-based backend)
- Auto-rotate (BMI320) and auto-brightness (STK3X1X) once `sensors-up.sh` has
  started the AON sensor hub
- Phosh quick-settings brightness and volume
- LTE modem stack (SM-X205: CP boot via `tools/lte-up.sh`, AT diagnostic via
  `tools/lte-at-test.py`, ModemManager integration)

The display fix is in the kernel, not just userspace: `tools/patch-display.py`
removes the SPRD DPU `active_changed` early-return and stops the Himax touch
driver from toggling the shared panel reset after probe.

## Quick start (SM-X205 / gta8 LTE)

Everything below assumes the tablet bootloader is unlocked and the stock
firmware is still on the eMMC (Mali, Wi-Fi firmware, and the panel firmware
come from there).

1. **Build the image.** Push to `main` (or run the workflow manually). GitHub
   Actions builds the kernel and the Debian + Phosh disk image, then publishes
   the rolling release `image-latest`:
   - `gta8-rootfs.img.xz.part.NN` — split disk image
   - `SHA256SUMS`, `manifest.txt`
   - `gta8-boot-pack.tar.gz` — `Image-v57`, `ramdisk.cpio.gz`, modules

2. **Write the microSD from macOS.** This downloads, verifies and decompresses
   the release on its own:

   ```sh
   sudo tools/write-sdcard.sh /dev/diskX
   ```

   Or do it in two steps (useful on a slow connection):

   ```sh
   python3 tools/fetch-image.py --boot-pack
   sudo tools/write-sdcard.sh /dev/diskX
   ```

   The card gets two partitions: `gta8root` (ext4, Debian + Phosh) and
   `GTA8CFG` (64 MiB FAT32, provisioning). Wi-Fi credentials are **not** in
   the public image.

3. **Provision Wi-Fi (optional but recommended).** The tablet reads this file
   at boot:

   ```sh
   cp tools/gta8boot/wpa_supplicant.conf.example /Volumes/GTA8CFG/wpa_supplicant.conf
   $EDITOR /Volumes/GTA8CFG/wpa_supplicant.conf
   diskutil eject /dev/diskX
   ```

   Without it, the image boots with no configured Wi-Fi; connect from Phosh
   Settings once the desktop is up.

4. **Build the Odin AP tar.** `tools/fetch-image.py --boot-pack` unpacks the
   kernel and ramdisk; `pack-x205.py` adds the stock SM-X205 DT table and AVB
   footer. Put the stock X205 `boot.img` in `stock/` (or set
   `GTA8LTE_STOCK_BOOT=/path/to/boot.img`) and run:

   ```sh
   python3 tools/repack-ramdisk.py
   ```

   Flash **only** `boot-pack/AP-boot-only-debug-x205-v58.tar` in Odin's AP
   slot. Never flash a custom or empty `vbmeta`; leave stock `vbmeta` and
   `dtbo` alone.

5. **Boot.** First boot takes one to two minutes (filesystem resize is not
   needed; systemd starts the vendor bring-up, then Phosh). Login:
   user `gta8`, password `gta8`; root password `gta8`. **Change both.** A USB
   ACM console is available on `/dev/ttyGS0` if the display ever stays black.

## What this tree is not

- Not the kernel source. The CI clones the LTE 4.14 tree, applies
  `tools/patch-prime-vt.py` and `tools/patch-display.py`, and packs the result.
- Not a supported distribution. Expect to read the scripts.
- Not Mali userspace blobs. The image uses pixman/software rendering so it can
  be published; add the vendor blobs yourself if you want GPU compositing.

**Never flash a custom or empty `vbmeta`.** That soft-bricks this board. Keep
stock `vbmeta` and pack boot images with the AVB footer the scripts already
write.

## Kernel source and binaries (not in this repo)

This tree is packers and userspace. The kernel and flashable images live elsewhere:

| What | Where |
| --- | --- |
| Samsung GPL dumps (search `SM-X200` / `SM-X205`) | [opensource.samsung.com](https://opensource.samsung.com/uploadSearch?searchValue=SM-X200) · [SM-X205](https://opensource.samsung.com/uploadSearch?searchValue=SM-X205) |
| Kernel tree used for `Image-v57` (`gta8wifi`, SM-X200) | [BasGame1/android_kernel_samsung_gta8wifi](https://github.com/BasGame1/android_kernel_samsung_gta8wifi) |
| LTE sibling tree (`gta8`, SM-X205) | [handicraftsman/kernel_samsung_gta8lte](https://github.com/handicraftsman/kernel_samsung_gta8lte) |
| DRM PRIME + `CONFIG_VT` delta on that 4.14 tree | [`tools/patch-prime-vt.py`](tools/patch-prime-vt.py) in this repo |
| `Image-v57`, ramdisk, packed `boot-*-v57.img` / `boot-*-v58.img`, Odin AP tars | The rolling release `image-latest` publishes `Image-v57` + `ramdisk.cpio.gz` in `gta8-boot-pack.tar.gz`; run `tools/repack-ramdisk.py` to add the stock X205 DT/AVB and produce the AP tar. |
| `magiskboot` (unpack/repack boot) | [topjohnwu/Magisk](https://github.com/topjohnwu/Magisk) |
| `odin4` (USB download-mode flash from Linux) | [Llucs/odin4](https://github.com/Llucs/odin4) |

Stock firmware (needed on the eMMC for Mali, Wi-Fi, and display firmware) is still Samsung’s; do not commit it here.

## Layout

| Path | What it is |
| --- | --- |
| `tools/pack-v*.py` | Boot.img packers for **SM-X200**. **v58 is current** (v57 kernel + USB-C dual-role ramdisk). |
| `tools/usb-role.sh` | USB-C role: `auto` (host/OTG for pads), `gadget` (ACM+RNDIS), `host` |
| `tools/pack-x205.py` | Same v57 kernel+ramdisk, DT taken from stock **SM-X205** boot.img |
| `tools/build-rootfs.sh` | Builds the two-partition Debian + Phosh SD image (CI, Linux arm64 chroot) |
| `tools/rootfs-configure.sh` | In-chroot setup: user, systemd units, Phosh autostart, Wi-Fi profile |
| `tools/gta8-bringup.sh` | systemd vendor bring-up: partitions, Wi-Fi, LTE, panel, sensors |
| `tools/fetch-image.py` | macOS downloader/verifier/reassembler for the release image |
| `tools/write-sdcard.sh` | macOS microSD writer with disk-safety checks |
| `tools/lte-up.sh` | LTE modem bring-up (CP boot, firmware mapping, modem_control) |
| `tools/lte-at-test.py` | Interactive AT command diagnostic tool for SIM, signal (CSQ), and network |
| `tools/patch-prime-vt.py` | Kernel patch for SPRD DRM PRIME export |
| `tools/start-phosh.sh` | Phosh session: seatd, Mali, NetworkManager, optional VNC, sensors |
| `tools/gsd-power-stub.py` | Session-bus stand-in for GSD Power.Screen; QS brightness → sysfs |
| `tools/sensors-up.sh`, `tools/gta8-sensors.py` | AON/pm_sys + BMI320/STK3X1X; auto-rotate and auto-brightness |
| `tools/gpu-up.sh`, `tools/hw-up.sh`, `tools/audio-*.sh` | GPU, Wi-Fi, audio bring-up |
| `tools/gbm-shim.c`, `tools/dmaheap/` | GBM plane-fd shim; 4.14 dma-heap backport |
| `tools/grim-vnc.py`, `tools/vnc-des-proxy.py`, `tools/gta8-inject.c` | Interactive VNC |
| `tools/dashboard/` | Sample fullscreen kiosk UI. Local URLs go in `config.php` (not committed). |
| `pi-lab/` | Optional Raspberry Pi helper image (`firstrun.sh`) for Odin / USB gadget work |

Pack scripts read and write boot images from `$GTA8_BOOT_PACK` (default `./boot-pack` at the repo root). That directory is gitignored; put your unpacked `boot-*.img` and `Image-*` there.

```sh
export GTA8_BOOT_PACK=/path/to/boot-pack
python3 tools/pack-v58.py
```

## Local configuration (keep this off GitHub)

- **Wi-Fi** lives in `/etc/wpa_supplicant.conf` on the tablet. `tools/nm-up.sh` copies that into NetworkManager. Do not commit PSKs.
- **VNC password** is `VNC_PASSWORD` or `password=` in `/root/.config/wayvnc/config`. There is no default in this tree.
- **Dashboard cameras / IPTV**: copy `tools/dashboard/config.sample.php` to `tools/dashboard/config.php`.
- **Pi lab Wi-Fi**: put `wifi-ssid.txt` and `wifi-psk.txt` next to `pi-lab/firstrun.sh` on the Pi boot partition (both are gitignored).

## VNC

wayvnc 0.5 cannot speak the classic DES password macOS Screen Sharing sends, and on this compositor it also does not produce a usable framebuffer. `start-wayvnc.sh` therefore:

1. Listens on `:5900` with `vnc-des-proxy.py` (type-2 auth)
2. Feeds a grim screenshot backend on localhost
3. Injects pointer/keyboard through `gta8-inject` (virtual pointer + virtual keyboard, with the 270° panel transform applied)

Build the injector on the tablet:

```sh
sh tools/build-inject.sh
```

## License

GPL-2.0. Out-of-tree kernel pieces (`tools/dmaheap`, `tools/agdspup`, `tools/pmicwdt`) need that. Vendored dashboard assets: Bootstrap (MIT), mpegts.js (Apache-2.0).

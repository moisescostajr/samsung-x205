# Linux on the Galaxy Tab A8 (SM-X200 / SM-X205)

Bring-up notes, boot-image packers, and userspace scripts for running **Debian 12 (bookworm) arm64** on a Samsung Galaxy Tab A8. Wi-Fi (`SM-X200`, `gta8wifi`) and LTE (`SM-X205`, `gta8`) share the Unisoc T618, the panel, Mali, and the Debian ramdisk. LTE needs its own `boot.img` DT table; see [docs/sm-x205.md](docs/sm-x205.md).

This is a research port, not a flashable ROM. You need an unlocked bootloader, a microSD card, and the stock firmware still on the eMMC (Mali, Wi-Fi, and the display firmware all come from there).

Hardware: [docs/hardware.md](docs/hardware.md) (X200). LTE differences: [docs/sm-x205.md](docs/sm-x205.md).

## What works today

- Debian on the microSD, `switch_root` from a custom ramdisk, BusyBox PID 1
- DRM/KMS on `DSI-1` (1200×1920 native, 1920×1200 after the 270° transform)
- Mali-G52 compositing in Phosh (r13p0 blob + GBM shim; apps can use r24p0 + dma-heap compat)
- Wi-Fi (`sprdwl_ng`), NetworkManager, Phosh Settings
- Speakers and headphones (VBC + AW882XX)
- VLC / mpv software decode, VLC volume keys remapped to playlist next/prev
- VNC with mouse and keyboard (macOS Screen Sharing talks to a small DES proxy in front of a grim-based backend)
- Auto-rotate (BMI320) and auto-brightness (STK3X1X) once `sensors-up.sh` has started the AON sensor hub
- Phosh quick-settings brightness (`gsd-power-stub.py` → `sprd_backlight`) and volume (Pulse `sprd` sink)
- LTE modem stack (SM-X205: CP boot via `tools/lte-up.sh`, AT diagnostic via `tools/lte-at-test.py`, ModemManager integration)

## What this tree is not

- Not the kernel source. `tools/patch-prime-vt.py` is the SPRD DRM PRIME + `CONFIG_VT` patch applied on top of Samsung's 4.14 tree.
- Not packed `boot.img` / `Image-*` binaries (gitignored; they carry stock DT and an AVB footer).
- Not Mali or other proprietary blobs.
- Not a supported distribution. Expect to read the scripts.

**Never flash a custom or empty `vbmeta`.** That soft-bricks this board. Keep stock `vbmeta` and pack boot images with the AVB footer the scripts already write.

## Kernel source and binaries (not in this repo)

This tree is packers and userspace. The kernel and flashable images live elsewhere:

| What | Where |
| --- | --- |
| Samsung GPL dumps (search `SM-X200` / `SM-X205`) | [opensource.samsung.com](https://opensource.samsung.com/uploadSearch?searchValue=SM-X200) · [SM-X205](https://opensource.samsung.com/uploadSearch?searchValue=SM-X205) |
| Kernel tree used for `Image-v57` (`gta8wifi`, SM-X200) | [BasGame1/android_kernel_samsung_gta8wifi](https://github.com/BasGame1/android_kernel_samsung_gta8wifi) |
| LTE sibling tree (`gta8`, SM-X205) | [handicraftsman/kernel_samsung_gta8lte](https://github.com/handicraftsman/kernel_samsung_gta8lte) |
| DRM PRIME + `CONFIG_VT` delta on that 4.14 tree | [`tools/patch-prime-vt.py`](tools/patch-prime-vt.py) in this repo |
| `Image-v57`, ramdisk, packed `boot-*-v57.img` / `boot-*-v58.img`, Odin AP tars | **Not published.** Build `Image` from the kernel tree, then `python3 tools/pack-v58.py` (X200) or `tools/pack-x205.py` (X205) with `$GTA8_BOOT_PACK` pointing at your output dir. |
| `magiskboot` (unpack/repack boot) | [topjohnwu/Magisk](https://github.com/topjohnwu/Magisk) |
| `odin4` (USB download-mode flash from Linux) | [Llucs/odin4](https://github.com/Llucs/odin4) |

Stock firmware (needed on the eMMC for Mali, Wi-Fi, and display firmware) is still Samsung’s; do not commit it here.

## Layout

| Path | What it is |
| --- | --- |
| `tools/pack-v*.py` | Boot.img packers for **SM-X200**. **v58 is current** (v57 kernel + USB-C dual-role ramdisk). |
| `tools/usb-role.sh` | USB-C role: `auto` (host/OTG for pads), `gadget` (ACM+RNDIS), `host` |
| `tools/pack-x205.py` | Same v57 kernel+ramdisk, DT taken from stock **SM-X205** boot.img |
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

GTA8 CFG - Wi-Fi provisioning
=============================

This small FAT partition is mounted at /mnt/gta8boot on the tablet. It is the
easiest way to give the Debian image your Wi-Fi network without rebuilding it.

1. Copy wpa_supplicant.conf.example to wpa_supplicant.conf on this volume.
2. Edit the ssid and psk lines.
3. Eject the card and boot the tablet.

At boot, gta8-hw.service reads /mnt/gta8boot/wpa_supplicant.conf, creates a
NetworkManager profile for wlan0, and connects before Phosh starts.

Notes
-----
* Keep the file named exactly wpa_supplicant.conf.
* The image never contains your Wi-Fi password; this partition does, so treat
  the SD card like a password.
* You can also connect from Phosh: Settings -> Wi-Fi.
* Do not put other files here that you need to keep: reflashing the image
  recreates this partition.

#!/bin/bash
set +e
BOOT=/boot/firmware
if [ ! -d "$BOOT" ]; then
  BOOT=/boot
fi

CURRENT_HOSTNAME=$(tr -d ' \t\n\r' </etc/hostname)
echo gta8lab >/etc/hostname
sed -i "s/127.0.1.1.*${CURRENT_HOSTNAME}/127.0.1.1\tgta8lab/g" /etc/hosts 2>/dev/null
hostnamectl set-hostname gta8lab 2>/dev/null || hostname gta8lab

install -o pi -g pi -m 700 -d /home/pi/.ssh
if [ -f "$BOOT/authorized_keys" ]; then
  install -o pi -g pi -m 600 "$BOOT/authorized_keys" /home/pi/.ssh/authorized_keys
fi
usermod -aG dialout,plugdev,sudo pi 2>/dev/null
echo 'pi ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/010-pi-nopasswd
chmod 440 /etc/sudoers.d/010-pi-nopasswd

raspi-config nonint do_ssh 0
raspi-config nonint do_wifi_country FI
rfkill unblock wifi 2>/dev/null
rfkill unblock wlan 2>/dev/null

PSK=""
SSID=""
if [ -f "$BOOT/wifi-psk.txt" ]; then
  PSK=$(tr -d '\r\n' <"$BOOT/wifi-psk.txt")
fi
if [ -f "$BOOT/wifi-ssid.txt" ]; then
  SSID=$(tr -d '\r\n' <"$BOOT/wifi-ssid.txt")
fi
if [ -n "$PSK" ] && [ -n "$SSID" ]; then
  mkdir -p /etc/NetworkManager/system-connections
  umask 077
  cat >/etc/NetworkManager/system-connections/${SSID}.nmconnection <<EOF
[connection]
id=${SSID}
uuid=$(cat /proc/sys/kernel/random/uuid)
type=wifi
interface-name=wlan0
autoconnect=true

[wifi]
mode=infrastructure
ssid=${SSID}

[wifi-security]
key-mgmt=wpa-psk
psk=${PSK}

[ipv4]
method=auto

[ipv6]
method=auto
EOF
  chmod 600 /etc/NetworkManager/system-connections/${SSID}.nmconnection
fi

cat >/etc/udev/rules.d/51-gta8.rules <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="1d6b", MODE="0666", GROUP="plugdev"
KERNEL=="ttyACM*", MODE="0666", GROUP="dialout"
EOF

mkdir -p /opt/gta8 /usr/local/sbin
if [ -f "$BOOT/debian-bookworm-arm64.tar.gz" ]; then
  cp "$BOOT/debian-bookworm-arm64.tar.gz" /opt/gta8/ || true
fi

cat >/usr/local/sbin/gta8-bootstrap <<'BOOTSTRAP'
#!/bin/bash
set -e
exec >/var/log/gta8-bootstrap.log 2>&1
if [ -f /var/lib/gta8-bootstrap.done ]; then
  exit 0
fi
export DEBIAN_FRONTEND=noninteractive
for i in $(seq 1 30); do
  ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1 && break
  sleep 2
done
apt-get update -y
apt-get install -y --no-install-recommends \
  e2fsprogs parted fdisk usbutils python3 python3-usb python3-serial \
  git cmake ninja-build g++ pkg-config libusb-1.0-0-dev libcrypto++-dev \
  screen minicom picocom avahi-daemon build-essential ca-certificates
systemctl enable --now ssh avahi-daemon || true
if [ ! -x /usr/local/bin/odin4 ]; then
  rm -rf /opt/gta8/odin4
  git clone --depth 1 https://github.com/Llucs/odin4.git /opt/gta8/odin4
  cmake -S /opt/gta8/odin4 -B /opt/gta8/odin4/build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DODIN4_BUILD_GUI=OFF -DODIN4_BUILD_TESTS=OFF
  cmake --build /opt/gta8/odin4/build --parallel "$(nproc)"
  install -m 755 /opt/gta8/odin4/build/odin4 /usr/local/bin/odin4
fi
touch /var/lib/gta8-bootstrap.done
BOOTSTRAP
chmod 755 /usr/local/sbin/gta8-bootstrap

cat >/etc/systemd/system/gta8-bootstrap.service <<'EOF'
[Unit]
Description=gta8 lab first-boot packages (odin4, e2fsprogs)
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/var/lib/gta8-bootstrap.done

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/gta8-bootstrap
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl enable gta8-bootstrap.service

cat >/usr/local/sbin/gta8-sd-info <<'EOF'
#!/bin/bash
echo "=== root ==="
findmnt -n -o SOURCE,TARGET /
echo "=== block devices ==="
lsblk -o NAME,SIZE,MODEL,TRAN,MOUNTPOINT
echo
echo "Tablet microSD in the Pi SD slot is usually /dev/mmcblk0 (NOT the USB stick)."
echo "Do not mkfs the device that is mounted on / ."
EOF
chmod 755 /usr/local/sbin/gta8-sd-info

if [ -f "$BOOT/cmdline.txt" ]; then
  sed -i 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.unit=[^ ]*||g' "$BOOT/cmdline.txt"
fi
rm -f "$BOOT/firstrun.sh" "$BOOT/wifi-psk.txt"
sync
exit 0

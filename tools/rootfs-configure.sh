#!/bin/bash
# Configure a freshly debootstrapped Debian arm64 rootfs for the Tab A8.
# Runs *inside* the chroot created by tools/build-rootfs.sh.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
# systemctl enable/set-default work without a running PID 1 in a chroot.
export SYSTEMD_OFFLINE=1

STAGE=${STAGE:-/tmp/gta8-stage}
USER_NAME=${GTA8_USER:-gta8}

log() { echo "gta8-rootfs: $*"; }

# ------------------------------------------------------------------ pseudo fs
mkdir -p /proc /sys /dev
mountpoint -q /proc || mount -t proc proc /proc 2>/dev/null || true
mountpoint -q /sys || mount -t sysfs sysfs /sys 2>/dev/null || true
[ -e /dev/null ] || mknod -m 666 /dev/null c 1 3 2>/dev/null || true
[ -e /dev/zero ] || mknod -m 666 /dev/zero c 1 5 2>/dev/null || true

# ---------------------------------------------------------------- identity
echo gta8 > /etc/hostname
cat > /etc/hosts <<'EOF'
127.0.0.1       localhost
127.0.1.1       gta8
::1             localhost ip6-localhost ip6-loopback
EOF
ln -sf /usr/share/zoneinfo/UTC /etc/localtime
echo "LANG=C.UTF-8" > /etc/default/locale
echo "C.UTF-8 UTF-8" > /etc/locale.gen
locale-gen >/dev/null 2>&1 || true

# The phosh.service shipped by Debian hard-codes User=1000.
if ! getent passwd 1000 >/dev/null; then
    groupadd -g 1000 "$USER_NAME" 2>/dev/null || true
    useradd -u 1000 -g 1000 -m -s /bin/bash "$USER_NAME"
fi
for g in video render input audio netdev plugdev dialout bluetooth; do
    groupadd -f "$g" 2>/dev/null || true
    usermod -aG "$g" "$USER_NAME" 2>/dev/null || true
done
# Convenience passwords for a device you have physical access to. Change them.
echo "root:gta8" | chpasswd
echo "$USER_NAME:gta8" | chpasswd
echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/gta8
chmod 440 /etc/sudoers.d/gta8

# ------------------------------------------------------------------ packages
# apt lists are not needed at runtime and cost ~100 MB on the card.
rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb
apt-get clean

# ------------------------------------------------------------------ stage
if [ -d "$STAGE/tools" ]; then
    cp -R "$STAGE/tools/." /root/
fi
install -d /root/modules /opt/kmsbin /opt/wifi /etc/udev/rules.d /mnt/gta8boot
if [ -d "$STAGE/modules" ]; then
    cp -f "$STAGE/modules/"*.ko /root/modules/ 2>/dev/null || true
    [ -f "$STAGE/modules/pmicwdt_off.ko" ] && \
        cp -f "$STAGE/modules/pmicwdt_off.ko" /root/ 2>/dev/null || true
fi
if [ -d "$STAGE/kmsbin" ]; then
    cp -R "$STAGE/kmsbin/." /opt/kmsbin/
fi
if [ -d /root/opt/wifi ]; then
    cp -R /root/opt/wifi/. /opt/wifi/
fi
if [ -d /root/udev ]; then
    cp -f /root/udev/*.rules /etc/udev/rules.d/ 2>/dev/null || true
fi
chmod +x /root/*.sh /root/*.py 2>/dev/null || true
install -m 755 /root/gta8-bringup.sh /usr/local/sbin/gta8-bringup.sh
# Fallback Wi-Fi path uses the udhcpc script when NetworkManager cannot drive
# the vendor interface; the initramfs also installs it, but keep the image
# self-contained.
if [ -f /root/default.script ]; then
    install -d /usr/share/udhcpc
    install -m 755 /root/default.script /usr/share/udhcpc/default.script
fi

# Wi-Fi profile, when the tree used for the build had the (gitignored) file.
if [ -f /root/wpa_supplicant.conf ] && command -v nmcli >/dev/null 2>&1; then
    ssid=$(sed -n 's/^[[:space:]]*ssid="\(.*\)"[[:space:]]*$/\1/p' /root/wpa_supplicant.conf | head -1)
    psk=$(sed -n 's/^[[:space:]]*psk="\(.*\)"[[:space:]]*$/\1/p' /root/wpa_supplicant.conf | head -1)
    if [ -n "$ssid" ]; then
        mkdir -p /etc/NetworkManager/system-connections
        f="/etc/NetworkManager/system-connections/${ssid//\//_}.nmconnection"
        {
            echo "[connection]"
            echo "id=$ssid"
            echo "uuid=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo 00000000-0000-0000-0000-000000000000)"
            echo "type=wifi"
            echo "autoconnect=true"
            echo "interface-name=wlan0"
            echo
            echo "[wifi]"
            echo "mode=infrastructure"
            echo "ssid=$ssid"
            if [ -n "$psk" ]; then
                echo
                echo "[wifi-security]"
                echo "key-mgmt=wpa-psk"
                echo "psk=$psk"
            fi
            echo
            echo "[ipv4]"
            echo "method=auto"
            echo
            echo "[ipv6]"
            echo "method=disabled"
        } > "$f"
        chmod 600 "$f"
        log "wrote NetworkManager profile for $ssid"
    fi
fi

# ------------------------------------------------------------------ services
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/gta8.conf <<'EOF'
[main]
no-auto-default=*
dns=default

[device]
wifi.scan-rand-mac-address=no

[keyfile]
unmanaged-devices=interface-name:usb0
EOF

cat > /etc/systemd/system/gta8-hw.service <<'EOF'
[Unit]
Description=GTA8 vendor hardware bring-up
After=local-fs.target systemd-udevd.service NetworkManager.service ModemManager.service
Wants=NetworkManager.service ModemManager.service
Before=phosh.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/gta8-bringup.sh
RemainAfterExit=yes
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
EOF

install -d /etc/systemd/system/phosh.service.d
cat > /etc/systemd/system/phosh.service.d/10-gta8.conf <<'EOF'
[Unit]
# The panel must be programmed before phoc opens the DRM device.
After=gta8-hw.service user@1000.service
Wants=gta8-hw.service user@1000.service

[Service]
Restart=always
RestartSec=10s
# Debian's phosh.service uses PAMName=login. Make sure the user instance and
# its session bus exist before phoc starts, even on a slow first boot.
ExecStartPre=+/bin/sh -c 'install -d -m 700 -o 1000 -g 1000 /run/user/1000'
# Wait for the user manager's D-Bus socket instead of racing it.
ExecStartPre=+/bin/sh -c 'i=0; while [ ! -S /run/user/1000/bus ] && [ "$i" -lt 50 ]; do i=$((i+1)); sleep 0.2; done; exit 0'
# phosh.service runs on tty7, but nothing switches the foreground VT when it
# is started directly by systemd instead of a display manager. Without this
# the PAM/logind session is online but not active, so libseat will not hand
# phoc the DRM device.
ExecStartPre=+/bin/sh -c '/usr/bin/chvt 7 2>/dev/null || true'
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
# No Mali userspace blobs in this image: phoc composites with pixman and
# clients are kept on software GL. Replace these if you add libmali later.
Environment=WLR_BACKENDS=drm,libinput
Environment=WLR_DRM_DEVICES=/dev/dri/card0
Environment=WLR_RENDERER=pixman
Environment=WLR_NO_HARDWARE_CURSORS=1
Environment=LIBGL_ALWAYS_SOFTWARE=1
Environment=GALLIUM_DRIVER=llvmpipe
Environment=GSK_RENDERER=cairo
Environment=GDK_BACKEND=wayland
Environment=QT_QPA_PLATFORM=wayland
Environment=MOZ_ENABLE_WAYLAND=1
Environment=WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
Environment=WEBKIT_DISABLE_COMPOSITING_MODE=1
Environment=WEBKIT_DISABLE_DMABUF_RENDERER=1
EOF

# Squeekboard has no D-Bus activation file in Debian, but gnome-session's
# phosh.session lists sm.puri.OSK0 as a required component.
cat > /usr/share/dbus-1/services/sm.puri.OSK0.service <<'EOF'
[D-BUS Service]
Name=sm.puri.OSK0
Exec=/usr/bin/squeekboard
EOF

# Phosh/phoc: rotate the portrait panel to landscape.
install -d /etc/phosh
cat > /etc/phosh/phoc.ini <<'EOF'
[output:DSI-1]
transform = 270
scale = 1
EOF

# Console on the USB ACM gadget, root shell without a password.
install -d /etc/systemd/system/serial-getty@ttyGS0.service.d
cat > /etc/systemd/system/serial-getty@ttyGS0.service.d/autologin.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
EOF
echo ttyGS0 >> /etc/securetty
echo tty1 >> /etc/securetty

# mpv: phoc/pixman can only show wl_shm buffers.
if [ -x /root/mpv-phosh ]; then
    install -m 755 /root/mpv-phosh /usr/local/bin/mpv-phosh
fi
if [ -f /root/mpv.conf ]; then
    install -d /etc/mpv
    install -m 644 /root/mpv.conf /etc/mpv/mpv.conf
fi

# zram swap: 3 GB of RAM is tight once WebKit is running.
if [ -f /etc/default/zramswap ]; then
    cat > /etc/default/zramswap <<'EOF'
ALGO=zstd
PERCENT=25
PRIORITY=100
EOF
fi

# --------------------------------------------------------------- boot config
cat > /etc/fstab <<'EOF'
# The initramfs mounts the card and switch_roots; this entry is for systemd.
LABEL=gta8root / ext4 defaults,noatime,errors=remount-ro 0 1
# Wi-Fi provisioning area, written from macOS/Windows. Optional at boot.
LABEL=GTA8CFG /mnt/gta8boot vfat defaults,noatime,nofail,umask=0022 0 0
EOF
rm -f /etc/resolv.conf
echo "nameserver 1.1.1.1" > /etc/resolv.conf
echo "nameserver 9.9.9.9" >> /etc/resolv.conf

# Leave /etc/machine-id empty: systemd generates a unique ID on first boot, so
# every tablet that gets a copy of this image does not share one machine-id.
: > /etc/machine-id
ssh-keygen -A >/dev/null 2>&1 || true

# ---------------------------------------------------------------- enabling
# This image has no display manager: graphical.target must pull phosh in and
# phosh must pull the vendor bring-up in.
systemctl set-default graphical.target
systemctl --global enable pulseaudio.socket >/dev/null 2>&1 || true
# dbus-user-session already enables its socket in /usr/lib; --global is only
# belt and braces for a changed package.
systemctl --global enable dbus.socket >/dev/null 2>&1 || true

enable_required() {
    if ! systemctl enable "$1"; then
        log "ERROR: could not enable $1"
        exit 1
    fi
}
enable_required NetworkManager.service
enable_required ModemManager.service
enable_required gta8-hw.service
enable_required phosh.service

for link in \
    /etc/systemd/system/multi-user.target.wants/gta8-hw.service \
    /etc/systemd/system/graphical.target.wants/phosh.service; do
    [ -e "$link" ] || { log "ERROR: missing enable link $link"; exit 1; }
done
systemctl enable serial-getty@ttyGS0.service >/dev/null 2>&1 || true
systemctl enable ssh.service >/dev/null 2>&1 || true
systemctl enable systemd-timesyncd.service >/dev/null 2>&1 || true
systemctl enable zramswap.service >/dev/null 2>&1 || true
systemctl disable apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
systemctl disable wpa_supplicant.service >/dev/null 2>&1 || true
systemctl disable systemd-resolved.service systemd-resolved.socket >/dev/null 2>&1 || true
systemctl mask systemd-resolved.service >/dev/null 2>&1 || true
systemctl mask systemd-firstboot.service >/dev/null 2>&1 || true
systemctl set-default graphical.target >/dev/null 2>&1 || true

# SSH is for debugging only; keep root out.
install -d /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/gta8.conf <<'EOF'
PasswordAuthentication yes
PermitRootLogin no
EOF

# ------------------------------------------------------------------- checks
# Fail the image build here instead of shipping a card that cannot start Phosh.
missing=0
for b in phosh phoc squeekboard nmcli ModemManager chvt; do
    command -v "$b" >/dev/null 2>&1 || { log "ERROR: missing binary: $b"; missing=1; }
done
for f in /etc/systemd/system/gta8-hw.service \
         /etc/systemd/system/phosh.service.d/10-gta8.conf \
         /etc/phosh/phoc.ini /usr/local/sbin/gta8-bringup.sh; do
    [ -e "$f" ] || { log "ERROR: missing file: $f"; missing=1; }
done
for s in phosh.service gta8-hw.service NetworkManager.service ModemManager.service; do
    systemctl is-enabled "$s" >/dev/null 2>&1 || {
        log "ERROR: service not enabled: $s"; missing=1; }
done
[ "$missing" = 0 ] || exit 1

log "configuration complete"

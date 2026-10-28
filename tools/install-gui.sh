#!/bin/busybox sh
# Automatically install Phosh and Wayland desktop environment once network is up
LOG=/root/install-gui.log
log() { echo "install-gui [$(busybox cut -d. -f1 /proc/uptime)s]: $*" >> "$LOG"; }

: > "$LOG"
log "Auto GUI Installer started."

# Wait up to 180s for network connectivity (Wi-Fi or LTE)
CONNECTED=0
for i in $(busybox seq 1 60); do
    if busybox ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1 || busybox ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1; then
        CONNECTED=1
        break
    fi
    busybox sleep 3
done

if [ "$CONNECTED" -eq 1 ]; then
    log "Internet connectivity established! Updating APT package cache..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update >> "$LOG" 2>&1
    log "Installing Phosh, Phoc, Squeekboard, Seatd, and NetworkManager..."
    apt-get install -y --no-install-recommends \
        phosh phoc squeekboard weston seatd dropbear NetworkManager modemmanager >> "$LOG" 2>&1
    log "Desktop packages installed successfully! Starting Phosh..."
    if [ -x /root/start-phosh.sh ]; then
        busybox sh /root/start-phosh.sh >> /root/phosh-boot.log 2>&1 &
    fi
else
    log "Notice: No internet access detected after 180s. Connect to Wi-Fi or LTE to complete desktop install."
fi

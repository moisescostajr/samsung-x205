#!/bin/bash
# Configure Wi-Fi SSID and Password for the SM-X205 tablet.
# Usage: ./tools/set-wifi.sh <SSID> <PASSWORD>
set -e

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 <SSID> <PASSWORD>"
    echo "Example: $0 'MinhaRedeWiFi' 'minhasenha123'"
    exit 1
fi

SSID="$1"
PASS="$2"
TARGET_FILE="tools/wpa_supplicant.conf"

cat > "$TARGET_FILE" << EOF
ctrl_interface=/run/wpa_supplicant
update_config=1

network={
    ssid="$SSID"
    psk="$PASS"
}
EOF

echo "[OK] Wi-Fi network '$SSID' saved to $TARGET_FILE!"
echo "This configuration will be deployed automatically to the tablet upon next boot."

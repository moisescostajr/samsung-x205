#!/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DISK="${GTA8_SD_DISK:-/dev/rdisk6s1}"
OUT="${GTA8_SD_LOGS:-$ROOT/sd-logs}"
exec > >(tee /tmp/gta8-sd-scan.log) 2>&1
set -x
echo "Scanning tablet SD for logs..."
date
diskutil unmount "${DISK#/dev/r}" 2>/dev/null || diskutil unmount "${DISK#/dev/}" || true
sudo /usr/bin/python3 "$ROOT/tools/sd_scan_strings.py" "$DISK" /tmp/gta8-sd-logs
echo SCAN_EXIT:$?
mkdir -p "$OUT"
cp -R /tmp/gta8-sd-logs/. "$OUT/" 2>/dev/null || true
echo DONE_SD_SCAN
date

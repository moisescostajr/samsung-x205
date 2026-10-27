#!/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DISK="${GTA8_SD_DISK:-/dev/rdisk6s1}"
OUT="${GTA8_SD_LOGS:-$ROOT/sd-logs}"
exec > >(tee /tmp/gta8-sd-dump.log) 2>&1
set -x
echo "Dumping tablet SD ext4 logs..."
whoami
date
diskutil unmount "${DISK#/dev/r}" 2>/dev/null || diskutil unmount "${DISK#/dev/}" || true
sudo /usr/bin/python3 "$ROOT/tools/ext4_extract_logs.py" "$DISK" /tmp/gta8-sd-logs
echo "python exit:$?"
mkdir -p "$OUT"
cp -R /tmp/gta8-sd-logs/. "$OUT/" 2>/dev/null || true
ls -la /tmp/gta8-sd-logs
echo DONE_SD_DUMP
echo
echo "You can close this window."

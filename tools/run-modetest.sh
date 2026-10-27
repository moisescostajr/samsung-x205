#!/bin/busybox sh
export LD_LIBRARY_PATH=/opt/kmsbin
exec 3<>/tmp/kms.hold
exec /opt/kmsbin/modetest -D /dev/dri/card0 -s 85:1200x1920 <&3

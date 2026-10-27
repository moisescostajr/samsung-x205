#!/bin/busybox sh
# PulseAudio -> FIFO -> feeder -> aplay, with a buffer the Unisoc driver can
# survive.
#
# VLC and friends talk to Pulse. Direct ALSA on hw:0,0 lets the client pick a
# 200+ KiB buffer; sprd_pcm then oopses in __memset_io and the watchdog resets
# the tablet. aplay here is the only process that opens the card, always with
# period 8192 / buffer 16384.
#
# sprd-pcm-feed.py sits between the FIFO and aplay because module-pipe-sink
# stops writing when idle, and the SPRD DMA then loops its ring buffer, so the
# last fragment repeats forever after a client quits.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
export HOME=/root
export XDG_RUNTIME_DIR=/run/user/0
PIPE=/run/sprd.pcm
LOG=/root/pulse-sprd.log

busybox mkdir -p /run /run/user/0/pulse /root/.config/pulse

for p in $(busybox pidof python3); do
    cmd=$(busybox tr "\0" " " < "/proc/$p/cmdline" 2>/dev/null)
    case "$cmd" in
        *sprd-pcm-feed.py*) kill "$p" 2>/dev/null ;;
    esac
done
busybox kill $(busybox pidof pulseaudio) 2>/dev/null
busybox kill $(busybox pidof aplay) 2>/dev/null
busybox rm -f "$PIPE"
busybox sleep 1

cat > /root/.config/pulse/default.pa <<'EOF'
load-module module-pipe-sink sink_name=sprd file=/run/sprd.pcm format=s16le rate=48000 channels=2 sink_properties=device.description=Speakers device.form_factor=speaker
load-module module-native-protocol-unix auth-anonymous=1
set-default-sink sprd
EOF

: > "$LOG"
busybox setsid pulseaudio --daemonize=no --exit-idle-time=-1 --disallow-exit \
    --log-target=file:"$LOG" --use-pid-file=no </dev/null >>"$LOG" 2>&1 &
i=0
while [ "$i" -lt 15 ]; do
    busybox sleep 1
    [ -p "$PIPE" ] && break
    i=$((i + 1))
done
if [ ! -p "$PIPE" ]; then
    echo "pulse pipe $PIPE missing" >&2
    busybox tail -20 "$LOG" >&2
    exit 1
fi

: > /root/aplay-sprd.log
busybox setsid busybox sh -c \
    "python3 /root/sprd-pcm-feed.py | aplay -D hw:0,0 --period-size=8192 \
     --buffer-size=16384 -f S16_LE -c 2 -r 48000 -t raw -N -" \
    </dev/null >>/root/aplay-sprd.log 2>&1 &
busybox sleep 2

if busybox pidof aplay >/dev/null && busybox pidof pulseaudio >/dev/null; then
    echo "pulse-sprd ready (aplay $(busybox pidof aplay))"
else
    echo "pulse-sprd failed" >&2
    busybox tail -20 "$LOG" >&2
    busybox tail -10 /root/aplay-sprd.log >&2
    exit 1
fi

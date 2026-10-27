#!/bin/busybox sh
# Bring the Unisoc audio DSP up and route playback.
# Default is the headphone jack: speakers stay muted unless AUDIO_OUT=spk.
# Safe to re-run.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
LOG=/root/audio-boot.log
: > "$LOG"
log() { echo "gta8-audio [$(busybox cut -d. -f1 /proc/uptime)s]: $*" >> "$LOG"; }

log START

if [ ! -c /dev/snd/pcmC0D0p ]; then
    log no_pcm
    exit 1
fi

# Hold AGCP powered. The HAL would have called agdsp_access_enable().
if ! busybox lsmod | busybox grep -q '^agdsp_up '; then
    if [ -f /opt/kmsbin/agdsp_up.ko ]; then
        insmod /opt/kmsbin/agdsp_up.ko >>"$LOG" 2>&1 && log agdsp_up_ok || log agdsp_up_fail
    elif [ -f /root/agdsp_up.ko ]; then
        insmod /root/agdsp_up.ko >>"$LOG" 2>&1 && log agdsp_up_ok || log agdsp_up_fail
    else
        log no_agdsp_up_ko
    fi
    busybox sleep 1
fi

# Stream l_agdsp into the load region and release reset. The sysfs store
# tracks ppos, so a second write in the same boot silently writes 0 bytes.
if [ ! -f /run/agdsp-fw-loaded ] && [ -x /root/agdsp-boot.py ]; then
    python3 /root/agdsp-boot.py >>"$LOG" 2>&1 && {
        busybox touch /run/agdsp-fw-loaded
        log dsp_boot_ok
    } || log dsp_boot_fail
else
    log dsp_already
fi

# Android compiled these from XML into /data; the unlock wiped that. Rebuild
# once from the vendor XML and leave the blobs where the kernel opens them.
PARAM=/data/vendor/local/media/audio_params
busybox mkdir -p "$PARAM"
if [ ! -s "$PARAM/dsp_vbc" ] && [ -x /root/vbc-profile-build.py ]; then
    for n in audio_structure dsp_vbc cvs; do
        python3 /root/vbc-profile-build.py \
            /vendor/etc/audio_params/sprd/$n.xml "$PARAM/$n" >>"$LOG" 2>&1 \
            && log "profile_$n" || log "profile_${n}_fail"
    done
fi

amixer -c 0 -q cset name='Audio Structure Profile Update' 1 2>/dev/null
amixer -c 0 -q cset name='DSP VBC Profile Update' 1 2>/dev/null
amixer -c 0 -q cset name='CVS Profile Update' 1 2>/dev/null
log profiles

# Headset jack ADC lives in the SC2730 and is dead until AON/pm_sys runs.
# Without this, jack-watch sees "unplugged" and the analog HP path stays off.
if [ "$(cat /proc/pmic/status 2>/dev/null)" != started ] && [ -x /root/pmsys-load.py ]; then
    python3 /root/pmsys-load.py >>"$LOG" 2>&1 && log pmsys_ok || log pmsys_fail
fi

# Speakers need aw_dev_*_switch. Do not enumerate the mixer for that on
# the headphone path: `amixer controls` can block in the kernel when AGCP
# is down.
if [ "${AUDIO_OUT:-hp}" = spk ]; then
    i=0
    while [ "$i" -lt 30 ]; do
        amixer -c 0 cget name='aw_dev_0_switch' >/dev/null 2>&1 && break
        busybox sleep 1
        i=$((i + 1))
    done
    log "aw_wait=${i}s"
fi

if [ -x /root/audio-up.sh ]; then
    busybox sh /root/audio-up.sh "${AUDIO_OUT:-hp}" >>"$LOG" 2>&1
    log "routed_${AUDIO_OUT:-hp}"
fi

if [ -x /root/start-pulse-sprd.sh ]; then
    busybox sh /root/start-pulse-sprd.sh >>"$LOG" 2>&1
    log pulse_sprd
fi

# Follow the headset jack: speakers when nothing is plugged in.
for p in $(busybox pidof python3); do
    cmd=$(busybox tr "\0" " " < "/proc/$p/cmdline" 2>/dev/null)
    case "$cmd" in
        *audio-jack-watch.py*) kill "$p" 2>/dev/null ;;
    esac
done
if [ -x /root/audio-jack-watch.py ]; then
    busybox setsid python3 /root/audio-jack-watch.py \
        </dev/null >>/root/audio-jack.log 2>&1 &
    log jack_watch
fi

log DONE

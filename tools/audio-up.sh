#!/bin/busybox sh
# Route AP playback (FE_ST_NORMAL_AP01) to the speakers or the headphone jack.
#
#   audio-up.sh spk   built-in speakers via the Awinic smart amps (default)
#   audio-up.sh hp    3.5 mm jack via the SC2730 codec
#
# Controls come from Samsung's /vendor/etc/audio_route.xml (be_switch,
# vbc_iis_mux and devices blocks). The VBC IIS muxes are required or playback
# starts and then stalls with hw_ptr frozen, because DAC0 is not wired to any
# IIS port. The VBC DAC gains default to 0, which is mute, not unity.
#
# The Awinic amps must have their monitor work disabled: it calls the driver's
# Qualcomm AFE/DSP path ("afe topo not ready"), which corrupts kernel slab on
# this SoC and takes the tablet down with a watchdog reset.
#
# sprd_pcm preallocates 128 KiB but advertises 233440 bytes and memsets
# whatever ALSA grants, so a larger buffer oopses (__memset_io). Keep
# period/buffer at 8192/16384.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin

OUT=${1:-spk}

set_ctl() {
    amixer -c 0 -q cset name="$1" "$2" 2>/dev/null || echo "miss: $1" >&2
}

# Digital gain sitting at 0 is mute. 63 is 0 dB on the 1.5 dB step scale.
# Do not apply the old +18 dB TV boost on a full-scale test tone — it
# blasts the speakers. Raise this only for quiet sources.
set_ctl 'VBC DAC0 DG Set' 63,63
set_ctl 'VBC DAC1 DG Set' 63,63
set_ctl 'VBC DAC0 AUD MDG Set' 4096,4096
set_ctl 'VBC DAC0 DSP MDG Set' 4096,4096
set_ctl 'VBC_DL_MUTE' 0

case "$OUT" in
hp)
    for i in 0 1 2 3; do set_ctl "aw_dev_${i}_switch" 0; done
    # The Awinic PAs keep playing unless they are powered down. Mixer
    # HIFI switches are not enough: SYS_IIS1 parked on vbc_iis0 still
    # shares the codec IIS, and aw_dev_*_switch never appears without
    # firmware. PWDN+AMPPD on SYSCTRL (0x04) mutes the chips over I2C.
    # 0x3a40 is the running speaker config; 0x3a43 sets bits 0 and 1.
    for d in 3-0034 3-0035 3-0036 3-0037; do
        echo 0 > "/sys/bus/i2c/devices/$d/monitor" 2>/dev/null
        echo 0x04 0x3a43 > "/sys/bus/i2c/devices/$d/rw" 2>/dev/null
    done
    set_ctl 'S_NORMAL_AP01_P_HIFI SWITCH' 0
    set_ctl 'S_FAST_P_HIFI SWITCH' 0
    set_ctl 'S_OFFLOAD_HIFI SWITCH' 0
    set_ctl 'S_NORMAL_AP23_P_HIFI SWITCH' 0
    set_ctl 'S_HIFI_P SWITCH' 0
    # Item 7 = audcp_iis1: a clock that is not carrying this DAC.
    # amixer rejects the name; the numeric index works.
    amixer -c 0 -q cset name='SYS_IIS1' 7 2>/dev/null || true
    set_ctl 'Speaker Function' 0
    set_ctl 'Speaker1 Function' 0
    set_ctl 'Speaker Mute' 1
    set_ctl 'Speaker2 Mute' 1

    set_ctl 'ag_iis0_ext_sel' enable
    set_ctl 'S_NORMAL_AP01_P_CODEC SWITCH' 1
    set_ctl 'S_NORMAL_AP23_P_CODEC SWITCH' 1
    set_ctl 'S_FAST_P_CODEC SWITCH' 1
    set_ctl 'S_OFFLOAD_CODEC SWITCH' 1

    # aplay is S16_LE; 24-bit IIS framing made the jack silent while the
    # same DAC was audible on the 16-bit speaker IIS. Do not poke
    # VBC_DAC0_DP_EN / IIS master here — those wait on the audio DSP
    # and hang when AGCP is down.
    set_ctl 'VBC_IIS_TX0_WD_SEL' WD_16BIT
    set_ctl 'VBC_IIS_TX1_WD_SEL' WD_16BIT
    set_ctl 'VBC_MUX_DAC0_IIS_PORT_SEL' VBC_IIS_PORT_IIS0
    set_ctl 'VBC_MUX_DAC1_IIS_PORT_SEL' VBC_IIS_PORT_IIS0
    set_ctl 'VBC_MUX_IIS0_PORT_DO_SEL' IIS_DO_VAL_DAC0
    set_ctl 'VBC_MUX_IIS2_PORT_DO_SEL' IIS_DO_VAL_DAC2
    set_ctl 'VBC_MUX_IIS3_PORT_DO_SEL' IIS_DO_VAL_DAC2

    set_ctl 'HP mix mode' 0
    set_ctl 'DAC LRCLK Select' invert
    set_ctl 'HPL EAR Sel' HPL
    set_ctl 'HPL Mixer DACLHPL Switch' 1
    set_ctl 'HPR Mixer DACRHPR Switch' 1
    set_ctl 'HPR Pin Switch' 1
    set_ctl 'HeadPhone Function' 1
    set_ctl 'HeadPhone Mute' 0
    set_ctl 'SmartAmp Boost' Bypass

    set_ctl 'DAC Gain DAC Playback Volume' 2
    # 8 = 0 dB on the -24 dB / 3 dB step scale (0 is mute).
    set_ctl 'HPL Gain HPL Playback Volume' 8
    set_ctl 'HPR Gain HPR Playback Volume' 8

    # Headset4P/FB1 = mode 19, packed as offset<<24.
    set_ctl 'Audio Structure Profile Select' $((19 << 24))
    set_ctl 'DSP VBC Profile Select' $((19 << 24))
    ;;
spk)
    for d in 3-0034 3-0035 3-0036 3-0037; do
        echo 0 > "/sys/bus/i2c/devices/$d/monitor" 2>/dev/null
    done

    set_ctl 'HeadPhone Function' 0
    set_ctl 'S_NORMAL_AP01_P_CODEC SWITCH' 0

    set_ctl 'S_NORMAL_AP01_P_HIFI SWITCH' 1
    set_ctl 'S_FAST_P_HIFI SWITCH' 1
    set_ctl 'S_OFFLOAD_HIFI SWITCH' 1

    set_ctl 'SYS_IIS1' vbc_iism0
    set_ctl 'VBC_IIS_TX0_WD_SEL' WD_16BIT
    set_ctl 'VBC_IIS_TX1_WD_SEL' WD_16BIT
    set_ctl 'VBC_IIS_MASTER_ENALBE' enable
    set_ctl 'VBC_IIS_MST_WIDTH_SET' WD_16BIT
    set_ctl 'VBC_IIS_MST_SEL_0_TYPE' VBC_MASTER_INTERNAL
    set_ctl 'VBC_MUX_DAC0_IIS_PORT_SEL' VBC_IIS_PORT_IIS0
    set_ctl 'VBC_MUX_DAC1_IIS_PORT_SEL' VBC_IIS_PORT_IIS1
    set_ctl 'VBC_MUX_IIS0_PORT_DO_SEL' IIS_DO_VAL_DAC0
    set_ctl 'VBC_MUX_IIS1_PORT_DO_SEL' IIS_DO_VAL_DAC1
    set_ctl 'VBC_MUX_IIS2_PORT_DO_SEL' IIS_DO_VAL_DAC2
    set_ctl 'VBC_MUX_IIS3_PORT_DO_SEL' IIS_DO_VAL_DAC2

    set_ctl 'VBC_MIXER0_DAC0' INTERCHANGE
    set_ctl 'VBC_MIXER0_DAC1' INTERCHANGE
    # DAC1 DSP MDG defaults to 0 (mute). IIS1 feeds the second amp pair.
    set_ctl 'VBC DAC1 DSP MDG Set' 4096,4096
    # PVDD boost: Bypass is battery voltage and sounds anemic; 5V is
    # the designed speaker rail. Protection monitor stays off.
    set_ctl 'SmartAmp Boost' 5V
    for i in 0 1 2 3; do set_ctl "aw_dev_${i}_switch" 1; done
    # PID 2113: clear HAGCE (bit 10) so the limiter stops sitting on TV levels,
    # set digital VOL to 0 dB, force the 5 V boost (Class-H never wakes on
    # quiet DVB). echo "0xREG 0xVAL" is the aw882xx rw sysfs format.
    for d in 3-0034 3-0035 3-0036 3-0037; do
        echo 0x04 0x3a40 > "/sys/bus/i2c/devices/$d/rw"
        echo 0x05 0x0000 > "/sys/bus/i2c/devices/$d/rw"
        echo 0x60 0x0f4d > "/sys/bus/i2c/devices/$d/rw"
    done

    # Handsfree/FB1 = mode 12, packed as offset<<24.
    set_ctl 'Audio Structure Profile Select' $((12 << 24))
    set_ctl 'DSP VBC Profile Select' $((12 << 24))
    ;;
*)
    echo "usage: $0 [spk|hp]" >&2
    exit 1
    ;;
esac

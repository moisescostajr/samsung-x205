#!/bin/busybox sh
# Bring up the Mali-G52 so phoc can composite on the GPU.
#
# Three pieces, none of which happen on their own here:
#  * mali_gondul.ko is an Android vendor module sitting in socko, not loaded
#    by anything in this rootfs.
#  * /dev is a plain tmpfs without devtmpfs auto-population, so the character
#    devices have to be created by hand from /sys.
#  * dma_heap_compat.ko backports the 5.6 DMA-BUF heaps that the Mali r24p0
#    userspace allocates from. The r13p0 blob phoc uses does not need it, but
#    the newer blob and its Wayland client path do.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
LOG=/root/gpu-up.log
: > "$LOG"
log() { echo "gta8-gpu [$(busybox cut -d. -f1 /proc/uptime)s]: $*" >> "$LOG"; }

log START

mknod_from_sys() {
    node=$1
    sysdev=$2
    [ -c "$node" ] && return 0
    [ -f "$sysdev" ] || return 1
    maj=$(busybox cut -d: -f1 "$sysdev")
    min=$(busybox cut -d: -f2 "$sysdev")
    busybox mkdir -p "$(dirname "$node")"
    busybox mknod "$node" c "$maj" "$min" && busybox chmod 666 "$node"
}

if ! busybox lsmod | busybox grep -q "^mali_gondul "; then
    if [ -f /mnt/socko/mali_gondul.ko ]; then
        insmod /mnt/socko/mali_gondul.ko >>"$LOG" 2>&1 && log mali_insmod_ok \
            || log mali_insmod_fail
        busybox sleep 1
    else
        log no_mali_ko
    fi
fi

mknod_from_sys /dev/mali0 /sys/class/misc/mali0/dev && log mali0_node \
    || log mali0_node_fail

if ! busybox lsmod | busybox grep -q "^dma_heap_compat "; then
    if [ -f /opt/kmsbin/dma_heap_compat.ko ]; then
        insmod /opt/kmsbin/dma_heap_compat.ko >>"$LOG" 2>&1 && log dmaheap_ok \
            || log dmaheap_fail
    fi
fi

MAJ=$(busybox awk '/dma_heap/{print $1}' /proc/devices | busybox head -1)
if [ -n "$MAJ" ] && [ ! -c /dev/dma_heap/system ]; then
    busybox mkdir -p /dev/dma_heap
    busybox mknod /dev/dma_heap/system c "$MAJ" 0 2>/dev/null
    busybox mknod /dev/dma_heap/system-uncached c "$MAJ" 1 2>/dev/null
    busybox chmod 666 /dev/dma_heap/system /dev/dma_heap/system-uncached
    log dma_heap_nodes
fi

[ -c /dev/mali0 ] && log GPU_READY || log GPU_MISSING
log DONE

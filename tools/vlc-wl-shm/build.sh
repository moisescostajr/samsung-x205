#!/bin/sh
# Build a patched libwl_shm_plugin.so on the tablet (aarch64).
set -e
dir=$(cd "$(dirname "$0")" && pwd)
cd "$dir"
wayland-scanner client-header \
    /usr/share/wayland-protocols/stable/viewporter/viewporter.xml \
    viewporter-client-protocol.h
wayland-scanner private-code \
    /usr/share/wayland-protocols/stable/viewporter/viewporter.xml \
    viewporter-protocol.c

gcc -shared -fPIC -O2 -Wall \
    -D__PLUGIN__ -D_FILE_OFFSET_BITS=64 \
    -DMODULE_STRING='"wl_shm"' \
    -I/usr/include/vlc -I/usr/include/vlc/plugins -I. \
    shm.c viewporter-protocol.c \
    -lvlccore -lwayland-client \
    -o libwl_shm_plugin.so

plug=/usr/lib/aarch64-linux-gnu/vlc/plugins/video_output
if [ ! -f "$plug/libwl_shm_plugin.so.stock" ]; then
    cp -a "$plug/libwl_shm_plugin.so" "$plug/libwl_shm_plugin.so.stock"
fi
cp -a libwl_shm_plugin.so "$plug/libwl_shm_plugin.so"
# drop stale plugin cache so VLC loads the new .so
rm -f /root/.cache/vlc/plugins* /root/.config/vlc/vlc-cache*
/usr/local/bin/vlc-root --reset-plugins-cache -I dummy --vout none vlc://quit >/dev/null 2>&1 || true
echo "installed $plug/libwl_shm_plugin.so"
ls -l "$plug/libwl_shm_plugin.so" "$plug/libwl_shm_plugin.so.stock"

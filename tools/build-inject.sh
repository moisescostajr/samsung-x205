#!/bin/sh
# Build gta8-inject on the tablet (aarch64). wlr-protocols is not packaged in
# bookworm, so the two XMLs travel with this tree.
set -e
dir=$(cd "$(dirname "$0")" && pwd)
cd "$dir"

for p in wlr-virtual-pointer-unstable-v1 virtual-keyboard-unstable-v1; do
    wayland-scanner client-header "protocols/$p.xml" "$p-client-protocol.h"
    wayland-scanner private-code "protocols/$p.xml" "$p-protocol.c"
done

gcc -O2 -Wall -Wextra -I. \
    gta8-inject.c \
    wlr-virtual-pointer-unstable-v1-protocol.c \
    virtual-keyboard-unstable-v1-protocol.c \
    -lwayland-client \
    -o gta8-inject

install -m 755 gta8-inject /usr/local/bin/gta8-inject
echo "installed /usr/local/bin/gta8-inject"

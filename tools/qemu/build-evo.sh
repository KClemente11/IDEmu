#!/bin/sh
# Build the IDEmu OMAP5 machine for iDrive 5/6 from the pinned QEMU release.
set -eu

archive=${1:?Usage: sh tools/qemu/build-evo.sh /path/to/qemu-11.1.2.tar.xz}
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
checksum=731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016
printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c -

build=$(mktemp -d)
echo "Building in $build"
tar -xf "$archive" -C "$build"
source="$build/qemu-11.1.2"
cp "$root/src/qemu/omap5-uevm.c" "$source/hw/arm/"
git -C "$source" apply "$root/src/qemu/qemu-v11.1.2-idemu.patch"

mkdir "$build/out"
cd "$build/out"
"$source/configure" --target-list=arm-softmmu --disable-download --disable-docs \
    --disable-tools --disable-guest-agent --disable-gtk --disable-sdl --disable-vnc \
    --disable-werror --disable-slirp --enable-fdt=system
ninja -j "${QEMU_BUILD_JOBS:-8}" qemu-system-arm
./qemu-system-arm -machine help | grep '^omap5-uevm '
mkdir -p "$root/bin"
install -m 755 qemu-system-arm "$root/bin/qemu-system-arm.new"
mv -f "$root/bin/qemu-system-arm.new" "$root/bin/qemu-system-arm"

#!/bin/sh
# Build the Linux helpers shipped with the WSL edition of the Windows installer.
set -eu
archive=$(realpath "${1:?Usage: sh tools/qemu/build-windows-payload.sh qemu-11.1.2.tar.xz}")
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"
sh tools/qemu/build-evo.sh "$archive"
sh src/glhost/build.sh

cic=$(mktemp -d)
trap 'rm -rf -- "$cic"' EXIT
tar -xf "$archive" -C "$cic"
export CIC_QEMU="$cic/qemu-11.1.2" CIC_BUILD="$cic/out"
mkdir "$CIC_BUILD"
(
    cd "$CIC_BUILD"
    "$CIC_QEMU/configure" --target-list=sh4-softmmu --disable-download --disable-docs \
        --disable-tools --disable-guest-agent --disable-gtk --disable-sdl --disable-vnc \
        --disable-werror --disable-slirp --enable-fdt=system
)
bash src/cic/build.sh
mkdir -p bin/lib
for soname in libfdt.so.1 libGLU.so.1 libglut.so.3.12; do
    lib=$(ldconfig -p | awk -v name="$soname" '$1 == name && !found { print $NF; found=1 }')
    test -n "$lib"
    cp -L "$lib" "bin/lib/$soname"
done
LD_LIBRARY_PATH="$root/bin/lib" bin/qemu-system-arm -machine help | grep '^omap5-uevm '
LD_LIBRARY_PATH="$root/bin/lib" bin/qemu-system-sh4 -machine help | grep '^cic '

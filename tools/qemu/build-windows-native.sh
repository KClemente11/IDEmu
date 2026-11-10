#!/usr/bin/env bash
# Run in the x64 MSYS2 UCRT64 shell. The resulting PE files use the Win32 APIs.
set -euo pipefail
[[ ${MSYSTEM:-} == UCRT64 ]] || { echo 'Run this script in MSYS2 UCRT64.' >&2; exit 1; }
archive=$(realpath "${1:?Usage: build-windows-native.sh /path/to/qemu-11.1.2.tar.xz}")
work=$(realpath -m "${2:-$HOME/idemu-qemu-win64}")
[[ "$(cygpath -am "$work")" != *' '* ]] || { echo 'QEMU needs a Windows build directory without spaces.' >&2; exit 1; }
root=$(cd "$(dirname "$0")/../.." && pwd)
dest="$root/bin/windows"
mkdir -p "$work/build" "$dest"
printf '%s  %s\n' 731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016 "$archive" | sha256sum -c -
source="$work/qemu-11.1.2"
# Skip symlinks from unused upstream ROM sources and CI container tooling.
# QEMU uses the prebuilt ROMs in pc-bios.
if [[ ! -f "$work/source-extracted" ]]; then
    tar -xf "$archive" --exclude='qemu-11.1.2/roms' --exclude='qemu-11.1.2/tests/lcitool' -C "$work"
    touch "$work/source-extracted"
fi
board="$root/src/qemu/omap5-uevm.c"
cmp -s "$board" "$source/hw/arm/omap5-uevm.c" || cp "$board" "$source/hw/arm/"
# The build-tree installation is unused by this bundle and needs symlink privileges.
if grep -Fq "meson.add_postconf_script(find_program('scripts/symlink-install-tree.py'))" "$source/meson.build"; then
    sed -i "/^meson\.add_postconf_script(find_program('scripts\/symlink-install-tree\.py'))/d" "$source/meson.build"
fi
patchfile="$root/src/qemu/qemu-v11.1.2-idemu.patch"
if ! git -C "$source" apply --reverse --check "$patchfile" 2>/dev/null; then
    git -C "$source" apply "$patchfile"
fi
cd "$work/build"
CIC_QEMU="$source" CIC_PATCH_ONLY=1 bash "$root/src/cic/build.sh"
if [[ ! -f build.ninja || ! -f meson-private/coredata.dat ]] || ! grep -q '^TARGET_DIRS=.*sh4-softmmu' config-host.mak; then
    "$source/configure" --target-list=arm-softmmu,sh4-softmmu --disable-download --disable-docs \
        --disable-tools --disable-guest-agent --disable-gtk --disable-sdl --disable-vnc \
        --disable-slirp --disable-werror --enable-fdt=system
fi
ninja -j "${QEMU_BUILD_JOBS:-8}" qemu-system-arm.exe qemu-system-sh4.exe
cp qemu-system-arm.exe qemu-system-sh4.exe "$dest/"
"$dest/qemu-system-arm.exe" -machine help | grep '^omap5-uevm '
"$dest/qemu-system-sh4.exe" -machine help | grep '^cic '
sh "$root/src/glhost/build.sh"

# Include the transitive MinGW DLL dependencies. Windows supplies the system DLLs.
cd "$dest"
declare -A staged
pending=(qemu-system-arm.exe qemu-system-sh4.exe glhost.exe)
while (("${#pending[@]}")); do
    binary=${pending[0]}
    pending=("${pending[@]:1}")
    while read -r dll; do
        if [[ -z "${staged[$dll]:-}" && -f "/ucrt64/bin/$dll" ]]; then
            cp "/ucrt64/bin/$dll" .
            pending+=("$dll")
            staged[$dll]=1
        fi
    done < <(objdump -p "$binary" | awk '/DLL Name:/ {print $3}')
done

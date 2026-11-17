#!/usr/bin/env python3
"""Cross-compile the MGU22 Linux ARM64 helpers using native LLVM (no WSL).

The sysroot contains libraries extracted from the user's firmware by build_image.py.
Host rendering is built separately; these files run inside the Linux guest.
"""
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess

SOURCE = Path(__file__).resolve().parents[2] / 'src' / 'mgu22'
GUEST_FILES = ('libcod.so.0', 'libEGL.so.1', 'libGLESv2.so.2', 'idemuinput',
               'idemuusb', 'libusb-1.0.so.0', 'libudev.so.1', 'libidemuhmi.so', 'idemuwl')


def validate_guest(directory):
    """Reject host executables and helpers for a different guest architecture."""
    for name in GUEST_FILES:
        path = Path(directory) / name
        with path.open('rb') as f:
            header = f.read(20)
        if (len(header) < 20 or header[:6] != b'\x7fELF\x02\x01'
                or struct.unpack_from('<H', header, 18)[0] != 183):
            raise ValueError(f'{path} must be a little-endian ELF64 AArch64 binary')


def compiler_path(name, env):
    value = os.environ.get(env) or shutil.which(name)
    if not value:
        raise RuntimeError(f'{name} not found. Install LLVM with the LLD linker and set {env} or add it to PATH.')
    return value


def build(sysroot, output):
    clang = compiler_path('clang', 'IDEMU_CLANG')
    # MinGW's ld.lld defaults to the PE driver; select the ELF driver explicitly.
    linker = [compiler_path('ld.lld', 'IDEMU_LLD'), '-flavor', 'gnu', '-m', 'aarch64linux']
    sysroot, output = Path(sysroot).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    libraries = [f'-L{sysroot / "lib"}', f'-L{sysroot / "usr/lib"}']
    common = ['-z', 'noexecstack', '--hash-style=gnu']

    def compile(source, obj):
        subprocess.run([clang, '-target', 'aarch64-linux-gnu', '-ffreestanding', '-fPIC', '-O2',
                        '-fno-stack-protector', '-fno-builtin-malloc', '-Wno-everything',
                        '-I', str(SOURCE), '-c', str(source), '-o', str(output / obj)], check=True)

    compile(SOURCE / 'crt.c', 'crt.o')

    def link(source, name, deps, executable=False, extra=()):
        obj = name + '.o'
        compile(SOURCE / source, obj)
        mode = (['--dynamic-linker=/lib/ld-linux-aarch64.so.1', '--unresolved-symbols=ignore-in-shared-libs',
                 str(output / 'crt.o')] if executable else ['-shared', '-soname', name])
        subprocess.run([*linker, *mode, *common, '-o', str(output / name), str(output / obj),
                        *libraries, *extra, *['-l:' + dep for dep in deps]], check=True)

    link('libcod.c', 'libcod.so.0', ['libc.so.6'])
    link('guest_egl.c', 'libEGL.so.1', ['libc.so.6', 'libwayland-client.so.0'])
    empty = output / 'empty.c'
    empty.write_text('int idemu_gles_stub;\n', encoding='ascii')
    compile(empty, 'empty.o')
    subprocess.run([*linker, '-shared', *common, '-soname', 'libGLESv2.so.2', '-o', str(output / 'libGLESv2.so.2'),
                    str(output / 'empty.o'), f'-L{output}', '-l:libEGL.so.1'], check=True)
    link('idemuinput.c', 'idemuinput', ['libc.so.6'], executable=True)
    link('idemuusb.c', 'idemuusb', ['libc.so.6', 'libdbus-1.so.3'], executable=True)
    link('usbfake/libusb_fake.c', 'libusb-1.0.so.0', ['libc.so.6'])
    link('usbfake/libudev_fake.c', 'libudev.so.1', ['libc.so.6'],
         extra=['--version-script=' + str(SOURCE / 'usbfake' / 'libudev.map')])
    link('hmihook.c', 'libidemuhmi.so', ['libc.so.6'])
    link('idemuwl.c', 'idemuwl', ['libc.so.6', 'libwayland-server.so.0', 'libivi-application.so.1',
                               'libivi-controller.so.1'], executable=True)
    link('ustk.c', 'ustk', ['libc.so.6'], executable=True)
    validate_guest(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sysroot', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.sysroot, args.output)

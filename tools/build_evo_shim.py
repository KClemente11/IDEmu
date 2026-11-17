#!/usr/bin/env python3
"""Build the Evo ARM graphics/input shim with Zig, on Windows or Linux.

Requires the user's extracted QNX libc.so.3. Generated headers are checked in;
this command changes only the requested output and temporary build directory.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(zig, libc, output, build_dir):
    source = ROOT / 'src/shim'
    build_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(build_dir / 'zig-cache'))
    # QNX libc has no SONAME: use its guest filename, not a host absolute DT_NEEDED path.
    guest_libc = build_dir / 'libc.so.3'
    if libc != guest_libc: shutil.copyfile(libc, guest_libc)
    objects = []
    for name in ('bridge', 'gles', 'egl', 'dbg', 'hook', 'hsfz', 'otf'):
        obj = build_dir / (name + '.o')
        subprocess.run([str(zig), 'cc', '-target', 'arm-freestanding-eabi', '-mcpu=cortex_a15',
                        '-mfloat-abi=soft', '-ffreestanding', '-fPIC', '-Os', '-mno-unaligned-access',
                        '-Wno-incompatible-library-redeclaration', '-Wno-builtin-requires-header',
                        '-Wno-int-conversion', '-Wno-pointer-sign', '-I', str(source),
                        '-c', str(source / (name + '.c')), '-o', str(obj)], check=True, env=env)
        if name != 'otf': objects.append(str(obj))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + '.building')
    subprocess.run([str(zig), 'ld.lld', '-shared', '-z', 'max-page-size=4096', '-z', 'common-page-size=4096',
                    '-z', 'norelro', '-z', 'noseparate-code', '--no-rosegment', '--hash-style=sysv',
                    '--no-eh-frame-hdr', '-z', 'nognustack', '-soname', 'libscreen.so.1',
                    '-o', str(temporary), *objects, '-L' + str(build_dir), '-l:libc.so.3'], check=True, env=env)
    with temporary.open('rb') as stream:
        header = stream.read(20)
    if header[:6] != b'\x7fELF\x01\x01' or header[18:20] != b'\x28\x00':
        raise RuntimeError('Expected an ELF32 ARM guest library')
    temporary.replace(output)
    trace_output = output.parent / 'libBMWOTFapi.so.3'
    trace_temp = trace_output.with_name(trace_output.name + '.building')
    subprocess.run([str(zig), 'ld.lld', '-shared', '-z', 'max-page-size=4096', '-z', 'common-page-size=4096',
                    '-z', 'norelro', '-z', 'noseparate-code', '--no-rosegment', '--hash-style=sysv',
                    '--no-eh-frame-hdr', '-z', 'nognustack', '-soname', trace_output.name,
                    '-o', str(trace_temp), str(build_dir / 'otf.o'), '-L' + str(build_dir), '-l:libc.so.3',
                    '-L' + str(output.parent), '-l:libscreen.so.1'], check=True, env=env)
    trace_temp.replace(trace_output)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zig', type=Path, default=shutil.which('zig'))
    p.add_argument('--libc', type=Path, required=True)
    p.add_argument('--output', type=Path, default=ROOT / 'idemu/shim/lib/libscreen.so.1')
    p.add_argument('--build-dir', type=Path, default=ROOT / 'scratch/evo-shim-build')
    args = p.parse_args()
    if not args.zig or not args.zig.is_file(): p.error('Pass --zig with the Zig compiler path')
    build(args.zig.resolve(), args.libc.resolve(), args.output.resolve(), args.build_dir.resolve())

#!/usr/bin/env python3
"""Monta o iDrive 8 (MGU22) a partir da PSdZData, sem alterá-la. Saída em <projeto>/mgu22 (cerca de 4 GB).
Uso: build_image.py [psdzdata] [--output-dir pasta] [--build-guest | --guest-dir pasta]
O perfil do carro é G70BEV e precisa bater com SERIES em MGU22_Coding.txt."""
import argparse, gzip, json, os, posixpath, shutil, stat, struct, subprocess, sys, tarfile, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from idemu.initramfs import validate_cpio
OUT = os.path.join(ROOT, 'mgu22')
VER, VERK = '007_034_003', '007_034_003'
sys.path.insert(0, HERE)
from ext4ls import E4
from build_guest8 import GUEST_FILES, validate_guest

def package(directory, kind, sid, version):
    base = os.path.join(directory, 'swe', kind, f'{kind}_{sid}.bin.{version}')
    for path in (base, base + '.tar'):
        if os.path.isfile(path): return path
    raise FileNotFoundError('required iDrive 8 firmware package not found: ' + base + ' (or .tar)')

def tool_cmd(script, *args):
    prefix = [sys.executable, '--run-tool'] if getattr(sys, 'frozen', False) else [sys.executable, '-I']
    return prefix + [os.path.join(HERE, script), *map(str, args)]

def simg(src, dst):
    subprocess.check_call(tool_cmd('simg2raw.py', src, dst))

def member(tarpath, name, dst):
    with tarfile.open(tarpath) as t:
        src = t.extractfile(name)
        with open(dst, 'wb') as o: shutil.copyfileobj(src, o, 1 << 20)

def ext2cpio(img, cpio, src='/', pfx=''):
    subprocess.check_call(tool_cmd('ext2cpio.py', img, cpio, src, pfx))

def grab(e, path, dst):
    # These are guest Linux paths, even when the image is built on Windows.
    path = posixpath.normpath(path)
    seen = set()
    while True:
        if path in seen:
            raise ValueError('symlink loop in firmware: ' + path)
        seen.add(path)
        inode = e.inode(e.lookup(path))
        if not stat.S_ISLNK(e.mode(inode)):
            with open(dst, 'wb') as f: f.write(e.data(inode))
            return
        path = posixpath.normpath(posixpath.join(posixpath.dirname(path), e.data(inode).decode()))

def prepare_guest(sysroot, destination, guest_dir=None, build_guest=False):
    if guest_dir:
        validate_guest(guest_dir)
        for name in GUEST_FILES:
            shutil.copy2(os.path.join(guest_dir, name), os.path.join(destination, name))
    elif build_guest:
        from build_guest8 import build
        build(sysroot, destination)
    else:
        subprocess.check_call(['zsh', os.path.join(ROOT, 'src/mgu22/build.sh'), sysroot, destination])

def main(argv=None):
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('psdzdata', nargs='?')
    parser.add_argument('--output-dir', default=os.environ.get('IDEMU_MGU8_OUT') or
                        os.path.join(os.environ.get('IDEMU_STATE_DIR') or ROOT, 'mgu22'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--guest-dir', help='precompiled Linux ARM64 helpers (no compiler required)')
    group.add_argument('--build-guest', action='store_true', help='cross-compile guest helpers with native LLVM')
    options = parser.parse_args(argv)
    if sys.platform == 'win32' and not (options.guest_dir or options.build_guest):
        parser.error('Windows image preparation requires --guest-dir or --build-guest; see docs/WINDOWS.md')
    if options.guest_dir: validate_guest(options.guest_dir)
    if options.build_guest:
        from build_guest8 import compiler_path
        compiler_path('clang', 'IDEMU_CLANG'); compiler_path('ld.lld', 'IDEMU_LLD')
    OUT = os.path.abspath(options.output_dir)
    psdz = options.psdzdata
    if not psdz:
        with open(os.path.join(os.environ.get('IDEMU_STATE_DIR') or ROOT, 'settings.json')) as f:
            psdz = json.load(f)['psdz_path']
    # Check every package before writing output or extracting gigabytes of data.
    packages = {sid: package(psdz, kind, sid, version) for kind, ids, version in
                [('swfl', ('00009ff7', '00009fc6', '00009ff9'), VER),
                 ('swfk', ('0000a6b1', '0000a6b0', '0000a6a6'), VERK)] for sid in ids}
    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='mgu22', dir=os.path.dirname(OUT))
    images = []; pending = None
    try:
        print('kernel e raiz'); f = packages['00009ff7']
        member(f, 'sa81x5-boot.img.bin.gz', tmp + '/boot.gz')
        b = gzip.open(tmp + '/boot.gz').read()
        assert b[:8] == b'ANDROID!'
        ks, ps = struct.unpack_from('<I', b, 8)[0], struct.unpack_from('<I', b, 36)[0]
        open(OUT + '/Image', 'wb').write(b[ps:ps + ks]); del b
        member(f, 'mgu22-bmw-image-mgu22-sa8155.ext4.simg.bin.gz', tmp + '/root.gz')
        simg(tmp + '/root.gz', tmp + '/root.raw'); os.unlink(tmp + '/root.gz')
        print('IVI e EXT')
        member(packages['00009fc6'], 'mgu22-ivi-sa8155.ext4.simg.bin.gz', tmp + '/ivi.gz')
        simg(tmp + '/ivi.gz', tmp + '/ivi.raw'); os.unlink(tmp + '/ivi.gz')
        member(packages['00009ff9'], 'mgu22-ext-sa8155.ext4.simg.bin.gz', tmp + '/ext.gz')
        simg(tmp + '/ext.gz', tmp + '/ext.raw'); os.unlink(tmp + '/ext.gz')
        # raiz do link das bibliotecas do guest e tabela de codificação
        sysroot = OUT + '/sysroot'; os.makedirs(sysroot + '/lib', exist_ok=True); os.makedirs(sysroot + '/usr/lib', exist_ok=True)
        r = E4(tmp + '/root.raw'); images.append(r)
        grab(r, '/lib/libc.so.6', sysroot + '/lib/libc.so.6')
        for n in ('libwayland-client.so.0', 'libwayland-server.so.0', 'libivi-application.so.1', 'libivi-controller.so.1', 'libdbus-1.so.3'):
            grab(r, '/usr/lib/' + n, sysroot + '/usr/lib/' + n)
        grab(r, '/usr/share/sysfunc/coding/cafd_mgu_02_a.bin', tmp + '/cafd.bin')
        iv = E4(tmp + '/ivi.raw'); images.append(iv)
        grab(iv, '/rootfs/usr/share/hmi/data/ro/MGU22_Coding.txt', tmp + '/coding.txt')
        gdir = OUT + '/guest'; os.makedirs(gdir, exist_ok=True)
        prepare_guest(sysroot, gdir, options.guest_dir, options.build_guest)
        subprocess.check_call(tool_cmd('gencoding.py', tmp + '/cafd.bin', tmp + '/coding.txt', gdir + '/coding.tab'))
        import gen_coding8; gen_coding8.write(gen_coding8.build(tmp + '/cafd.bin', tmp + '/coding.txt'), OUT + '/coding8.json')
        print('cpio')
        ext2cpio(tmp + '/root.raw', tmp + '/root.cpio')
        ext2cpio(tmp + '/ivi.raw', tmp + '/ivi.cpio', '/rootfs', '/opt/ivi/rootfs')
        ext2cpio(tmp + '/ext.raw', tmp + '/ext.cpio', '/rootfs', '/opt/ext/rootfs')
        for image in images: image.f.close()
        images.clear()
        for n in ('root', 'ivi', 'ext'): os.unlink(f'{tmp}/{n}.raw')
        print('dados da marca e do carro (SWFK)')
        pk = [('a6b1', 'hmi-data.bmw', 'var/begu/hmi-data/bmw'), ('a6b0', 'hmi-data.bmw-shared', 'var/begu/hmi-data/bmw-shared'),
              ('a6a6', 'hmi-vehicles.g70bev', 'var/begu/hmi-vehicles/G70BEV')]
        cps = []
        for a, b_, dst in pk:
            n = f'swfk-0000{a}.{b_}.ext4.bin.gz'
            member(packages['0000' + a], n, tmp + '/p.gz')
            with gzip.open(tmp + '/p.gz') as g, open(tmp + '/p.raw', 'wb') as o: shutil.copyfileobj(g, o, 1 << 20)
            c = f'{tmp}/{a}.cpio'; ext2cpio(tmp + '/p.raw', c, '/', dst); cps.append(c)
            os.unlink(tmp + '/p.gz'); os.unlink(tmp + '/p.raw')
        print('juntando')
        # sem compressão: run.py copia isto direto para a RAM do guest e o kernel só desempacota
        with tempfile.NamedTemporaryFile(prefix='base-', suffix='.cpio.new', dir=OUT, delete=False) as o:
            pending = o.name
            for c in [tmp + '/root.cpio', tmp + '/ivi.cpio', tmp + '/ext.cpio'] + cps:
                with open(c, 'rb') as f: shutil.copyfileobj(f, o, 1 << 20)
                os.unlink(c)
        validate_cpio(pending, expected_archives=6)
        os.replace(pending, OUT + '/base.cpio')
        pending = None
        print('pronto:', OUT)
    finally:
        for image in images: image.f.close()
        if pending:
            try: os.unlink(pending)
            except FileNotFoundError: pass
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == '__main__':
    main()

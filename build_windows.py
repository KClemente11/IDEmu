"""Build a Windows IDEmu executable with PyInstaller."""
import argparse
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parent


def require_mgu8_helpers(native, guest):
    """A native installer must not silently ship without its iDrive 8 backend."""
    executables = ('qemu-system-aarch64.exe', 'mguhost.exe')
    for name in executables:
        path = native / name
        if not path.is_file():
            raise ValueError(f'Missing {path}. Build the native helpers first.')
        with path.open('rb') as binary:
            if binary.read(2) != b'MZ': raise ValueError(f'{path} is not a Windows executable.')
    from tools.mgu.build_guest8 import validate_guest
    try: validate_guest(guest)
    except (OSError, ValueError) as error:
        raise ValueError(f'iDrive 8 guest helpers are missing or invalid: {error}') from error
    return executables


def publish_bundle(staged, target, timeout=15):
    """Windows scanners may briefly hold newly copied executables without delete sharing."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            staged.rename(target)
            return
        except PermissionError:
            if target.exists() or time.monotonic() >= deadline: raise
            time.sleep(.5)


def stage_wsl_payload(destination):
    source = ROOT / 'idemu'
    shutil.copytree(source, destination / 'idemu', ignore=shutil.ignore_patterns(
        '__pycache__', '*.pyc', 'phone', 'guest7', 'bezel*.jpg', 'nbt_*'))
    tools = destination / 'tools'
    tools.mkdir()
    shutil.copy2(ROOT / 'tools' / 'windows-wsl.sh', tools)

    bin_dir = destination / 'bin'
    bin_dir.mkdir()
    names = ['qemu-system-arm', 'glhost']
    if (ROOT / 'bin' / 'qemu-system-sh4').is_file():
        names.append('qemu-system-sh4')
        shutil.copytree(ROOT / 'tools' / 'cic', tools / 'cic',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in names:
        executable = ROOT / 'bin' / name
        try:
            with executable.open('rb') as binary:
                if binary.read(4) != b'\x7fELF':
                    raise ValueError(f'Expected a Linux executable at {executable}.')
        except FileNotFoundError:
            raise ValueError(f'Missing {executable}. Build the WSL backend first (docs/WINDOWS.md).') from None
        shutil.copy2(executable, bin_dir)
    libs = ROOT / 'bin' / 'lib'
    if libs.is_dir():
        shutil.copytree(libs, bin_dir / 'lib')


def copy_overlay(source, destination):
    """Copy the iDrive 7 overlay. A symlink (a Git checkout with symlinks enabled) is stored as its target text,
    which is how Git for Windows checks it out by default and what idemu/mgu7.py expects."""
    for path in sorted(source.rglob('*')):
        target = destination / path.relative_to(source)
        if path.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(os.readlink(path).replace('\\', '/').encode())
        elif path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('wsl', 'native-prep', 'native'), default='wsl',
                        help='package the WSL2 runtime, the native firmware builder, or the native iDrive 4/6/7/8 runtime')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().upper() not in ('AMD64', 'X86_64'):
        parser.error('Build with x64 Windows Python.')
    if importlib.util.find_spec('PyInstaller') is None:
        parser.error(f'Install the build dependency with "{sys.executable}" -m pip install pyinstaller==6.22.3')

    name = 'IDEmu-Prep' if args.backend == 'native-prep' else 'IDEmu'
    output_dir = args.output_dir.resolve()
    target = output_dir / name
    if target.exists() or target.is_symlink():
        parser.error(f'{target} already exists. Choose a new --output-dir for this build.')

    with tempfile.TemporaryDirectory(prefix='idemu-exe-') as temp_dir:
        work = Path(temp_dir)
        command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--name', name,
                   '--icon', str(ROOT / 'installer' / 'icon.ico'),
                   '--paths', str(ROOT), '--distpath', str(work / 'dist'),
                   '--workpath', str(work / 'build'), '--specpath', str(work)]
        if args.backend == 'wsl':
            payload = work / 'wsl'
            try:
                stage_wsl_payload(payload)
            except ValueError as error:
                parser.error(str(error))
            command += ['--add-data', f'{payload}:wsl']
        else:
            # Stage a clean copy so local phone credentials and reference images cannot enter the bundle.
            for folder in ('web', 'data', 'guest', 'shim'):
                assets = work / folder
                shutil.copytree(ROOT / 'idemu' / folder, assets, ignore=shutil.ignore_patterns(
                    '__pycache__', '*.pyc', 'phone', 'bezel*.jpg', 'nbt_*'))
                command += ['--add-data', f'{assets}:idemu/{folder}']
            template = ROOT / 'idemu' / 'qnxfs' / 'q6_template.img.z'
            command += ['--add-data', f'{template}:idemu/qnxfs']
            if args.backend == 'native':
                command += ['--hidden-import', 'idemu.runtime', '--hidden-import', 'idemu.cic',
                            '--hidden-import', 'idemu.qnxfs.lzo', '--hidden-import', 'tarfile']
                cic_tools = work / 'cic'
                cic_tools.mkdir()
                for name_required in ('run.py', 'bootinfo.py', 'efs.py', 'hmiinput.py', 'ifsx.py', 'mkimagefs.py', 'ffs3.py'):
                    shutil.copy2(ROOT / 'tools' / 'cic' / name_required, cic_tools)
                command += ['--add-data', f'{cic_tools}:tools/cic']
                native = ROOT / 'bin' / 'windows'
                native_executables = ('qemu-system-arm.exe', 'qemu-system-sh4.exe', 'glhost.exe')
                for name_required in native_executables:
                    exe = native / name_required
                    if not exe.is_file():
                        parser.error(f'Missing {exe}. Build the native helpers first.')
                    with exe.open('rb') as source:
                        if source.read(2) != b'MZ':
                            parser.error(f'{exe} is not a Windows executable.')
                # iDrive 7 is included when its helpers were built (tools/qemu/build-windows-native.sh).
                mgu7_executables = ('qemu-system-x86_64.exe', 'glhost7.exe')
                share = native / 'qemu-share'
                if all((native / name_required).is_file() for name_required in mgu7_executables) and (share / 'bios-256k.bin').is_file():
                    native_executables += mgu7_executables
                    command += ['--hidden-import', 'idemu.mgu7', '--hidden-import', 'idemu.coding7', '--hidden-import', 'uuid',
                                '--add-data', f'{share}:bin/windows/qemu-share']
                    mgu_tools = work / 'mgu'
                    mgu_tools.mkdir()
                    for name_required in ('har.py', 'hosttree.py', 'mkext2.py', 'patch_rse.py', 'gen_fakesvc.py', 'gen_coding7.py',
                                          'tscfix.py', 'idemu-init.sh'):
                        shutil.copy2(ROOT / 'tools' / 'mgu' / name_required, mgu_tools)
                    copy_overlay(ROOT / 'tools' / 'mgu' / 'rse_overlay', mgu_tools / 'rse_overlay')
                    guest7 = work / 'guest7'
                    shutil.copytree(ROOT / 'idemu' / 'guest7', guest7, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    command += ['--add-data', f'{mgu_tools}:tools/mgu', '--add-data', f'{guest7}:idemu/guest7']
                else:
                    print('Note: iDrive 7 is left out of this build (qemu-system-x86_64.exe, glhost7.exe or qemu-share is missing).')
                # iDrive 8 is part of every native bundle; firmware and sysroot libraries stay local.
                guest8 = ROOT / 'idemu' / 'guest8'
                if not guest8.is_dir(): guest8 = native / 'guest8'
                try: mgu8_executables = require_mgu8_helpers(native, guest8)
                except ValueError as error: parser.error(str(error))
                from tools.mgu.build_guest8 import GUEST_FILES
                native_executables += mgu8_executables
                command += ['--hidden-import', 'idemu.mgu', '--hidden-import', 'idemu.coding8',
                            '--hidden-import', 'gzip', '--hidden-import', 'tarfile']
                mgu_tools = work / 'mgu'
                mgu_tools.mkdir(exist_ok=True)
                for name_required in ('build_image.py', 'build_guest8.py', 'simg2raw.py', 'ext2cpio.py',
                                      'ext4ls.py', 'gencoding.py', 'gen_coding8.py', 'guest_boot.sh', 'virt_mgu22.dtb', 'smoke_windows8.py'):
                    shutil.copy2(ROOT / 'tools' / 'mgu' / name_required, mgu_tools)
                if not any(str(mgu_tools) + ':tools/mgu' == item for item in command):
                    command += ['--add-data', f'{mgu_tools}:tools/mgu']
                staged_guest8 = work / 'guest8'
                staged_guest8.mkdir()
                for filename in GUEST_FILES: shutil.copy2(guest8 / filename, staged_guest8)
                command += ['--add-data', f'{staged_guest8}:idemu/guest8']
                for file in sorted(native.iterdir()):
                    if file.name in native_executables or file.suffix.lower() == '.dll':
                        command += ['--add-data', f'{file}:bin/windows']
        command.append(str(ROOT / 'tools' / 'windows_exe.py'))
        subprocess.run(command, cwd=ROOT, check=True)
        bundle = work / 'dist' / name
        for file in ('LICENSE', 'NOTICE'):
            shutil.copy2(ROOT / file, bundle)
        output_dir.mkdir(parents=True, exist_ok=True)
        # Copy into the output directory so files inherit its Windows ACLs.
        # Moving directly from TemporaryDirectory keeps its private ACLs.
        publish = output_dir / f'.{name}-{uuid4().hex}'
        try:
            shutil.copytree(bundle, publish)
            publish_bundle(publish, target)
        finally:
            if publish.is_dir() and publish.resolve().parent == output_dir:
                shutil.rmtree(publish)

    print(f'Built {target / (name + ".exe")}')


if __name__ == '__main__':
    main()

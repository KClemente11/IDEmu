"""Build a Windows IDEmu executable with PyInstaller."""
import argparse
import importlib.util
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4


ROOT = Path(__file__).resolve().parent


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('wsl', 'native-prep'), default='wsl',
                        help='package the working WSL2 runtime, or the native firmware setup and builder')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().upper() not in ('AMD64', 'X86_64'):
        parser.error('Build with x64 Windows Python.')
    if importlib.util.find_spec('PyInstaller') is None:
        parser.error(f'Install the build dependency with "{sys.executable}" -m pip install pyinstaller==6.22.3')

    name = 'IDEmu' if args.backend == 'wsl' else 'IDEmu-Prep'
    output_dir = args.output_dir.resolve()
    target = output_dir / name
    if target.exists() or target.is_symlink():
        parser.error(f'{target} already exists. Choose a new --output-dir for this build.')

    with tempfile.TemporaryDirectory(prefix='idemu-exe-') as temp_dir:
        work = Path(temp_dir)
        command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--name', name,
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
            publish.rename(target)
        finally:
            if publish.is_dir() and publish.resolve().parent == output_dir:
                shutil.rmtree(publish)

    print(f'Built {target / (name + ".exe")}')


if __name__ == '__main__':
    main()

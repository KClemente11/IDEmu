"""Build the IDEmu x64 Windows installer from fresh Windows bundles."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from idemu.windows_update import ASSET, version_tuple

ROOT = Path(__file__).resolve().parent


def compiler():
    for item in (
        os.environ.get('IDEMU_ISCC'),
        shutil.which('ISCC.exe'),
        ROOT / 'dist/.installer-tools/Inno Setup 7/ISCC.exe',
        Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Inno Setup 7/ISCC.exe',
        Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe',
    ):
        if item and Path(item).is_file():
            return Path(item).resolve()
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, help='installer version, without the leading v')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist' / 'installer')
    parser.add_argument('--iscc', type=Path, help='path to the Inno Setup command-line compiler')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Build the installer on Windows.')
    try:
        version_tuple(args.version)
    except ValueError as error:
        parser.error(str(error))
    iscc = args.iscc.resolve() if args.iscc else compiler()
    if not iscc or not iscc.is_file():
        parser.error('Install Inno Setup and set IDEMU_ISCC or pass --iscc.')
    output = args.output_dir.resolve()
    if (output / ASSET).exists():
        parser.error('The destination already contains an installer. Choose a new --output-dir.')
    with tempfile.TemporaryDirectory(prefix='idemu-installer-') as temp:
        work = Path(temp)
        payload = work / 'apps'
        for backend in ('wsl', 'native-prep'):
            subprocess.run([sys.executable, str(ROOT / 'build_windows.py'), '--backend', backend,
                            '--output-dir', str(payload)], cwd=ROOT, check=True)
        (payload / 'installed-version.txt').write_text(args.version + '\n', encoding='ascii')
        subprocess.run([str(iscc), '/Qp', f'/DAppVersion={args.version}',
                        f'/DPayloadDir={payload}', f'/DOutputDir={work}',
                        str(ROOT / 'installer' / 'windows.iss')], cwd=ROOT, check=True)
        output.mkdir(parents=True, exist_ok=True)
        with (work / ASSET).open('rb') as source, (output / ASSET).open('xb') as dest:
            shutil.copyfileobj(source, dest)
    print(f'Built {output / ASSET}')


if __name__ == '__main__':
    main()

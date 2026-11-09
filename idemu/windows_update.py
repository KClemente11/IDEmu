"""Opt-in installer updates from the official IDEmu fork's GitHub Releases."""

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


REPO = 'KClemente11/IDEmu'
ASSET = 'IDEmu-Setup.exe'
LATEST = f'https://api.github.com/repos/{REPO}/releases/latest'
VERSION_RE = re.compile(r'(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}', re.ASCII)
MAX_INSTALLER_BYTES = 512 * 1024 * 1024


def version_tuple(version):
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError('Expected a version in X.Y.Z format.')
    parts = tuple(map(int, version.split('.')))
    if any(part > 65535 for part in parts):
        raise ValueError('Each version component must fit in a Windows file version.')
    return parts


class HttpsRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise ValueError('GitHub redirected the update to an insecure URL.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url, accept):
    request = urllib.request.Request(url, headers={'User-Agent': 'IDEmu Windows Updater', 'Accept': accept})
    return urllib.request.build_opener(HttpsRedirects()).open(request, timeout=25)


def update_asset(release, installed):
    """Find the exact published installer and its GitHub-computed SHA-256."""
    if release.get('draft') or release.get('prerelease'):
        return None
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise ValueError('The latest release does not use a vX.Y.Z tag.')
    version = tag[1:]
    if version_tuple(version) <= version_tuple(installed):
        return None
    expected_url = f'https://github.com/{REPO}/releases/download/{tag}/{ASSET}'
    for asset in release.get('assets', []):
        if asset.get('name') != ASSET or asset.get('state') != 'uploaded':
            continue
        size = asset.get('size')
        digest = asset.get('digest')
        if (asset.get('browser_download_url') != expected_url or type(size) is not int or
                not 0 < size <= MAX_INSTALLER_BYTES or not isinstance(digest, str) or
                not re.fullmatch(r'sha256:[a-f0-9]{64}', digest)):
            raise ValueError('The release installer lacks valid download or checksum metadata.')
        return version, expected_url, size, digest[7:]
    raise ValueError(f'Release {tag} does not publish {ASSET} yet.')


def download_installer(url, size, digest, destination):
    hasher = hashlib.sha256()
    total = 0
    with open_url(url, 'application/octet-stream') as response, destination.open('xb') as out:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > size:
                raise ValueError('The installer is larger than GitHub reported.')
            hasher.update(chunk)
            out.write(chunk)
    if total != size or hasher.hexdigest() != digest:
        raise ValueError('The installer failed its SHA-256 check.')


def dialog(message, flags=0x40):
    return ctypes.windll.user32.MessageBoxW(None, message, 'IDEmu Updates', flags | 0x10000)


def start_setup(setup):
    """Wait for this updater to exit before replacing its installed executable."""
    script = """
$ErrorActionPreference = 'Stop'
$setup = $env:IDEMU_VERIFIED_SETUP
try {
    Wait-Process -Id $env:IDEMU_UPDATER_PID -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $setup -ArgumentList '/NORESTART' -Wait -PassThru
    exit $process.ExitCode
} finally {
    Remove-Item -LiteralPath $setup -ErrorAction SilentlyContinue
    [System.IO.Directory]::Delete([System.IO.Path]::GetDirectoryName($setup))
}
"""
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    args = [str(powershell), '-NoProfile', '-NonInteractive',
            '-EncodedCommand', base64.b64encode(script.encode('utf-16le')).decode('ascii')]
    subprocess.Popen(args, env=dict(os.environ, IDEMU_VERIFIED_SETUP=str(setup), IDEMU_UPDATER_PID=str(os.getpid())),
                     creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    """Run independently of the GUI server; only install after the user agrees."""
    try:
        version_file = Path(sys.executable).with_name('installed-version.txt')
        if not version_file.is_file():
            raise ValueError('Install IDEmu using IDEmu-Setup.exe to use the updater.')
        installed = version_file.read_text(encoding='ascii').strip()
        version_tuple(installed)
        try:
            with open_url(LATEST, 'application/vnd.github+json') as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError('GitHub returned too much release metadata.')
                asset = update_asset(json.loads(raw), installed)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            dialog(f'No release is published on {REPO} yet. Installed version: {installed}.')
            return 0
        if asset is None:
            dialog(f'No newer stable release is available. Installed version: {installed}.')
            return 0
        version, url, size, digest = asset
        if dialog(f'IDEmu {version} is available (installed: {installed}).\n\n'
                  'Close any running emulator session before continuing. Download and run Setup?',
                  0x24 | 0x100) != 6:
            return 0
        print(f'Downloading and verifying IDEmu {version}…', flush=True)
        tmp = tempfile.mkdtemp(prefix='idemu-update-')
        try:
            setup = Path(tmp) / ASSET
            download_installer(url, size, digest, setup)
            start_setup(setup)
        except Exception:
            shutil.rmtree(tmp)
            raise
        return 0
    except (OSError, ValueError) as error:
        dialog(f'Could not update IDEmu.\n\n{error}', 0x30)
        return 1

"""Entry point for the frozen Windows builds."""
import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys


def run_wsl(root, argv):
    parser = argparse.ArgumentParser(description='Run IDEmu using Ubuntu WSL2 and WSLg.')
    parser.add_argument('--distro', default='Ubuntu', help='WSL2 distribution name')
    parser.add_argument('--port', type=int, metavar='1024-65535', default=8765)
    parser.add_argument('--no-browser', action='store_true')
    options = parser.parse_args(argv)
    if not 1024 <= options.port <= 65535:
        parser.error('--port must be between 1024 and 65535')
    command = ['wsl.exe', '--distribution', options.distro, '--cd', str(root), '--exec',
               'sh', 'tools/windows-wsl.sh', '--port', str(options.port)]
    if options.no_browser:
        command.append('--no-browser')
    try:
        return subprocess.call(command)
    except FileNotFoundError:
        print('This IDEmu build requires Windows Subsystem for Linux (WSL2) and Ubuntu.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def run_tool(script, argv):
    """Run one of the bundled tools/mgu scripts in this process. The frozen app has no python.exe to start them with."""
    import runpy
    tools = (Path(__file__).resolve().parent / 'tools').resolve()
    script = Path(script).resolve()
    if tools not in script.parents or script.suffix != '.py':
        print('Not a bundled IDEmu tool: %s' % script, file=sys.stderr)
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    sys.argv = [str(script), *argv]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name='__main__')
    return 0


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == '--run-tool':
        return run_tool(sys.argv[2], sys.argv[3:])
    if sys.argv[1:] == ['--check-update']:
        from idemu.windows_update import ASSET, NATIVE_ASSET, main as update
        native = (Path(__file__).resolve().parent / 'bin' / 'windows' / 'glhost.exe').is_file()
        return update(NATIVE_ASSET if native else ASSET)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    mutex = kernel.CreateMutexW(None, False, 'IDEmu.Windows.App')
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return run_app()
    finally:
        kernel.CloseHandle(mutex)


def run_app():
    payload = Path(__file__).resolve().parent / 'wsl'
    if payload.is_dir():
        return run_wsl(payload, sys.argv[1:])

    local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    os.environ.setdefault('IDEMU_STATE_DIR', str(local / 'IDEmu'))
    from idemu.__main__ import main as run_idemu

    args = sys.argv[1:]
    if not args or args[0] in ('--port', '--no-browser'):
        args = ['gui', *args]
    return run_idemu(args)


if __name__ == '__main__':
    sys.exit(main())

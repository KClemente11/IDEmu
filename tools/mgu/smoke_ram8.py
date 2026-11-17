"""Verify that native QEMU and Python see the same MGU22 RAM mapping."""
import argparse
import json
import mmap
from pathlib import Path
import socket
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


def run(output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    name = 'Local\\IDEmu-RAM-smoke-' + uuid.uuid4().hex
    qemu = ROOT / 'bin/windows/qemu-system-aarch64.exe'
    payload = bytes(range(256))
    image = output / 'loader.bin'; image.write_bytes(payload)
    saved = output / 'readback.bin'
    memory = mmap.mmap(-1, 64 << 20, tagname=name)
    process = connection = None
    try:
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
        with (output / 'qemu.log').open('wb') as log:
            process = subprocess.Popen([str(qemu), '-M', 'virt,memory-backend=m0', '-accel', 'tcg',
                                        '-cpu', 'cortex-a76', '-m', '64', '-S', '-display', 'none', '-serial', 'none',
                                        '-monitor', 'none', '-nic', 'none', '-object', f'memory-backend-idemu,id=m0,size=64M,mapping-name={name},share=on',
                                        '-device', f'loader,file={image},addr=0x40200000,force-raw=on',
                                        '-qmp', f'tcp:127.0.0.1:{port},server=on,wait=off'],
                                       stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 30
        while connection is None:
            if process.poll() is not None: raise RuntimeError('QEMU exited; see qemu.log')
            if time.monotonic() > deadline: raise TimeoutError('QMP did not start')
            try: connection = socket.create_connection(('127.0.0.1', port), timeout=1)
            except OSError: time.sleep(.1)
        connection.settimeout(10)
        with connection.makefile('rb') as stream:
            json.loads(stream.readline())

            def command(name, arguments=None):
                connection.sendall((json.dumps({'execute': name, 'arguments': arguments or {}}) + '\n').encode())
                while True:
                    reply = json.loads(stream.readline())
                    if 'error' in reply: raise RuntimeError(reply['error'])
                    if 'return' in reply: return reply['return']

            command('qmp_capabilities')
            if memory[0x200000:0x200100] != payload: raise AssertionError('QEMU loader writes are absent from Python mapping')
            memory[0x300000:0x300100] = payload[::-1]
            command('pmemsave', {'val': 0x40300000, 'size': 256, 'filename': str(saved)})
            if saved.read_bytes() != payload[::-1]: raise AssertionError('Python mapping writes are absent from QEMU RAM')
            command('quit')
        process.wait(10)
        print('PASS: QEMU loader -> Python RAM and Python RAM -> QEMU physical-memory readback')
    finally:
        if connection: connection.close()
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        memory.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'scratch/mgu8-ram-smoke'))
    args = parser.parse_args()
    run(args.output)

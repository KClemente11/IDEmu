"""Exercise the real Windows MGU22 renderer using a synthetic guest channel.

No firmware or QEMU needed. Creates a GLES context, clears a pbuffer, and checks
the renderer's published RGB pixels. Requires Windows and x64 ANGLE DLLs.
"""
import argparse
import mmap
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


def run(angle, output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    name = 'Local\\IDEmu-MGU8-smoke-' + uuid.uuid4().hex
    memory = mmap.mmap(-1, 96 << 20, tagname=name)
    port_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    port_socket.bind(('127.0.0.1', 0)); port = port_socket.getsockname()[1]; port_socket.close()
    process = None
    try:
        # Same wire layout as chan.h. Six PFN table pages followed by the A/B rings.
        a, b = 7 * 4096, 7 * 4096 + (16 << 20)
        struct.pack_into('<IIIIQIII', memory, 16, 1, 4096, 2048, 6, 0x123456789abcdef0, os.getpid(), 1, 0)
        struct.pack_into('<6I', memory, 52, *[(0x40000000 >> 12) + i for i in range(1, 7)])
        struct.pack_into('<6144I', memory, 4096, *[(0x40000000 >> 12) + i for i in range(7, 6151)])
        memory[:16] = b'IDEMU-MGU-CHAN-1'
        # Independent daemon channels for touch and controller/vehicle state.
        for role, offset in ((1, 32 << 20), (2, 64 << 20)):
            struct.pack_into('<IIIIQIII', memory, offset + 16, 1, 4096, 2048, 6, role, os.getpid(), role + 1, role)
            base_pfn = (0x40000000 + offset) >> 12
            struct.pack_into('<6I', memory, offset + 52, *[base_pfn + i for i in range(1, 7)])
            struct.pack_into('<6144I', memory, offset + 4096, *[base_pfn + i for i in range(7, 6151)])
            memory[offset:offset + 16] = b'IDEMU-MGU-CHAN-1'
        invalid = 95 << 20
        struct.pack_into('<IIIIQIII', memory, invalid + 16, 1, 4096, 2048, 6, 99, 1, 1, 0)
        struct.pack_into('<6I', memory, invalid + 52, *([0xffffffff] * 6))
        memory[invalid:invalid + 16] = b'IDEMU-MGU-CHAN-1'
        ops = {name: int(value) for name, value in re.findall(r'OP_(\w+) = (\d+)', (ROOT / 'src/mgu22/gen_ops.h').read_text())}
        awr = brd = 0

        def send(op, args=(), payload=b''):
            nonlocal awr
            data = struct.pack('<II', ops[op], len(args)) + struct.pack('<' + 'Q' * len(args), *args) + payload
            memory[a + awr:a + awr + len(data)] = data; awr += len(data)
            struct.pack_into('<Q', memory, 320, awr)

        def read(count):
            nonlocal brd
            deadline = time.monotonic() + 30
            while struct.unpack_from('<Q', memory, 448)[0] - brd < count:
                if process.poll() is not None: raise RuntimeError('renderer exited; see renderer.log')
                if time.monotonic() > deadline: raise TimeoutError('renderer response timed out; see renderer.log')
                time.sleep(.01)
            data = memory[b + brd:b + brd + count]; brd += count
            struct.pack_into('<Q', memory, 512, brd)
            return data

        def scalar(): return struct.unpack('<Q', read(8))[0]

        with (output / 'renderer.log').open('wb') as log:
            process = subprocess.Popen([str(ROOT / 'bin/windows/mguhost.exe'), name, '96', str(output),
                                        str(Path(angle).resolve()), str(port)], stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        attrs = [0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3033, 1, 0x3040, 0x40]
        send('EGLChooseConfig', [len(attrs), 1], struct.pack('<' + 'i' * len(attrs), *attrs))
        if not scalar(): raise RuntimeError('No GLES3 pbuffer config')
        config = scalar()
        send('EGLCreateContext', [config, 0, 2], struct.pack('<ii', 0x3098, 3))
        context = scalar()
        if not context: raise RuntimeError('GLES3 context creation failed')
        send('EGLCreateSurface', [1, config, 64, 32])
        if not scalar(): raise RuntimeError('pbuffer creation failed')
        send('EGLMakeCurrent', [1, 1, context])
        if not scalar(): raise RuntimeError('MakeCurrent failed')
        send('CreateProgram')
        program = scalar()
        if not program: raise RuntimeError('Generated GLES reply lost its 64-bit wire value')
        send('EGLCreateContext', [config, context, 2], struct.pack('<ii', 0x3098, 3))
        shared = scalar()
        if not shared: raise RuntimeError('Shared context creation failed')
        send('EGLMakeCurrent', [1, 1, shared])
        if not scalar(): raise RuntimeError('Shared context MakeCurrent failed')
        send('GetProgramiv', [program, 0x8b80])
        read(4)
        send('GetError')
        if scalar(): raise RuntimeError('Program is not visible in shared context')
        send('DeleteProgram', [program])
        floats = [struct.unpack('<I', struct.pack('<f', f))[0] for f in (.25, .5, .75, 1)]
        send('ClearColor', floats); send('Clear', [0x4000]); send('EGLSwap', [1])
        if not scalar(): raise RuntimeError('Swap failed')
        frame = (output / 'frame.rgb').read_bytes()
        magic, seq, width, height = struct.unpack_from('<4sIII', frame)
        if (magic, width, height) != (b'IDFR', 64, 32) or not seq: raise AssertionError('Invalid frame header')
        pixel = frame[32:35]
        if any(abs(x - y) > 1 for x, y in zip(pixel, (64, 128, 191))):
            raise AssertionError(f'Unexpected rendered RGB: {tuple(pixel)}')
        if frame[32:] != pixel * (64 * 32): raise AssertionError('Frame is not uniformly cleared')
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(b'd 12 34', ('127.0.0.1', port))
            sender.sendto(b'r 2', ('127.0.0.1', port))
        for offset, expected in ((32 << 20, b'd 12 34\n'), (64 << 20, b'r 2\n')):
            deadline = time.monotonic() + 10
            while struct.unpack_from('<Q', memory, offset + 448)[0] < len(expected):
                if time.monotonic() > deadline: raise TimeoutError('UDP input did not reach daemon channel')
                time.sleep(.01)
            start = offset + 7 * 4096 + (16 << 20)
            if memory[start:start + len(expected)] != expected: raise AssertionError('Incorrect input routing')
        print(f'PASS: GLES3 and shared contexts, 64-bit replies, RGB {tuple(pixel)}, UDP touch/controller routing; {output}')
    finally:
        if process is not None:
            process.terminate()
            try: process.wait(5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        memory.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('angle')
    parser.add_argument('--output', default=str(ROOT / 'scratch/mgu8-host-smoke'))
    args = parser.parse_args()
    run(args.angle, args.output)

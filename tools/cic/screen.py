#!/usr/bin/env python3
"""Captura a tela do emulador (monitor screendump) e grava um PNG: screen.py [saida.png]"""
import os, socket, struct, sys, time, zlib
D = os.environ.get('CIC_DIR', '/tmp/cic')
out = sys.argv[1] if len(sys.argv) > 1 else D + '/screen.png'
s = socket.socket(socket.AF_UNIX); s.connect(D + '/mon.sock'); s.settimeout(1)
ppm = D + '/screen.ppm'
if os.path.exists(ppm):
    os.remove(ppm)
s.sendall(('screendump %s\n' % ppm).encode()); time.sleep(2.5)
d = open(ppm, 'rb').read()
parts = d.split(b'\n', 3)
w, h = map(int, parts[1].split()); px = parts[3]
def chunk(t, dd):
    c = struct.pack('>I', len(dd)) + t + dd
    return c + struct.pack('>I', zlib.crc32(t + dd) & 0xffffffff)
raw = b''.join(b'\0' + px[y * w * 3:(y + 1) * w * 3] for y in range(h))
open(out, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
nz = sum(1 for b in px[::997] if b)
print('ok', out, w, h, 'amostras não-zero:', nz)

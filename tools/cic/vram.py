#!/usr/bin/env python3
"""Salva a memória de vídeo do Carmine (BAR2 em 0xd8000000) pelo monitor do QEMU e converte em PNG.
uso: vram.py SAÍDA.png [offset=0x0 [largura=1280 [altura=480 [formato=argb8888]]]]"""
import socket, struct, sys, time, zlib, os

D = os.environ.get('CIC_DIR', '/tmp/cic')


def mon(cmd, wait=2.0):
    s = socket.socket(socket.AF_UNIX)
    s.connect(D + '/mon.sock')
    s.settimeout(1)
    s.sendall((cmd + '\n').encode())
    time.sleep(wait)
    try:
        s.recv(65536)
    except Exception:
        pass
    s.close()


def png(path, w, h, rgb):
    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    raw = b''.join(b'\0' + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                           chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def main():
    out = sys.argv[1]
    off = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 1280
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 480
    fmt = sys.argv[5] if len(sys.argv) > 5 else 'argb8888'
    bpp = 4 if '8888' in fmt else 2
    n = w * h * bpp
    tmp = D + '/vram.bin'
    if os.path.exists(tmp):
        os.remove(tmp)
    mon('pmemsave 0x%x %d "%s"' % (0xd8000000 + off, n, tmp), 3.0)
    d = open(tmp, 'rb').read()
    rgb = bytearray(w * h * 3)
    if bpp == 4:
        for i in range(w * h):
            v = struct.unpack_from('<I', d, i * 4)[0]
            rgb[i * 3] = (v >> 16) & 255
            rgb[i * 3 + 1] = (v >> 8) & 255
            rgb[i * 3 + 2] = v & 255
    else:
        for i in range(w * h):
            v = struct.unpack_from('<H', d, i * 2)[0]
            rgb[i * 3] = ((v >> 11) & 31) * 255 // 31
            rgb[i * 3 + 1] = ((v >> 5) & 63) * 255 // 63
            rgb[i * 3 + 2] = (v & 31) * 255 // 31
    png(out, w, h, bytes(rgb))
    nz = sum(1 for b in d[::4096] if b)
    print('ok', out, 'bytes não-zero amostrados:', nz)


main()

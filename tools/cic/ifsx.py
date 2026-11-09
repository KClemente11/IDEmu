#!/usr/bin/env python3
"""Extrator de IFS QNX 6.3 (CIC / SH4) — iDrive 4.
uso: ifsx.py pacote.bin [destino]   (imprime a árvore; com destino, extrai)"""
import struct, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from idemu.qnxfs import lzo

HFMT = '<IHBBHHIIIIIIIII'

def load(path):
    d = open(path, 'rb').read(0x1000000 if os.path.getsize(path) > 0x2000000 else None)
    return d

def parse_header(d):
    v = struct.unpack_from(HFMT, d, 0)
    return dict(zip('sig ver f1 f2 hs mach sva pb ip rp rs ss sts ims pre'.split(), v))

def decompress(d, h):
    ct = (h['f1'] & 0x1c) >> 2
    p = h['ss']; end = h['sts']
    if ct == 0:
        return d[p:end]
    assert ct == 2, 'compressão %d' % ct
    img = bytearray()
    while p + 2 <= end:
        ln = (d[p] << 8) | d[p + 1]; p += 2
        if ln == 0: break
        o, ip = lzo.lzo1x_decompress(bytes(d[p:p + ln]) + b'\x11\x00\x00'); p += ln
        img += o
    return bytes(img)

def walk(img):
    hd, do = struct.unpack_from('<II', img, 12)
    p = do
    while p < hd:
        sz, xo, ino, mode, gid, uid, mt = struct.unpack_from('<HHIIIII', img, p)
        if sz == 0: break
        t = mode & 0o170000
        body = img[p + 24:p + sz]
        if t == 0o100000:
            off, fs = struct.unpack_from('<II', body, 0)
            yield 'F', body[8:].split(b'\0')[0].decode('latin1'), mode, off, fs
        elif t == 0o120000:
            so, ss = struct.unpack_from('<HH', body, 0)
            nm = body[4:].split(b'\0')[0].decode('latin1')
            tg = body[4 + len(nm) + 1:].split(b'\0')[0].decode('latin1')
            yield 'L', nm, mode, tg, 0
        elif t == 0o040000:
            yield 'D', body.split(b'\0')[0].decode('latin1'), mode, 0, 0
        else:
            yield '?', body[:32].hex(), mode, 0, 0
        p += (sz + 3) & ~3

if __name__ == '__main__':
    d = load(sys.argv[1]); h = parse_header(d)
    print({k: hex(v) for k, v in h.items()})
    img = decompress(d, h)
    print('imagefs', len(img), img[:16])
    out = sys.argv[2] if len(sys.argv) > 2 else None
    if out: os.makedirs(out, exist_ok=True)
    for t, nm, mode, a, b in walk(img):
        print(t, oct(mode & 0o7777), nm, (a if t == 'L' else b))
        if out and t == 'F':
            dst = os.path.join(out, os.path.normpath('/' + nm).lstrip('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'wb').write(img[a:a + b])
        elif out and t == 'L':
            open(os.path.join(out, '_symlinks.txt'), 'a').write('%s -> %s\n' % (nm, a))
    if out:
        open(os.path.join(out, '_imagefs.bin'), 'wb').write(img)

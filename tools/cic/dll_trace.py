#!/usr/bin/env python3
"""Acha onde o io-display carregou um DLL (dlopen) e rastreia pontos do DLL com o gdbstub.
Pré-requisito: QEMU com CIC_XARGS="-gdb tcp:127.0.0.1:1234".
uso: dll_trace.py DLL_LOCAL SUBSTRING_DO_NOME OFFSET:rótulo [OFFSET:rótulo ...]
O offset é do arquivo (vaddr do DLL, que começa em 0)."""
import os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gdbc import Gdb

dll = open(sys.argv[1], 'rb').read()
name = sys.argv[2].encode()
pts = {}
for a in sys.argv[3:]:
    o, l = a.split(':', 1)
    pts[int(o, 16)] = l
sigoff = min(pts)
SIG = dll[sigoff:sigoff + 32]
DLOPEN = int(os.environ.get('DLOPEN', '0x080419bc'), 0)      # stub do dlopen no io-display

g = Gdb(1234, retries=600)
g.s.settimeout(600)
g.bp(DLOPEN)
while True:
    g.cont()
    rg = g.regs()
    if rg['pc'] == DLOPEN:
        try:
            s = g.mem(rg['r4'], 32).split(b'\0')[0]
        except Exception:
            s = b'?'
        print('dlopen', s, flush=True)
        if name in s:
            break
    g.unbp(rg['pc']); g.step(); g.bp(DLOPEN)
pr = rg['pr']
g.unbp(DLOPEN)
g.bp(pr)
g.cont()
g.unbp(pr)
print('dlopen voltou', flush=True)

DLSYM = int(os.environ.get('DLSYM', '0x08041a34'), 0)
# símbolos exportados do DLL (nome -> vaddr) para deduzir a base pelo retorno do dlsym
import re as _re
def dynsyms(d):
    e_phoff, = struct.unpack_from('<I', d, 0x1c)
    es, n = struct.unpack_from('<HH', d, 0x2a)
    segs = []
    for i in range(n):
        t, o, va, pa, fs, ms, fl, al = struct.unpack_from('<8I', d, e_phoff + i * es)
        if t == 1: segs.append((va, o, fs))
        if t == 2: dyn = (o, fs)
    def off(v):
        for va, o, fs in segs:
            if va <= v < va + fs: return o + v - va
    tags = {}
    for k in range(0, dyn[1], 8):
        tg, v = struct.unpack_from('<II', d, dyn[0] + k); tags.setdefault(tg, v)
    st, sr, h = tags[6], tags[5], tags[4]
    nch = struct.unpack_from('<I', d, off(h) + 4)[0]
    out = {}
    for i in range(nch):
        nm, val, sz, info, oth, shn = struct.unpack_from('<IIIBBH', d, off(st) + i * 16)
        out[d[off(sr) + nm:].split(b'\0')[0].decode()] = val
    return out
syms = dynsyms(dll)
g.bp(DLSYM)
base = None
while base is None:
    g.cont()
    rg = g.regs()
    if rg['pc'] != DLSYM:
        g.unbp(rg['pc']); g.step(); g.bp(rg['pc']); continue
    try:
        nm = g.mem(rg['r5'], 40).split(b'\0')[0].decode()
    except Exception:
        nm = '?'
    pr = rg['pr']
    g.unbp(DLSYM); g.bp(pr); g.cont(); r2 = g.regs(); g.unbp(pr)
    print('dlsym', nm, hex(r2['r0']), flush=True)
    if nm in syms and r2['r0']:
        base = r2['r0'] - syms[nm]
    g.step(); g.bp(DLSYM)
g.unbp(DLSYM)
print('base =', hex(base), flush=True)
if base:
    for o in pts:
        g.bp(base + o)
    t0 = time.time()
    while time.time() - t0 < float(os.environ.get('SECS', '60')):
        g.cont()
        rg = g.regs()
        o = rg['pc'] - base
        print('%.1fs %s (%x) ' % (time.time() - t0, pts.get(o, '?'), o) + ' '.join('r%d=%08x' % (k, rg['r%d' % k]) for k in range(15)) + ' pr=%08x' % rg['pr'], flush=True)
        g.unbp(rg['pc']); g.step(); g.bp(rg['pc'])

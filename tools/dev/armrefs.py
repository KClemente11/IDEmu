#!/usr/bin/env python3
"""armrefs.py <HmiMain3D> <símbolo>...: acha as funções ARM que carregam o endereço (via GOT) de um símbolo exportado. Uso: achar construtores
(escrevem o vptr) e quem usa um objeto. Precisa de capstone e pyelftools (pasta de bibliotecas em PYLIBS)."""
import os, struct, sys
sys.path.insert(0, os.environ.get('PYLIBS', os.path.dirname(os.path.abspath(__file__)) + '/pylibs'))
from elftools.elf.elffile import ELFFile
f = open(sys.argv[1], 'rb'); raw = f.read(); e = ELFFile(open(sys.argv[1], 'rb')); sec = {s.name: s for s in e.iter_sections()}
dyn = sec['.dynsym']; names = {i: s.name for i, s in enumerate(dyn.iter_symbols())}
symval = {s_.name: s_['st_value'] for s_ in dyn.iter_symbols() if s_['st_value']}
gsec = sec['.got']; ga, go, gs = gsec['sh_addr'], gsec['sh_offset'], gsec['sh_size']
rel = {}
for r in sec['.rel.dyn'].iter_relocations():
    rel[r['r_offset']] = r
def slot_value(a):
    r = rel.get(a)
    if r is not None and r['r_info_sym'] == 0: return struct.unpack_from('<I', raw, go + a - ga)[0]
    return None
got = {}
for a in range(ga, ga + gs, 4):
    v = slot_value(a)
    if v is None: v = struct.unpack_from('<I', raw, go + a - ga)[0]
    for n in sys.argv[2:]:
        if symval.get(n) == v: got.setdefault(n, a)
for r in sec['.rel.dyn'].iter_relocations():
    n = names.get(r['r_info_sym'])
    if n in sys.argv[2:]: got.setdefault(n, r['r_offset'])
text = sec['.text']; ta, to, ts = text['sh_addr'], text['sh_offset'], text['sh_size']
w = lambda a: struct.unpack_from('<I', raw, to + a - ta)[0]
# base da GOT: o primeiro "ldr rN,[pc,#]; add rN,pc,rN" que aparece
gotbase = None
for a in range(ta, ta + 0x4000, 4):
    i = w(a)
    if (i & 0x0f7f0000) == 0x051f0000:      # ldr r,[pc,#imm]
        j = w(a + 8) if False else None
gotbase = int(os.environ.get('GOTBASE', '0x39e7930'), 16)
syms = {n: got[n] for n in sys.argv[2:] if n in got}
print('GOT slots', {k: hex(v) for k, v in syms.items()})
targets = {(v - gotbase) & 0xffffffff: k for k, v in syms.items()}
# literais no texto
lit = {}
for a in range(ta, ta + ts, 4):
    v = w(a)
    if v in targets: lit[a] = targets[v]
# referências: ldr rX,[pc,#imm] cujo literal aponta para esses endereços
refs = {}
for a in range(ta, ta + ts, 4):
    i = w(a)
    if (i & 0x0e5f0000) == 0x041f0000:
        imm = i & 0xfff; la = a + 8 + (imm if (i >> 23) & 1 else -imm)
        if la in lit: refs.setdefault(lit[la], []).append(a)
for k, v in refs.items(): print(k, ' '.join(hex(x) for x in v[:40]))

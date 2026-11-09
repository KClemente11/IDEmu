#!/usr/bin/env python3
"""Mapa (classe de proxy do HMI) -> FktID MOST, extraído do HmiMain3D do SWFL (somente análise; precisa de pyelftools e capstone).

Cada dispositivo MOST do HMI (CPxy<Grupo>) constrói seus membros (um objeto por função) num construtor e, noutra função, chama
`init(membro = this+deslocamento, this, FktID)` para cada um.  Casando os dois pelo deslocamento obtém-se classe -> FktID.
Uso: python3 tools/hmi_most_map.py <HmiMain3D> <grupo, ex.: KombiInterface> [saida.json]
"""
import array, json, re, struct, sys
from elftools.elf.elffile import ELFFile
from capstone import *

path, group = sys.argv[1], sys.argv[2]
raw = open(path, 'rb').read(); e = ELFFile(open(path, 'rb'))
sec = {s.name: s for s in e.iter_sections()}
tx = sec['.text']; TB = tx['sh_addr']; TO = tx['sh_offset']; TS = tx['sh_size']
syms = list(sec['.dynsym'].iter_symbols())
gb = sec['.got']['sh_addr']
md = Cs(CS_ARCH_ARM, CS_MODE_ARM); md.skipdata = True
T32 = array.array('I'); T32.frombytes(raw[TO:TO + TS // 4 * 4])

def word(a): return T32[(a - TB) // 4]

# classe -> deslocamento da entrada da vtable no GOT
slot = {}
for r in sec['.rel.dyn'].iter_relocations():
    if r['r_info_type'] == 21:
        s = syms[r['r_info_sym']]
        if s.name.startswith('_ZTVN') and ('CPxy' + group) in s.name:
            slot[r['r_offset'] - gb] = s.name
def cname(n):
    m = re.match(r'_ZTVN\d+CPxy\w+?(\d+)(C\w+)E$', n)
    return n.split('CPxy' + group)[1][2:-1] if 'CPxy' + group in n else n

def dis(a, n):
    return list(md.disasm(raw[TO + a - TB:TO + a - TB + 4 * n], a))

def func_start(a):
    """Procura para trás o início da função (push {..., lr})."""
    i = (a - TB) // 4
    while i > 0:
        w = T32[i]
        if (w & 0xFFFF4000) == 0xE92D4000: return TB + 4 * i
        i -= 1
    return a

def ctor_class(addr):
    """Classe construída pela função em `addr` (primeiro literal do GOT que é uma vtable do grupo)."""
    for ins in dis(addr, 40):
        if ins.mnemonic == 'ldr' and '[pc' in ins.op_str:
            m = re.search(r'#(0x[0-9a-f]+)', ins.op_str)
            if m:
                lw = word(ins.address + 8 + int(m.group(1), 16))
                if lw in slot: return slot[lw]
    return None

# 1) funções do grupo: endereços que referenciam a vtable da fábrica / dispositivo
refs = {}
for i, w in enumerate(T32):
    if w in slot: refs.setdefault(slot[w], []).append(TB + 4 * i)
print('classes do grupo:', len(refs), file=sys.stderr)

# 2) varredura linear de todas as chamadas `bl` do intervalo de código do grupo, com rastreio simples de r0/r1/r2
lo = min(min(v) for v in refs.values()) - 0x3000; hi = max(max(v) for v in refs.values()) + 0x3000
REG = re.compile(r'^(r\d+|fp|ip|sp|lr|sb|sl)$')
calls = []
reg = {}; val = {}
for ins in dis(lo, (hi - lo) // 4):
    mn, op = ins.mnemonic, ins.op_str
    if mn == 'push' and 'lr' in op:
        reg = {'r0': 0}; val = {}
        continue
    parts = [x.strip() for x in op.split(',')]
    def imm(x):
        try: return int(x.lstrip('#'), 0)
        except Exception: return None
    if mn in ('mov', 'movw') and len(parts) == 2:
        v = imm(parts[1])
        if v is not None: val[parts[0]] = v; reg.pop(parts[0], None)
        elif parts[1] in reg: reg[parts[0]] = reg[parts[1]]; val.pop(parts[0], None)
        else: reg.pop(parts[0], None); val.pop(parts[0], None)
    elif mn == 'add' and len(parts) == 3:
        v = imm(parts[2])
        if v is not None and parts[1] in reg: reg[parts[0]] = reg[parts[1]] + v; val.pop(parts[0], None)
        else: reg.pop(parts[0], None); val.pop(parts[0], None)
    elif mn == 'bl' and op.startswith('#'):
        calls.append((ins.address, int(op[1:], 0), reg.get('r0'), reg.get('r1'), val.get('r2')))
        for r in ('r0', 'r1', 'r2', 'r3'): reg.pop(r, None); val.pop(r, None)
        # os valores de r4.. continuam
    elif parts and REG.match(parts[0]) and mn in ('ldr', 'ldrb', 'ldrh', 'sub', 'orr', 'and', 'eor', 'mvn', 'movt', 'ldm', 'pop'):
        reg.pop(parts[0], None); val.pop(parts[0], None)

# helper de registro: alvo mais chamado com r1 == this (0) e r2 imediato
from collections import Counter
cnt = Counter(t for (_, t, r0, r1, r2) in calls if r1 == 0 and r2 is not None and r0 is not None)
helper = cnt.most_common(1)[0][0] if cnt else None
fkt_at = {}
for (_, t, r0, r1, r2) in calls:
    if t == helper and r0 is not None and r2 is not None: fkt_at[r0] = r2
# construtores de classe
ctor_cache = {}
cls_at = {}
for (_, t, r0, r1, r2) in calls:
    if r0 is None: continue
    if t not in ctor_cache: ctor_cache[t] = ctor_class(t)
    if ctor_cache[t]: cls_at[r0] = cname(ctor_cache[t])
print('helper %s: %d funções; %d membros com classe' % (hex(helper) if helper else None, len(fkt_at), len(cls_at)), file=sys.stderr)
rows = []
for off, fkt in sorted(fkt_at.items(), key=lambda x: x[1]):
    rows.append({'fkt': fkt, 'offset': off, 'class': cls_at.get(off)})
out = {'group': group, 'helper': hex(helper) if helper else None, 'functions': rows,
       'unmatched_classes': sorted(set(cls_at.values()) - set(r['class'] for r in rows))}
json.dump(out, open(sys.argv[3] if len(sys.argv) > 3 else '/dev/stdout', 'w'), indent=1)

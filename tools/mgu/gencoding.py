#!/usr/bin/env python3
"""Gera coding.tab (id -> valor) para o libcod do IDEmu a partir de MGU22_Coding.txt e do esquema cafd_mgu_02_a.bin.
Uso: gencoding.py cafd_mgu_02_a.bin MGU22_Coding.txt saida.tab [NOME=VALOR ...]"""
import re, struct, sys

class FB:
    def __init__(s, p): s.d = open(p, 'rb').read()
    def u32(s, o): return struct.unpack_from('<I', s.d, o)[0]
    def i32(s, o): return struct.unpack_from('<i', s.d, o)[0]
    def u16(s, o): return struct.unpack_from('<H', s.d, o)[0]
    def fields(s, t):
        vt = t - s.i32(t); n = s.u16(vt)
        return [s.u16(vt + 4 + 2 * i) for i in range((n - 4) // 2)]
    def str(s, p):
        q = p + s.u32(p); n = s.u32(q); return s.d[q + 4:q + 4 + n].decode('latin1')
    def vec(s, p):
        q = p + s.u32(p); return [q + 4 + 4 * i for i in range(s.u32(q))]
    def tbl(s, p): return p + s.u32(p)

def flags(fb):
    root = 4 + fb.u32(4)
    for e in fb.vec(root + fb.fields(root)[0]):
        caf = fb.tbl(e); cf = fb.fields(caf)
        sec = fb.str(caf + cf[11]) if len(cf) > 11 and cf[11] else ''
        for g in fb.vec(caf + cf[9]):
            t = fb.tbl(g); f = fb.fields(t)
            name = fb.str(t + f[0])
            fid = fb.u32(t + f[12] + 2)  # uuid: tipo, área, id de 32 bits, número de valores do enum
            default = fb.str(t + f[4]) if len(f) > 4 and f[4] else None
            enum = {}
            if len(f) > 7 and f[7]:
                for v in fb.vec(t + f[7]):
                    tv = fb.tbl(v); fv = fb.fields(tv)
                    n = fb.str(tv + fv[0])
                    enum[n] = fb.i32(tv + fv[1]) if len(fv) > 1 and fv[1] else 0
            yield sec, name, fid, default, enum

def parse_txt(p):
    vals = {}
    for l in open(p, encoding='utf-8', errors='replace'):
        m = re.match(r'\s*"([A-Za-z0-9_]+)"\s*:\s*"([^"]*)"', l)
        if m: vals[m.group(1)] = m.group(2)
    return vals

def resolve(v, default, enum):
    """Valor numérico de um parâmetro: o texto do MGU22_Coding.txt (nome do enum ou número), senão o valor padrão do esquema; None se nenhum serve."""
    val = None
    if v is not None:
        if enum and v in enum: val = enum[v]
        else:
            try: val = int(v, 10)
            except ValueError:
                try: val = int(v, 16)
                except ValueError: pass
    if val is None and default is not None:
        try: val = int(default, 0)
        except ValueError: pass
    return val

def main():
    fb = FB(sys.argv[1]); txt = parse_txt(sys.argv[2])
    for kv in sys.argv[4:]:
        k, v = kv.split('=', 1); txt[k] = v
    out = {}; miss = 0
    # infotainment por último: ganha em ids repetidos entre áreas
    allf = sorted(flags(fb), key=lambda x: x[0] == 'infotainment')
    for sec, name, fid, default, enum in allf:
        val = resolve(txt.get(name), default, enum)
        if val is None: miss += 1; val = 0
        out[fid] = val
    with open(sys.argv[3], 'w') as f:
        for k in sorted(out): f.write('%x %d\n' % (k, out[k]))
    print('flags', len(out), 'sem valor', miss)

if __name__ == '__main__':
    main()

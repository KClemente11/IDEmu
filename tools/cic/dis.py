#!/usr/bin/env python3
"""Desmontador SH-4A little-endian (completo para o que o QNX 6.3 usa, inclusive FPU).
uso: dis.py arquivo base [offset [n_instrucoes]]   |  import dis; dis.dis1(word, addr, fpscr_pr=0) -> texto"""
import struct, sys


def s8(x): return x - 256 if x & 0x80 else x
def s12(x): return x - 4096 if x & 0x800 else x


def dis1(w, pc, nxt=None):
    """desmonta uma palavra de 16 bits; retorna texto. `nxt` não é usado (sem instruções de 32 bits no SH-4A básico)."""
    n = (w >> 8) & 15; m = (w >> 4) & 15; d = w & 15; i8 = w & 255
    hi = w >> 12
    R = lambda x: 'r%d' % x
    if hi == 0:
        lo = w & 15
        t = {0x0008: 'clrt', 0x0009: 'nop', 0x000b: 'rts', 0x0018: 'sett', 0x0019: 'div0u', 0x001b: 'sleep',
             0x0028: 'clrmac', 0x002b: 'rte', 0x0038: 'ldtlb', 0x0048: 'clrs', 0x0058: 'sets'}
        if w in t: return t[w]
        if w & 0xf0ff == 0x0002: return 'stc sr,r%d' % n
        if w & 0xf0ff == 0x0003: return 'bsrf r%d' % n
        if w & 0xf0ff == 0x0012: return 'stc gbr,r%d' % n
        if w & 0xf0ff == 0x0022: return 'stc vbr,r%d' % n
        if w & 0xf0ff == 0x0023: return 'braf r%d' % n
        if w & 0xf0ff == 0x0032: return 'stc ssr,r%d' % n
        if w & 0xf0ff == 0x0042: return 'stc spc,r%d' % n
        if w & 0xf0ff == 0x0052: return 'stc mod,r%d' % n
        if w & 0xf0ff == 0x0062: return 'stc rs,r%d' % n
        if w & 0xf0ff == 0x0072: return 'stc re,r%d' % n
        if w & 0xf0ff == 0x0083: return 'pref @r%d' % n
        if w & 0xf0ff == 0x0093: return 'ocbi @r%d' % n
        if w & 0xf0ff == 0x00a3: return 'ocbp @r%d' % n
        if w & 0xf0ff == 0x00b3: return 'ocbwb @r%d' % n
        if w & 0xf0ff == 0x00c3: return 'movca.l r0,@r%d' % n
        if w & 0xf0ff == 0x00a2: return 'stc sgr,r%d' % n if False else 'stc ?a2,r%d' % n
        if w & 0xf0ff == 0x00fa: return 'stc dbr,r%d' % n
        if w & 0xf08f == 0x0082: return 'stc r%d_bank,r%d' % ((w >> 4) & 7, n)
        if w & 0xf0ff == 0x000a: return 'sts mach,r%d' % n
        if w & 0xf0ff == 0x001a: return 'sts macl,r%d' % n
        if w & 0xf0ff == 0x002a: return 'sts pr,r%d' % n
        if w & 0xf0ff == 0x003a: return 'stc sgr,r%d' % n
        if w & 0xf0ff == 0x005a: return 'sts fpul,r%d' % n
        if w & 0xf0ff == 0x006a: return 'sts fpscr,r%d' % n
        if w & 0xf0ff == 0x0029: return 'movt r%d' % n
        if lo == 4: return 'mov.b r%d,@(r0,r%d)' % (m, n)
        if lo == 5: return 'mov.w r%d,@(r0,r%d)' % (m, n)
        if lo == 6: return 'mov.l r%d,@(r0,r%d)' % (m, n)
        if lo == 7: return 'mul.l r%d,r%d' % (m, n)
        if lo == 12: return 'mov.b @(r0,r%d),r%d' % (m, n)
        if lo == 13: return 'mov.w @(r0,r%d),r%d' % (m, n)
        if lo == 14: return 'mov.l @(r0,r%d),r%d' % (m, n)
        if lo == 15: return 'mac.l @r%d+,@r%d+' % (m, n)
    elif hi == 1: return 'mov.l r%d,@(%d,r%d)' % (m, d * 4, n)
    elif hi == 2:
        t = {0: 'mov.b r%d,@r%d', 1: 'mov.w r%d,@r%d', 2: 'mov.l r%d,@r%d', 4: 'mov.b r%d,@-r%d', 5: 'mov.w r%d,@-r%d',
             6: 'mov.l r%d,@-r%d', 7: 'div0s r%d,r%d', 8: 'tst r%d,r%d', 9: 'and r%d,r%d', 10: 'xor r%d,r%d', 11: 'or r%d,r%d',
             12: 'cmp/str r%d,r%d', 13: 'xtrct r%d,r%d', 14: 'mulu.w r%d,r%d', 15: 'muls.w r%d,r%d'}
        if d in t: return t[d] % (m, n)
    elif hi == 3:
        t = {0: 'cmp/eq', 2: 'cmp/hs', 3: 'cmp/ge', 4: 'div1', 5: 'dmulu.l', 6: 'cmp/hi', 7: 'cmp/gt', 8: 'sub', 10: 'subc',
             11: 'subv', 12: 'add', 13: 'dmuls.l', 14: 'addc', 15: 'addv'}
        if d in t: return '%s r%d,r%d' % (t[d], m, n)
    elif hi == 4:
        lo = w & 0xff
        t = {0x00: 'shll', 0x01: 'shlr', 0x02: 'stc.l?', 0x04: 'rotl', 0x05: 'rotr', 0x08: 'shll2', 0x09: 'shlr2', 0x0a: 'lds mach',
             0x10: 'dt', 0x11: 'cmp/pz', 0x15: 'cmp/pl', 0x18: 'shll8', 0x19: 'shlr8', 0x20: 'shal', 0x21: 'shar', 0x24: 'rotcl',
             0x25: 'rotcr', 0x28: 'shll16', 0x29: 'shlr16', 0x1b: 'tas.b'}
        if lo in (0x00, 0x01, 0x04, 0x05, 0x08, 0x09, 0x10, 0x11, 0x15, 0x18, 0x19, 0x20, 0x21, 0x24, 0x25, 0x28, 0x29):
            return '%s r%d' % (t[lo], n)
        if lo == 0x1b: return 'tas.b @r%d' % n
        if lo == 0x0b: return 'jsr @r%d' % n
        if lo == 0x2b: return 'jmp @r%d' % n
        if lo == 0x0e: return 'ldc r%d,sr' % n
        if lo == 0x1e: return 'ldc r%d,gbr' % n
        if lo == 0x2e: return 'ldc r%d,vbr' % n
        if lo == 0x3e: return 'ldc r%d,ssr' % n
        if lo == 0x4e: return 'ldc r%d,spc' % n
        if lo == 0xfa: return 'ldc r%d,dbr' % n
        if lo & 0x8f == 0x8e: return 'ldc r%d,r%d_bank' % (n, (lo >> 4) & 7)
        if lo == 0x0a: return 'lds r%d,mach' % n
        if lo == 0x1a: return 'lds r%d,macl' % n
        if lo == 0x2a: return 'lds r%d,pr' % n
        if lo == 0x5a: return 'lds r%d,fpul' % n
        if lo == 0x6a: return 'lds r%d,fpscr' % n
        if lo == 0x07: return 'ldc.l @r%d+,sr' % n
        if lo == 0x17: return 'ldc.l @r%d+,gbr' % n
        if lo == 0x27: return 'ldc.l @r%d+,vbr' % n
        if lo == 0x37: return 'ldc.l @r%d+,ssr' % n
        if lo == 0x47: return 'ldc.l @r%d+,spc' % n
        if lo & 0x8f == 0x87: return 'ldc.l @r%d+,r%d_bank' % (n, (lo >> 4) & 7)
        if lo == 0x06: return 'lds.l @r%d+,mach' % n
        if lo == 0x16: return 'lds.l @r%d+,macl' % n
        if lo == 0x26: return 'lds.l @r%d+,pr' % n
        if lo == 0x56: return 'lds.l @r%d+,fpul' % n
        if lo == 0x66: return 'lds.l @r%d+,fpscr' % n
        if lo == 0x03: return 'stc.l sr,@-r%d' % n
        if lo == 0x13: return 'stc.l gbr,@-r%d' % n
        if lo == 0x23: return 'stc.l vbr,@-r%d' % n
        if lo == 0x33: return 'stc.l ssr,@-r%d' % n
        if lo == 0x43: return 'stc.l spc,@-r%d' % n
        if lo == 0x32: return 'stc.l sgr,@-r%d' % n
        if lo & 0x8f == 0x83: return 'stc.l r%d_bank,@-r%d' % ((lo >> 4) & 7, n)
        if lo == 0x02: return 'sts.l mach,@-r%d' % n
        if lo == 0x12: return 'sts.l macl,@-r%d' % n
        if lo == 0x22: return 'sts.l pr,@-r%d' % n
        if lo == 0x52: return 'sts.l fpul,@-r%d' % n
        if lo == 0x62: return 'sts.l fpscr,@-r%d' % n
        if lo == 0xf2: return 'stc.l dbr,@-r%d' % n
        if lo & 0xf == 0xc: return 'shad r%d,r%d' % (m, n)
        if lo & 0xf == 0xd: return 'shld r%d,r%d' % (m, n)
        if lo & 0xf == 0xf: return 'mac.w @r%d+,@r%d+' % (m, n)
        if lo & 0xf == 0xe and lo & 0x80 == 0: pass
    elif hi == 5: return 'mov.l @(%d,r%d),r%d' % (d * 4, m, n)
    elif hi == 6:
        t = {0: 'mov.b @r%d,r%d', 1: 'mov.w @r%d,r%d', 2: 'mov.l @r%d,r%d', 3: 'mov r%d,r%d', 4: 'mov.b @r%d+,r%d',
             5: 'mov.w @r%d+,r%d', 6: 'mov.l @r%d+,r%d', 7: 'not r%d,r%d', 8: 'swap.b r%d,r%d', 9: 'swap.w r%d,r%d',
             10: 'negc r%d,r%d', 11: 'neg r%d,r%d', 12: 'extu.b r%d,r%d', 13: 'extu.w r%d,r%d', 14: 'exts.b r%d,r%d', 15: 'exts.w r%d,r%d'}
        return t[d] % (m, n)
    elif hi == 7: return 'add #%d,r%d' % (s8(i8), n)
    elif hi == 8:
        sub = (w >> 8) & 15
        if sub == 0: return 'mov.b r0,@(%d,r%d)' % (d, m)
        if sub == 1: return 'mov.w r0,@(%d,r%d)' % (d * 2, m)
        if sub == 4: return 'mov.b @(%d,r%d),r0' % (d, m)
        if sub == 5: return 'mov.w @(%d,r%d),r0' % (d * 2, m)
        if sub == 8: return 'cmp/eq #%d,r0' % s8(i8)
        if sub in (9, 11, 13, 15):
            nm = {9: 'bt', 11: 'bf', 13: 'bt/s', 15: 'bf/s'}[sub]
            return '%s 0x%08x' % (nm, (pc + 4 + s8(i8) * 2) & 0xffffffff)
    elif hi == 9: return 'mov.w @(0x%08x),r%d   ; pc+%d' % ((pc + 4 + i8 * 2) & 0xffffffff, n, i8 * 2)
    elif hi == 10: return 'bra 0x%08x' % ((pc + 4 + s12(w & 0xfff) * 2) & 0xffffffff)
    elif hi == 11: return 'bsr 0x%08x' % ((pc + 4 + s12(w & 0xfff) * 2) & 0xffffffff)
    elif hi == 12:
        sub = (w >> 8) & 15
        t = {0: 'mov.b r0,@(%d,gbr)', 1: 'mov.w r0,@(%d,gbr)', 2: 'mov.l r0,@(%d,gbr)', 4: 'mov.b @(%d,gbr),r0', 5: 'mov.w @(%d,gbr),r0',
             6: 'mov.l @(%d,gbr),r0'}
        sc = {0: 1, 1: 2, 2: 4, 4: 1, 5: 2, 6: 4}
        if sub in t: return t[sub] % (i8 * sc[sub])
        if sub == 3: return 'trapa #%d' % i8
        if sub == 7: return 'mova @(0x%08x),r0' % (((pc + 4) & ~3) + i8 * 4)
        t2 = {8: 'tst #%d,r0', 9: 'and #%d,r0', 10: 'xor #%d,r0', 11: 'or #%d,r0'}
        if sub in t2: return t2[sub] % i8
        t3 = {12: 'tst.b #%d,@(r0,gbr)', 13: 'and.b #%d,@(r0,gbr)', 14: 'xor.b #%d,@(r0,gbr)', 15: 'or.b #%d,@(r0,gbr)'}
        return t3[sub] % i8
    elif hi == 13: return 'mov.l @(0x%08x),r%d   ; pc+%d' % ((((pc + 4) & ~3) + i8 * 4) & 0xffffffff, n, i8 * 4)
    elif hi == 14: return 'mov #%d,r%d' % (s8(i8), n)
    elif hi == 15:
        lo = w & 15
        if lo == 0: return 'fadd fr%d,fr%d' % (m, n)
        if lo == 1: return 'fsub fr%d,fr%d' % (m, n)
        if lo == 2: return 'fmul fr%d,fr%d' % (m, n)
        if lo == 3: return 'fdiv fr%d,fr%d' % (m, n)
        if lo == 4: return 'fcmp/eq fr%d,fr%d' % (m, n)
        if lo == 5: return 'fcmp/gt fr%d,fr%d' % (m, n)
        if lo == 6: return 'fmov.s @(r0,r%d),fr%d' % (m, n)
        if lo == 7: return 'fmov.s fr%d,@(r0,r%d)' % (m, n)
        if lo == 8: return 'fmov.s @r%d,fr%d' % (m, n)
        if lo == 9: return 'fmov.s @r%d+,fr%d' % (m, n)
        if lo == 10: return 'fmov.s fr%d,@r%d' % (m, n)
        if lo == 11: return 'fmov.s fr%d,@-r%d' % (m, n)
        if lo == 12: return 'fmov fr%d,fr%d' % (m, n)
        if lo == 14: return 'fmac fr0,fr%d,fr%d' % (m, n)
        if lo == 13:
            t = {0: 'fsts fpul,fr%d', 1: 'flds fr%d,fpul', 2: 'float fpul,fr%d', 3: 'ftrc fr%d,fpul', 4: 'fneg fr%d', 5: 'fabs fr%d',
                 6: 'fsqrt fr%d', 7: 'fsrra fr%d', 8: 'fldi0 fr%d', 9: 'fldi1 fr%d', 10: 'fcnvsd fpul,dr%d', 11: 'fcnvds dr%d,fpul'}
            if m in t: return t[m] % n
            if w & 0xf3ff == 0xf0fd: return 'fipr fv%d,fv%d' % ((w >> 8) & 3, (w >> 10) & 3) if False else 'fipr/ftrv'
            if w & 0xf3ff == 0xf1fd: return 'ftrv xmtrx,fv%d' % (n & 12)
            if w == 0xfbfd: return 'frchg'
            if w == 0xf3fd: return 'fschg'
    return '.word 0x%04x' % w


def dis(data, base, n=None):
    out = []
    for i in range(0, len(data) - 1, 2):
        w = struct.unpack_from('<H', data, i)[0]
        out.append((base + i, w, dis1(w, base + i)))
        if n and len(out) >= n: break
    return out


def lit(blob, base, a, w):
    """valor do literal para mov.l/mov.w @(disp,pc) em blob (carregado em base)."""
    hi = w >> 12
    if hi == 0xd: ea = ((a + 4) & ~3) + (w & 255) * 4; fmt = '<I'
    elif hi == 9: ea = a + 4 + (w & 255) * 2; fmt = '<H'
    else: return None
    o = ea - base
    if 0 <= o < len(blob) - 4:
        v = struct.unpack_from(fmt, blob, o)[0]
        if fmt == '<H': v = v - 0x10000 if v & 0x8000 else v
        return v
    return None


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '-q']
    quiet = '-q' in sys.argv       # -q: esconde nops
    blob = open(args[0], 'rb').read(0x600000)
    base = int(args[1], 0); off = int(args[2], 0) if len(args) > 2 else 0
    n = int(args[3], 0) if len(args) > 3 else 64
    data = blob[off:off + n * 2]
    for a, w, t in dis(data, base + off):
        if quiet and w == 9: continue
        v = lit(blob, base, a, w)
        extra = '' if v is None else '   ; = 0x%x' % (v & 0xffffffff)
        print('%08x  %04x  %s%s' % (a, w, t, extra))

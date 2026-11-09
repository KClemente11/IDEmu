#!/usr/bin/env python3
"""Navegação em ELF SH-4 (QNX) sem seções: strings -> referências no pool de literais -> desmontagem.
uso:
  elfx.py ARQ str  TEXTO            lista strings que contêm TEXTO (vaddr e texto)
  elfx.py ARQ xref VADDR            procura palavras de 32 bits == VADDR (literais) e mostra a instrução que as carrega
  elfx.py ARQ dis  VADDR [N]        desmonta N instruções a partir de VADDR (padrão 80), anotando literais e strings
"""
import os, re, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dis as D


class Elf:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        e_phoff, = struct.unpack_from('<I', self.d, 0x1c)
        e_phentsize, e_phnum = struct.unpack_from('<HH', self.d, 0x2a)
        self.segs = []
        for i in range(e_phnum):
            p_type, p_off, p_va, p_pa, p_fs, p_ms, p_fl, p_al = struct.unpack_from('<8I', self.d, e_phoff + i * e_phentsize)
            if p_type == 1:
                self.segs.append((p_va, p_off, p_fs, p_ms))

    def off(self, va):
        for v, o, fs, ms in self.segs:
            if v <= va < v + fs:
                return o + va - v
        return None

    def va(self, off):
        for v, o, fs, ms in self.segs:
            if o <= off < o + fs:
                return v + off - o
        return None

    def u32(self, va):
        o = self.off(va)
        return None if o is None or o + 4 > len(self.d) else struct.unpack_from('<I', self.d, o)[0]

    def cstr(self, va, n=90):
        o = self.off(va)
        if o is None:
            return None
        s = self.d[o:o + n].split(b'\0')[0]
        if len(s) >= 3 and all(32 <= c < 127 or c in (9, 10) for c in s):
            return s.decode('latin1')
        return None


def main():
    el = Elf(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == 'str':
        pat = sys.argv[3].encode()
        for m in re.finditer(re.escape(pat), el.d):
            s = el.d.rfind(b'\0', 0, m.start()) + 1
            e = el.d.find(b'\0', m.start())
            va = el.va(s)
            print('%08x  %s' % (va if va is not None else 0, el.d[s:e].decode('latin1')))
    elif cmd == 'xref':
        tgt = int(sys.argv[3], 16)
        pat = struct.pack('<I', tgt)
        for m in re.finditer(re.escape(pat), el.d):
            if m.start() % 4:
                continue
            va = el.va(m.start())
            if va is None:
                continue
            # instruções mov.l @(disp,pc) que apontam para va (procura em volta, antes do literal)
            for back in range(0, 1024, 2):
                a = va - back
                w = el.u32(a) if False else None
                o = el.off(a)
                if o is None:
                    break
                w = struct.unpack_from('<H', el.d, o)[0]
                if (w >> 12) == 0xd and (((a + 4) & ~3) + (w & 255) * 4) == va:
                    print('literal %08x  carregado por %08x: %s' % (va, a, D.dis1(w, a)))
    elif cmd == 'plt':
        # pilhas de importação: lê DT_JMPREL/DT_SYMTAB/DT_STRTAB e associa cada stub (mov.l @(GOT),r1; jmp @r1) ao nome
        e_phoff, = struct.unpack_from('<I', el.d, 0x1c)
        e_phentsize, e_phnum = struct.unpack_from('<HH', el.d, 0x2a)
        dyn = None
        for i in range(e_phnum):
            t, o, va, pa, fs, ms, fl, al = struct.unpack_from('<8I', el.d, e_phoff + i * e_phentsize)
            if t == 2:
                dyn = (o, fs)
        tags = {}
        for k in range(0, dyn[1], 8):
            tg, val = struct.unpack_from('<II', el.d, dyn[0] + k)
            tags.setdefault(tg, val)
        symtab, strtab, jmprel, pltsz = tags[6], tags[5], tags[23], tags[2]
        names = {}
        stride = 12 if tags.get(20) == 7 else 8       # DT_PLTREL: 7 = RELA (SH usa RELA)
        for k in range(0, pltsz, stride):
            off, info = struct.unpack_from('<II', el.d, el.off(jmprel) + k)
            sym = info >> 8
            nm_off, = struct.unpack_from('<I', el.d, el.off(symtab) + sym * 16)
            nm = el.d[el.off(strtab) + nm_off:].split(b'\0')[0].decode()
            names[off] = nm
        for a in range(0x08041000, 0x08042000, 2):
            o = el.off(a)
            w = struct.unpack_from('<H', el.d, o)[0]
            if (w >> 12) == 0xd:
                ea = ((a + 4) & ~3) + (w & 255) * 4
                v = el.u32(ea)
                if v in names:
                    print('%08x  %s' % (a, names[v]))
    elif cmd == 'dis':
        a = int(sys.argv[3], 16)
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 80
        for _ in range(n):
            o = el.off(a)
            if o is None:
                break
            w = struct.unpack_from('<H', el.d, o)[0]
            t = D.dis1(w, a)
            note = ''
            if (w >> 12) == 0xd:
                ea = ((a + 4) & ~3) + (w & 255) * 4
                v = el.u32(ea)
                if v is not None:
                    note = '   ; =0x%x' % v
                    s = el.cstr(v)
                    if s:
                        note += '  "%s"' % s
            elif (w >> 12) == 9:
                ea = a + 4 + (w & 255) * 2
                o2 = el.off(ea)
                if o2 is not None:
                    note = '   ; =0x%x' % struct.unpack_from('<H', el.d, o2)[0]
            print('%08x  %04x  %s%s' % (a, w, t, note))
            a += 2


if __name__ == '__main__':
    main()

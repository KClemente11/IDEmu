#!/usr/bin/env python3
"""Acha, em código SH, as instruções que carregam um literal (mov.l/mov.w @(pc)) com certo valor.
uso: lit.py arquivo base valor [valor...]   (valor pode ser prefixo com 0x, ou 'hw' = faixa de periféricos)"""
import sys, struct
f = open(sys.argv[1], 'rb'); d = f.read(0x40000)
base = int(sys.argv[2], 0)
want = [int(x, 0) for x in sys.argv[3:]]
for off in range(0, len(d) - 2, 2):
    w = struct.unpack_from('<H', d, off)[0]
    if w >> 12 == 0xd:
        ea = ((base + off + 4) & ~3) + (w & 255) * 4
        o = ea - base
        if 0 <= o < len(d) - 3:
            v = struct.unpack_from('<I', d, o)[0]
            if v in want or any(a <= v <= b for a, b in zip(want[::2], want[1::2])) and False:
                print('%08x r%d <- %08x' % (base + off, (w >> 8) & 15, v))

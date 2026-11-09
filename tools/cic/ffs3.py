#!/usr/bin/env python3
"""Extrator de QNX FFS3 (f3s) little-endian, como o EFS_RO original do CIC (segmento 0x04D80000 do pacote 3a6).
Formato observado (unidades de 2^unit_pow2 bytes, 256 KB aqui):
  * cabeçalhos de extent de 32 bytes crescem do FIM da unidade para trás (índice 0 = últimos 32 bytes):
      +0x00 status (3 cópias de u32)   +0x14 u16 offset do texto em palavras de 4 bytes   +0x16 u16 tamanho
      +0x18 next (u16 unidade lógica, u16 índice)    +0x1c super (idem)        0xffff = nulo
  * unidade lógica = física + 1 (as unidades da imagem de produção estão em ordem)
  * entrada de diretório (texto do extent): u16 ?, u8 ?, u8 tamanho do nome (com NUL), first (unidade, índice), nome,
    alinhado a 4, depois um stat (u16 tamanho=0x14, u16 mode, ...). Diretório: first = primeiro filho; os irmãos seguem
    o 'next' do cabeçalho da entrada. Arquivo: first = primeiro extent de dados; os dados seguem o 'next' de cada extent.
uso: ffs3.py IMAGEM [destino]   (lista; com destino extrai)   |   import ffs3; ffs3.walk(dados) -> [(caminho, tipo, dados, mode)]"""
import os, struct, sys

UNIT = 0x40000


class F3S:
    def __init__(self, d):
        self.d = d
        self.unit = 1 << d[4] if d[2] == 0x4c else UNIT

    def head(self, lu, idx):
        base = (lu - 1) * self.unit
        h = base + self.unit - 0x20 * (idx + 1)
        st, = struct.unpack_from('<I', self.d, h)
        off, size, nu, ni, su, si = struct.unpack_from('<HHHHHH', self.d, h + 0x14)
        return {'status': st, 'text': base + off * 4, 'size': size,
                'next': None if nu == 0xffff else (nu, ni), 'super': None if su == 0xffff else (su, si)}

    def text(self, p):
        h = self.head(*p)
        return self.d[h['text']:h['text'] + h['size']], h

    def dirent(self, p):
        t, h = self.text(p)
        nl = t[3]
        first = struct.unpack_from('<HH', t, 4)
        name = t[8:8 + nl].split(b'\0')[0].decode('latin1')
        so = (8 + nl + 3) & ~3
        mode = struct.unpack_from('<H', t, so + 2)[0] if so + 4 <= len(t) else 0
        return name, (None if first[0] == 0xffff else first), mode, h

    def data(self, p):
        out = []
        seen = set()
        while p and p not in seen:
            seen.add(p)
            t, h = self.text(p)
            out.append(t)
            p = h['next']
        return b''.join(out)

    def walk(self, p, prefix=''):
        res = []
        seen = set()
        while p and p not in seen:
            seen.add(p)
            name, first, mode, h = self.dirent(p)
            path = (prefix + '/' + name).lstrip('/')
            kind = mode & 0xf000
            if kind == 0x4000:
                res.append((path, 'D', None, mode & 0o7777))
                if first:
                    res += self.walk(first, path)
            elif kind == 0xa000:
                res.append((path, 'L', self.data(first).split(b'\0')[0].decode('latin1') if first else '', mode & 0o7777))
            else:
                res.append((path, 'F', self.data(first) if first else b'', mode & 0o7777))
            p = h['next']
        return res


def walk(d):
    """Árvore a partir do diretório raiz do FFS3 (a entrada '/mnt/EFS_RO' no índice 3 da unidade lógica 1)."""
    f = F3S(d)
    name, first, mode, h = f.dirent((1, 3))
    return f.walk(first) if first else []


def main():
    d = open(sys.argv[1], 'rb').read()
    ents = walk(d)
    dst = sys.argv[2] if len(sys.argv) > 2 else None
    for p, k, data, mode in ents:
        print('%s %6o %9s %s' % (k, mode, len(data) if k == 'F' else '', p) + (' -> ' + data if k == 'L' else ''))
        if dst:
            q = os.path.join(dst, p)
            if k == 'D':
                os.makedirs(q, exist_ok=True)
            elif k == 'F':
                os.makedirs(os.path.dirname(q), exist_ok=True)
                open(q, 'wb').write(data)


if __name__ == '__main__':
    main()

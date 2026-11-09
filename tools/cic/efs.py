#!/usr/bin/env python3
"""Monta a árvore /mnt/EFS_RO como imagefs a partir dos tar.gz do pacote 3a6 (segmentos 0x30000000, 0x360000c0, 0x3f0000b0).
O EFS_RO original é um FFS3 de flash cuja tabela de partições não está nos pacotes; aqui o conteúdo vem dos tar.gz.
uso: efs.py pacote.bin saida.ifs [--com-mapas] [--com-voz]"""
import io, os, sys, tarfile, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkimagefs

SEGS = [('voz', 20736698), ('base', 5610436), ('res', 45384615)]   # após os 3 primeiros segmentos (flash)
START = 4980736 + 73662464 + 33554432
LIMIT = 0x7ce0000 - 0x4d80000   # flash livre entre 0x4D80000 e a partição HBpersistence (127872K)

FFS3_OFF, FFS3_LEN = 4980736 + 73662464, 33554432      # segmento 0x04D80000 (o EFS_RO original, FFS3)


def entries(pkg, mapas=False, voz=False):
    import ffs3
    f = open(pkg, 'rb'); off = START; out = []; seen = set()
    # conteúdo do FFS3 original: Hmi/data/ro (ResDB.menu/bitmap/text..., sem eles o HMI não carrega a GUI), DSP, icu, opt...
    f.seek(FFS3_OFF)
    orig = {p: (p, k, d, m) for p, k, d, m in ffs3.walk(f.read(FFS3_LEN))}
    tar = []
    for name, n in SEGS:
        f.seek(off); data = f.read(n); off += n
        if name == 'voz' and not voz:
            continue
        t = tarfile.open(fileobj=io.BytesIO(zlib.decompressobj(31).decompress(data)))
        for m in t.getmembers():
            p = m.name[2:] if m.name.startswith('./') else m.name
            p = p.strip('/')
            if not p or p in seen:
                continue
            if p.startswith('mapstyles') and not mapas:
                continue
            seen.add(p)
            mode = (m.mode & 0o777) or 0o755
            if m.isdir(): tar.append((p, 'D', None, mode))
            elif m.issym(): tar.append((p, 'L', m.linkname, mode))
            elif m.isreg(): tar.append((p, 'F', t.extractfile(m).read(), mode))
    # o FFS3 tem prioridade; as entradas do HD (tar) substituem só os links simbólicos do FFS3 que apontam para o HD
    # (fonts -> /mnt/hbdata/ext/fonts, opt/bin/taco ...) e completam o resto
    merged = dict(orig)
    vehicles = []
    for e in tar:
        p = e[0]
        if p.startswith('res/ResDB.vehicle-'):
            vehicles.append(e); continue
        if p not in merged or merged[p][1] == 'L':
            merged[p] = e
    out = list(merged.values())
    # imagens de veículo (~1,3 MB cada): só as que couberem na flash livre
    used = sum(len(d) + 512 for p, k, d, m in out if k == 'F') + 64 * len(out)
    pref = ('e90', 'f10', 'f30', 'e60', 'f01', 'e70', 'f25', 'e84', 'f20', 'e87', 'e92', 'e93', 'f07', 'e71', 'f11', 'e89')
    vehicles.sort(key=lambda e: pref.index(e[0].rsplit('-', 1)[1]) if e[0].rsplit('-', 1)[1] in pref else 99)
    if vehicles and 'res' not in merged:
        out.append(('res', 'D', None, 0o755))
    for e in vehicles:
        if used + len(e[2]) + 512 > LIMIT - (1 << 20):
            continue
        out.append(e); used += len(e[2]) + 512
    return out

def build(pkg, dst, mapas=False, voz=False):
    img = mkimagefs.build(entries(pkg, mapas, voz))
    assert len(img) <= LIMIT, 'imagefs de %d bytes não cabe na flash livre (%d)' % (len(img), LIMIT)
    open(dst, 'wb').write(img)
    return len(img)

if __name__ == '__main__':
    print(build(sys.argv[1], sys.argv[2], '--com-mapas' in sys.argv, '--com-voz' in sys.argv))

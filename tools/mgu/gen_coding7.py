#!/usr/bin/env python3
"""Extrai a codificação do iDrive 7 do HmiMain3D (o HMI do MGU) para um JSON: parâmetros, valores, áreas e valores de fábrica.

Uso: gen_coding7.py HmiMain3D saida.json

Como o HMI guarda a codificação (descoberto lendo o binário, versão 030_016_002 do pacote do HMI):
  * Memória compartilhada `rawcodingdata` (4144 bytes, criada pelo CodingShmApp). Byte 0x28 = estado: bit 3 = bloco presente; bit 0 = dados reais em +0x2c;
    bit 1 ou 2 (sem o bit 0) = codificação padrão (a do próprio HMI). A partir de +0x2c ficam as áreas.
  * 16 áreas (id 0x3000 a 0x3010, as classes CodingHMI_SPEECH, CodingSYSTEM_CONFIGURATION...), cada uma com posição e tamanho fixos (AREAS abaixo, lidos da fábrica
    de objetos do HMI: um `switch` sobre o id que chama CodingBase(posição, tamanho, padrão)). O HMI do banco traseiro (RSE) usa as mesmas áreas deslocadas de 6 a 7 bytes.
  * Os valores de fábrica são um vetor de bytes dentro do binário (HU em 0x82d6880, RSE em 0x82d5d60).
  * O dicionário de parâmetros (CVACoding) é uma tabela de 56 bytes por entrada: [ponteiro do nome, A, B, ponteiro do valor, 0, 0, 0] com
    A = id da área (u16, 0x3000 + n) | byte inicial << 16 | byte final << 32 e B = máscara (bits 0 a 7) | número do valor << 8 | id do texto << 32.
    Cada parâmetro tem uma entrada por valor possível (o texto do valor é `va_<NOME>_<valor>`); `VariantVal` é a entrada genérica de valor numérico."""
import json, struct, sys

AREAS = [   # id, nome, (posição, tamanho) no HU, (posição, tamanho) no RSE
    (0x3000, 'HMI_SPEECH', (0, 151), (0, 158)), (0x3001, 'CONNECTIVITY_A4A', (151, 150), (158, 150)), (0x3002, 'AUDIO_BROADCAST', (301, 150), (308, 150)),
    (0x3003, 'TELEMATICS', (451, 150), (458, 150)), (0x3004, 'SYSTEM_CONFIGURATION', (601, 150), (608, 150)), (0x3005, 'APIX_CID_UND_ZIN', (751, 151), (758, 150)),
    (0x3006, 'NAVIGATION', (902, 150), (908, 150)), (0x3007, 'ENTERTAINMENT', (1052, 150), (1058, 150)), (0x3008, 'FES', (1202, 150), (1208, 150)),
    (0x3009, 'EFFICIENT_DYNAMICS', (1352, 150), (1358, 150)), (0x300a, 'SARAH', (1502, 150), (1508, 150)), (0x300b, 'PARKEN', (1652, 80), (1658, 80)),
    (0x300c, 'TOUCH_COMMAND', (1732, 150), (1738, 150)), (0x300d, 'KOMBI_HUD', (1882, 150), (1888, 150)), (0x300e, 'LANGUAGE', (2032, 100), (2038, 100)),
    (0x3010, 'M_GMBH', (2142, 30), (2148, 30))]
BLOB_HU, SIZE_HU = 0x82d6880, 2172
BLOB_RSE, SIZE_RSE = 0x82d5d60, 2178
ANCHOR = b'va_SERVICE_PACK_2018'

def load(path):
    d = open(path, 'rb').read()
    if d[:4] != b'\x7fELF' or d[4] != 2: raise SystemExit('não é um ELF de 64 bits: ' + path)
    phoff, = struct.unpack_from('<Q', d, 0x20); phes, phn = struct.unpack_from('<HH', d, 0x36)
    segs = []
    for i in range(phn):
        ty, fl, off, va, pa, fsz, msz, al = struct.unpack_from('<IIQQQQQQ', d, phoff + i * phes)
        if ty == 1: segs.append((off, va, fsz))
    shoff, = struct.unpack_from('<Q', d, 0x28); shes, shn, shsi = struct.unpack_from('<HHH', d, 0x3a)
    secs = [struct.unpack_from('<IIQQQQIIQQ', d, shoff + i * shes) for i in range(shn)]
    names = {}
    for s in secs:
        o = secs[shsi][4] + s[0]; names[d[o:d.index(b'\0', o)].decode()] = s
    rela = names['.rela.dyn']; rel = {}
    for o in range(rela[4], rela[4] + rela[5], 24):
        r_off, r_info, r_add = struct.unpack_from('<QQq', d, o)
        if (r_info & 0xffffffff) == 8: rel[r_off] = r_add
    return d, segs, rel

def main(src, dst):
    d, segs, rel = load(src)
    def va2off(v):
        for so, sv, sz in segs:
            if sv <= v < sv + sz: return so + (v - sv)
    def cstr(v):
        o = va2off(v)
        if o is None: return None
        t = d[o:o + 96]; t = t[:t.index(b'\0')] if b'\0' in t else t
        return t.decode('latin1') if t and all(32 <= c < 127 for c in t) else None
    def qw(a): return struct.unpack_from('<Q', d, va2off(a))[0]
    i = d.find(b'\0' + ANCHOR + b'\0')
    if i < 0: raise SystemExit('esta versão do HMI não tem o dicionário de codificação esperado')
    va = i + 1                                           # no primeiro segmento o deslocamento no arquivo é o próprio endereço
    refs = [o for o, a in rel.items() if a == va]
    if not refs: raise SystemExit('tabela de codificação não encontrada')
    def ok(e): return rel.get(e) is not None and cstr(rel[e]) and rel.get(e + 24) is not None and cstr(rel[e + 24]) and qw(e + 32) == 0 and qw(e + 40) == 0 and qw(e + 48) == 0
    ent = refs[0] - 24
    while ok(ent - 56): ent -= 56
    rows = []
    while ok(ent): rows.append((cstr(rel[ent]), qw(ent + 8), qw(ent + 16), cstr(rel[ent + 24]))); ent += 56
    if len(rows) < 3000: raise SystemExit('tabela de codificação curta demais: %d entradas' % len(rows))
    params = {}
    for name, a, b, label in rows:
        area, start, end = a & 0xffff, (a >> 16) & 0xffff, (a >> 32) & 0xffff
        mask, val = b & 0xff, (b >> 8) & 0xff
        p = params.setdefault(name, {'name': name, 'area': area, 'start': start, 'end': end, 'mask': mask, 'vals': []})
        if (p['area'], p['start'], p['end'], p['mask']) != (area, start, end, mask): p['bad'] = True
        short = label.replace('va_' + name + '_', '') if label.startswith('va_' + name + '_') else ('' if label == 'va_' + name else label)
        if not any(v[0] == val for v in p['vals']) or short != 'VariantVal': p['vals'].append([val, short])
    good = []
    for p in params.values():
        if p.pop('bad', False): continue
        seen = {}
        for v, s in p['vals']:
            if v not in seen or seen[v] == 'VariantVal': seen[v] = s
        p['vals'] = sorted([v, s] for v, s in seen.items())
        good.append(p)
    hu = d[BLOB_HU:BLOB_HU + SIZE_HU]; rse = d[BLOB_RSE:BLOB_RSE + SIZE_RSE]
    if sum(1 for x in hu if x) < 100 or sum(1 for x in rse if x) < 100: raise SystemExit('valores de fábrica não encontrados')
    json.dump({'version': 1, 'areas': [{'id': a, 'name': n, 'hu': list(h), 'rse': list(r)} for a, n, h, r in AREAS], 'blob': {'hu': hu.hex(), 'rse': rse.hex()}, 'params': good},
              open(dst, 'w'), separators=(',', ':'))
    print('codificação do iDrive 7: %d parâmetros, %d entradas, %d áreas' % (len(good), len(rows), len(AREAS)))

if __name__ == '__main__': main(*sys.argv[1:3])

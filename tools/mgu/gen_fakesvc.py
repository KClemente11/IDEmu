#!/usr/bin/env python3
"""Gera a tabela de serviços SOME/IP falsos do iDrive 7 (lida por `idemu-fakesvc`, src/mgu/fakesvc.c) a partir de someip-interfaces.json.

Uso: gen_fakesvc.py someip-interfaces.json saida.tab [servico[=campo=hex,campo=hex] ...]
  servico = nome da interface (ex. Lifecycle, VehicleCondition, Key), o nome completo (de.bmw.body.Key) ou o id (0xb51b; use o id quando o nome se repete).
  campo=hex substitui o valor padrão serializado do campo (ex. powerStateDetailed=63).

Formato da tabela (uma linha por item, campos separados por espaço):
  S <serviceId hex> <instância hex> <major> <minor> <nome>
  F <getter|-> <setter|-> <notificador|-> <grupo|-> <hex do valor> <nome do campo>
Serialização do CommonAPI SOME/IP: big endian, enum com `enumWidth` bytes, struct sem campo de tamanho, membros com `bitWidth` empacotados do bit mais alto para o mais baixo.
"""
import json, sys

PRIM = {'UInt8': 1, 'Int8': 1, 'UInt16': 2, 'Int16': 2, 'UInt32': 4, 'Int32': 4, 'UInt64': 8, 'Int64': 8, 'Bool': 1, 'Boolean': 1, 'Float': 4, 'Double': 8}

class Ser:
    def __init__(self, T): self.T = T
    def default(self, ref, dv=None):
        """(bytes, largura em bits) do valor padrão de um tipo."""
        if ref in PRIM:
            n = PRIM[ref]; v = int(dv) if dv is not None and not isinstance(dv, (list, dict)) else 0
            return (v & ((1 << (8 * n)) - 1)).to_bytes(n, 'big'), 8 * n
        if ref not in self.T and (ref.startswith('Utf') or ref.startswith('String')): return (0).to_bytes(4, 'big'), None     # texto vazio: só o campo de tamanho
        t = self.T[ref]; k = t['type']
        if k == 'enum':
            n = t.get('enumWidth', 1); vals = list(t['items'].values()); v = dv if dv is not None else t.get('defaultValue', 0 if 0 in vals or not vals else vals[0])
            return (int(v) & ((1 << (8 * n)) - 1)).to_bytes(n, 'big'), 8 * n
        if k == 'typedef': return self.default(t['dataRef'], dv if dv is not None else t.get('defaultValue'))
        if k == 'struct': return self.struct(t), None
        if k == 'array':
            if 'arrayMinLength' in t and t.get('arrayMinLength') == t.get('arrayMaxLength'):
                one, _ = self.default(t['dataRef']); return one * int(t['arrayMinLength']), None
            return (0).to_bytes(t.get('arrayLengthWidth', 4), 'big'), None
        if k in ('union', 'map'): return (0).to_bytes(4, 'big'), None
        raise ValueError('tipo sem serialização: %s (%s)' % (ref, k))
    def struct(self, t):
        out = bytearray(); bits = 0; acc = 0
        base = t.get('extends')
        if base: out += self.struct(self.T[base])
        for m in t.get('members', []):
            ref = m['dataRef']; dv = m.get('defaultValue'); bw = m.get('bitWidth')
            if bw:
                v = int(dv) if dv is not None else 0
                acc = (acc << bw) | (v & ((1 << bw) - 1)); bits += bw
                while bits >= 8: bits -= 8; out.append((acc >> bits) & 0xff); acc &= (1 << bits) - 1
                continue
            b, _ = self.default(ref, dv); out += b
        if bits: out.append((acc << (8 - bits)) & 0xff)
        return bytes(out)

def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = json.loads(open(src, 'rb').read().decode('latin1'), strict=False)
    I, N, T = d['interfaces'], d['instanceIDs'], d['datatypes']; ser = Ser(T)
    lines = []
    for arg in sys.argv[3:]:
        name, _, rest = arg.partition('=')
        over = dict(kv.split('=') for kv in rest.split(',') if kv)
        keys = [k for k in I if k == name or k.rsplit('.', 1)[-1] == name or (name.startswith('0x') and I[k]['serviceId'] == int(name, 16))]
        if not keys: raise SystemExit('interface desconhecida: ' + name)
        k = keys[0]; v = I[k]
        insts = N.get(k) or {'1': 1}
        for iname, iid in insts.items():
            lines.append('S %x %x %d %d %s/%s' % (v['serviceId'], iid, v['version']['major'], v['version']['minor'], k.rsplit('.', 1)[-1], iname))
            for fname, f in v['fields'].items():
                g, s, n = f.get('getter'), f.get('setter'), f.get('notifier')
                val = bytes.fromhex(over[fname]) if fname in over else ser.default(f['dataRef'])[0]
                lines.append('F %s %s %s %s %s %s' % ('-' if not g else g['id'], '-' if not s else s['id'], '-' if not n else '%x' % n['id'],
                                                      '-' if not n else n['eventgroups'][0], val.hex() or '-', fname))
    open(dst, 'w').write('\n'.join(lines) + '\n')

if __name__ == '__main__': main()

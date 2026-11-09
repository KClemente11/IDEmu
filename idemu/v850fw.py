"""Firmware do microcontrolador IOC (V850 / RH850) e tabelas de gateway que a PSdZData traz nos pacotes SWFL da NBT Evo.

Tudo isso foi achado por engenharia reversa (ver docs/V850_FIRMWARE.md):

* os pacotes SWFL têm, além dos arquivos do QNX, blocos com `Tag=IOC_FLASH` (aplicação do IOC) e `Tag=GATEWAY_FLASH`
  (tabela do gateway), cada um com `Address=` (endereço na flash do V850) e `SEL_HWINDEX=` (revisão de hardware em que vale);
* `swfl_0000271a` = aplicação do iDrive 5/6 (`v850ApplicationFlash` e `rh850ApplicationFlash`), `swfl_0000271f` = tabela do
  gateway (`v850GWTableFlash` / `rh850GWTableFlash`), `swfl_00002734` = aplicação da versão RSE (`v850ApplicationRseFlash`);
* as imagens são código em claro (sem criptografia); as strings dão identificação, nomes dos canais do `io-ipc` e versões.

Uso:  python3 -m idemu.v850fw <pasta da PSdZData> [--extract PASTA] [--json arquivo]
"""
import glob
import hashlib
import json
import os
import re
import sys

from . import swfl

IOC_TAGS = ('IOC_FLASH', 'GATEWAY_FLASH')
# pacote -> papel (ids estáveis entre versões; conferido em 001_056_001, 007_039_008 e 007_051_002)
PACKAGES = {'0000271a': 'app', '0000271f': 'gateway', '00002734': 'rse'}


def hw_range(spec):
    """'2-3' -> (2, 3); '4-*' -> (4, None); '3' -> (3, 3). None = sem limite."""
    if not spec:
        return (0, None)
    a, _, b = spec.partition('-')
    lo = int(a, 10)
    if not _:
        return (lo, lo)
    return (lo, None if b in ('*', '') else int(b, 10))


def hw_matches(spec, index):
    lo, hi = hw_range(spec)
    return index >= lo and (hi is None or index <= hi)


def family(name):
    """'rh850ApplicationFlash' -> 'RH850'; 'v850GWTableFlash' -> 'V850'."""
    return 'RH850' if name.lower().startswith('rh850') else 'V850'


def find_blocks(path):
    """Blocos IOC/gateway de um pacote .bin: lista de dicts (name, tag, address, hwindex, size, offset)."""
    out = []
    with open(path, 'rb') as f:
        for meta, txt, off, ln, idx in swfl.records_fh(f, path):
            if meta.get('Tag') in IOC_TAGS:
                out.append({'name': meta.get('Name', ''), 'tag': meta['Tag'], 'address': int(meta.get('Address', '0'), 16),
                            'hwindex': meta.get('SEL_HWINDEX', ''), 'size': ln, 'offset': off})
    return out


def read_block(path, blk):
    with open(path, 'rb') as f:
        f.seek(blk['offset'])
        return f.read(blk['size'])


def find_packages(psdz):
    """{papel: [(versão, caminho), ...]} das versões presentes (mais novas por último)."""
    base = None
    for c in (os.path.join(psdz, 'swe', 'swfl'), os.path.join(psdz, 'psdzdata', 'swe', 'swfl'), psdz):
        if os.path.isdir(c):
            base = c
            break
    res = {}
    if not base:
        return res
    for pid, role in PACKAGES.items():
        found = []
        for p in glob.glob(os.path.join(base, 'swfl_%s.bin.*' % pid)):
            g = swfl.parse_name(p)
            if g:
                found.append((g[3], p))
        res[role] = sorted(found)
    return res


# --- identificação pelas strings --------------------------------------------------------------

_DATE = rb'[A-Z][a-z]{2} [ 0-9][0-9] [0-9]{4}'


def _s(b):
    return b.decode('latin1')


def identity(data):
    """Identificação de uma imagem de aplicação (strings embutidas). Campos ausentes ficam de fora."""
    d = {}
    m = re.search(rb'([0-9]{4}_APPL)\x00', data)
    if m:
        d['appl'] = _s(m.group(1))
    m = re.search(rb'(' + _DATE + rb')\x00([0-9]{2}:[0-9]{2}:[0-9]{2})\x00', data)
    if m:
        d['build'] = '%s %s' % (_s(m.group(1)), _s(m.group(2)))
    else:
        m = re.search(rb'\x00(' + _DATE + rb')\x00', data)
        if m:
            d['build'] = _s(m.group(1))
    m = re.search(rb'(cbuild_[A-Za-z0-9]+)\x00', data)
    if m:
        d['builder'] = _s(m.group(1))
    m = re.search(rb'(Headunit [A-Z][0-9]|RSE [A-Z][0-9])\x00', data)
    if m:
        d['device'] = _s(m.group(1))
    vers = []
    for m in re.finditer(rb'(D(?:V850|RH850)[A-Za-z0-9]{3}x{5}V[0-9]{3})\x00', data):
        v = _s(m.group(1))
        if v not in vers:
            vers.append(v)
    if vers:
        d['bootloader_ids'] = vers
    comps = []
    for m in re.finditer(rb'(' + _DATE + rb')\x00(BMW [A-Za-z0-9 ]+)\x00(V[0-9]+\.[0-9]+\.[0-9]+)\x00', data):
        comps.append({'name': _s(m.group(2)), 'version': _s(m.group(3)), 'date': _s(m.group(1))})
    if comps:
        d['components'] = comps
    i = data.find(b'DiagCore')                       # "V000-000-000-00000" vem antes; o da base do gateway vem depois das listas do roteador
    m = re.search(rb'(V[0-9]{3}-[0-9]{3}-[0-9]{3}-[0-9]{5})\x00', data[max(i, 0):])
    if m:
        d['gateway_data'] = _s(m.group(1))
    m = re.search(rb'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})\x00([A-Za-z-]+)\x00(K2L Composer/[A-Za-z ]+)\x00', data)
    if m:
        d['gateway_data_built'] = {'when': _s(m.group(1)), 'by': _s(m.group(2)), 'tool': _s(m.group(3))}
    m = re.search(rb'-------- (BIOSControl [A-Z0-9]+) --------', data)
    if m:
        d['bios_control'] = _s(m.group(1))
    parts = sorted(set(_s(x) for x in re.findall(rb'(UPD70F[0-9]{4})\x00', data)))
    if parts:
        d['device_ids'] = parts
    return d


def ipc_channels(data):
    """Nomes de canais/filas do `io-ipc` que o firmware registra (IpcXxx e cfXxx), na ordem da tabela (sem duplicar)."""
    seen = []
    head = data[:data.find(b'm2Handle') + 8] if b'm2Handle' in data else data[:0x4000]
    for m in re.finditer(rb'(?<=\x00)((?:Ipc|cf)[A-Za-z0-9_]{2,40})(?=\x00)', head):
        n = _s(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def embedded_script_lines(data, limit=40):
    """Linhas de texto do roteiro de inicialização embutido ("// set Fan PWM to 7000", "P 12 20 0200"...)."""
    out = []
    for m in re.finditer(rb'(?:^|[\x00\r\n])((?://[ -~]{4,80})|(?:[A-Z] [0-9A-Fa-f]{2}(?: [0-9A-Fa-f]{1,8}){1,4}))(?=[\x00\r\n])', data):
        out.append(_s(m.group(1)))
        if len(out) >= limit:
            break
    return out


def gw_info(data):
    """Resumo da tabela do gateway (640 KB de flash, o que sobra é 0xFF)."""
    used = [i for i in range(0, len(data), 0x1000) if data[i:i + 0x1000].count(0xff) != len(data[i:i + 0x1000])]
    last = max((i for i in range(len(data) - 1, -1, -1) if data[i] != 0xff), default=-1)
    return {'size': len(data), 'header': data[:16].hex(), 'pages_4k_used': len(used), 'pages_4k': (len(data) + 0xfff) // 0x1000,
            'last_data_offset': last, 'sha1': hashlib.sha1(data).hexdigest()}


def describe_block(name, data):
    d = {'family': family(name), 'size': len(data), 'sha1': hashlib.sha1(data).hexdigest()}
    if 'GWTable' in name:
        d['gateway_table'] = gw_info(data)
    else:
        d['identity'] = identity(data)
        d['ipc_channels'] = ipc_channels(data)
    return d


def scan(psdz, versions=None, extract=None, log=lambda s: None):
    """Lê os pacotes da PSdZData e devolve {'packages': {papel: {versão: [blocos]}}}.
    `versions`: lista de versões (p.ex. ['007_051_002']); padrão = a mais nova de cada papel. `extract`: pasta onde gravar os blocos."""
    res = {'packages': {}}
    for role, found in find_packages(psdz).items():
        pick = [x for x in found if (not versions or x[0] in versions)]
        if not versions and pick:
            pick = [pick[-1]]
        for ver, path in pick:
            blocks = []
            for blk in find_blocks(path):
                data = read_block(path, blk)
                b = dict(blk, **describe_block(blk['name'], data))
                b.pop('offset', None)
                blocks.append(b)
                if extract:
                    os.makedirs(extract, exist_ok=True)
                    with open(os.path.join(extract, '%s.%s.bin' % (blk['name'], ver)), 'wb') as o:
                        o.write(data)
                log('%s %s %s: %d bytes' % (role, ver, blk['name'], len(data)))
            if blocks:
                res['packages'].setdefault(role, {})[ver] = {'file': os.path.basename(path), 'blocks': blocks}
    return res


DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'v850_firmware.json')


def known():
    """Dados já extraídos da PSdZData (idemu/data/v850_firmware.json, gerado por `python3 -m idemu.v850fw <PSdZData> --json ...`).
    Dict vazio se o arquivo não existir."""
    try:
        with open(DATA) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def summary(data=None):
    """Resumo compacto para a API (`GET /api/v850`, chave `firmware`): variantes de hardware, versões e nomes de canais."""
    data = known() if data is None else data
    out = {'variants': [], 'ipc_channels': [], 'gateway_table': None}
    for role, vers in sorted((data.get('packages') or {}).items()):
        for ver, pk in sorted(vers.items()):
            for b in pk['blocks']:
                ident = b.get('identity') or {}
                if 'gateway_table' in b:
                    g = b['gateway_table']
                    out['gateway_table'] = {'package': pk['file'], 'size': g['size'], 'pages_used': g['pages_4k_used'], 'pages': g['pages_4k'],
                                            'sha1': g['sha1'][:12], 'address': b['address']}
                    continue
                out['variants'].append({'role': role, 'package': pk['file'], 'name': b['name'], 'family': b['family'], 'hwindex': b['hwindex'],
                                        'address': b['address'], 'size': b['size'], 'appl': ident.get('appl'), 'device': ident.get('device'),
                                        'build': ident.get('build'), 'components': ident.get('components', [])})
                for n in b.get('ipc_channels', []):
                    if n not in out['ipc_channels']:
                        out['ipc_channels'].append(n)
    return out


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 2
    psdz, extract, out = argv[0], None, None
    if '--extract' in argv:
        extract = argv[argv.index('--extract') + 1]
    if '--json' in argv:
        out = argv[argv.index('--json') + 1]
    res = scan(psdz, extract=extract, log=lambda s: sys.stderr.write(s + '\n'))
    txt = json.dumps(res, indent=1, sort_keys=True)
    if out:
        with open(out, 'w') as o:
            o.write(txt + '\n')
    else:
        print(txt)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

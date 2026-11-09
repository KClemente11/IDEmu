"""Decodificador de VIN: transforma o número do chassi no carro virtual (geração do iDrive, série, chassi, marca, ano, mercado).

O que o VIN traz (ISO 3779 e o padrão da BMW):
  1–3  fabricante (WMI): WBA = BMW AG, WBS = BMW M, WBY = BMW i, WMW = MINI, SCA = Rolls-Royce, 5UX/5YM = BMW EUA...
  4–7  código do tipo do veículo ("Typschlüssel", ex. 8E31): chassi, carroceria, motor, tração, direção e mercado
  8    restrição/airbag, 9 dígito verificador (obrigatório só na América do Norte), 10 ano-modelo, 11 fábrica, 12–17 número de série.

A tabela de tipos não vai no repositório: ela é lida da base KIS da sua PSdZData (kiswb/<série>/KIS.data, tabela FAHRZEUGTYP, banco HSQLDB) e
guardada em cache/vin_types.json na primeira consulta (cerca de 1 minuto para ~4.800 tipos).

O VIN não traz a lista de opcionais do carro (o "FA"): o tipo de head unit (Professional, Business ou EntryNav) continua sendo escolha do usuário."""
import glob, json, mmap, os, re, struct, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache', 'vin_types.json')
VIN_RE = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')

WMI = {'WBA': ('bmw', 'BMW AG (Alemanha)'), 'WBS': ('bmw_m', 'BMW M GmbH'), 'WBY': ('bmw_i', 'BMW i'), 'WBX': ('bmw', 'BMW AG (SAV)'), 'WMW': ('mini', 'MINI'),
       'WMZ': ('mini', 'MINI (Countryman/Paceman)'), 'SCA': ('rr', 'Rolls-Royce'), '5UX': ('bmw', 'BMW Manufacturing (EUA, X)'), '5UJ': ('bmw', 'BMW Manufacturing (EUA)'),
       '5YM': ('bmw_m', 'BMW Manufacturing (EUA, X M)'), '4US': ('bmw', 'BMW Manufacturing (EUA)'), '3MW': ('bmw', 'BMW México'), '3MF': ('bmw_m', 'BMW M México'),
       'LBV': ('bmw', 'BMW Brilliance (China)'), 'X4X': ('bmw', 'Avtotor (Rússia)'), 'MMB': ('bmw', 'BMW (Tailândia/Malásia)'), 'NC0': ('bmw', 'BMW África do Sul'),
       'WB1': ('moto', 'BMW Motorrad'), 'WB3': ('moto', 'BMW Motorrad'), 'WB4': ('moto', 'BMW Motorrad'), 'WB5': ('bmw', 'BMW AG'), 'WB8': ('bmw', 'BMW AG')}
YEAR_CODES = 'ABCDEFGHJKLMNPRSTVWXY'           # 2010..2030 (I, O, Q, U, Z e 0 não são usados)
BODY = {'LIM': 'sedã', 'TOU': 'Touring (perua)', 'COU': 'cupê', 'CAB': 'conversível', 'SAV': 'SUV', 'SAC': 'SUV cupê', 'SAT': 'SUV/Touring', 'HAT': 'hatch',
        'SHA': 'Gran Coupé/hatch', 'CLU': 'Clubman', 'MPV': 'monovolume', 'ROA': 'roadster'}
DRIVE = {'RWD': 'tração traseira', 'AWD': 'tração integral (xDrive/ALL4)', 'FWD': 'tração dianteira'}
GEARBOX = {'A': 'automático', 'M': 'manual', 'X': 'manual ou automático'}
BRAND_KIS = {'BM': 'bmw', 'MI': 'mini', 'RR': 'rr', 'BI': 'bmw_i'}
# Chassis por geração do iDrive (a partir do ano-modelo quando a série mudou de central no meio da vida).
ID8 = {'I20', 'G60', 'G61', 'G68', 'G70', 'G73', 'G45', 'G48', 'G90', 'G99', 'U06', 'U10', 'U11', 'U12', 'U25', 'F65', 'F66', 'F67', 'F70', 'F74', 'J01', 'J05'}
ID8_FROM = {'G20': 2023, 'G21': 2023, 'G22': 2024, 'G23': 2024, 'G26': 2022, 'G80': 2024, 'G81': 2024, 'G82': 2024, 'G83': 2024, 'G87': 2024, 'G05': 2024,
            'G06': 2024, 'G07': 2023, 'G09': 2023, 'G18': 2024, 'I12': 9999, 'F95': 2024, 'F96': 2024}
ID7_ALWAYS = {'G05', 'G06', 'G07', 'G09', 'G14', 'G15', 'G16', 'G18', 'G20', 'G21', 'G22', 'G23', 'G26', 'G28', 'G29', 'G42', 'G80', 'G81', 'G82', 'G83', 'G87',
              'F40', 'F44', 'F91', 'F92', 'F93', 'F95', 'F96', 'G08', 'G38'}
ID7_FROM = {'G01': 2020, 'G02': 2020, 'G11': 2020, 'G12': 2020, 'G30': 2020, 'G31': 2020, 'G32': 2020, 'F90': 2020, 'F97': 2020, 'F98': 2020,
            'F39': 2021, 'F45': 2022, 'F46': 2022, 'F48': 2021, 'F49': 2021, 'F52': 2021}

_lock = threading.Lock()
_state = {'state': 'idle', 'error': None, 'pct': 0}
_types = None


# ------------------------------------------------------------------------------------------------ tabela de tipos (KIS)
_ROW = re.compile(rb'\x01\x00\x00\x00\x04([0-9A-Z]{4})\x01(....)\x00\x01(....)([A-Z_]+=)', re.S)

def read_kis(path):
    """{código do tipo: {campo: valor}} de um KIS.data (HSQLDB, tabela FAHRZEUGTYP: NAME, EBR, BESCHREIBUNG (nula), TYPMERKMALE "CHAVE=valor;...")."""
    out = {}
    with open(path, 'rb') as f:
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for x in _ROW.finditer(m):
                n = struct.unpack('>I', x.group(3))[0]
                if n > 4000: continue
                t = m[x.end(3):x.end(3) + n].decode('utf-8', 'replace')
                kv = dict(a.split('=', 1) for a in t.split(';') if '=' in a)
                if kv.get('EBR'): out[x.group(1).decode()] = kv
        finally: m.close()
    return out

def build_table(psdz, progress=lambda p: None):
    files = sorted(glob.glob(os.path.join(psdz, 'kiswb', '*', 'KIS.data')))
    if not files: raise ValueError('a PSdZData não tem a base KIS (pasta kiswb): ela é necessária para decodificar o VIN')
    keep = ('EBR', 'MARKE', 'KFORM', 'MOT', 'ANTR', 'LENK', 'AUSF', 'GETR', 'HUBR', 'ZYL', 'MLAND', 'MSPORT', 'HYB', 'ELEKTRO')
    types = {}
    for i, f in enumerate(files):
        for k, kv in read_kis(f).items():
            types[k] = {c: kv[c] for c in keep if kv.get(c)}
            types[k]['ms'] = os.path.basename(os.path.dirname(f))
        progress(int(100 * (i + 1) / len(files)))
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + '.new'
    with open(tmp, 'w') as fh: json.dump({'version': 1, 'psdz': psdz, 'built': time.time(), 'types': types}, fh, separators=(',', ':'))
    os.replace(tmp, CACHE)
    return types

def table_status():
    if _types is not None or os.path.isfile(CACHE): return {'state': 'ready', 'pct': 100, 'error': None}
    return dict(_state)

def load_types(psdz=None, wait=False):
    """Tabela de tipos (do cache ou da PSdZData). Sem cache: começa a montar em segundo plano e devolve None (ou espera, com wait=True)."""
    global _types
    if _types is not None: return _types
    if os.path.isfile(CACHE):
        try:
            with open(CACHE) as f: _types = json.load(f)['types']
            return _types
        except Exception: pass
    if not psdz: raise ValueError('configure a pasta da PSdZData para decodificar o VIN')
    with _lock:
        if _state['state'] != 'building':
            _state.update(state='building', error=None, pct=0)
            def run():
                global _types
                try: _types = build_table(psdz, progress=lambda p: _state.update(pct=p)); _state.update(state='ready', pct=100)
                except Exception as e: _state.update(state='error', error=str(e))
            t = threading.Thread(target=run, daemon=True); t.start()
        else: t = None
    if wait:
        while _state['state'] == 'building': time.sleep(0.2)
        if _state['state'] == 'error': raise ValueError(_state['error'])
        return _types
    return None


# ------------------------------------------------------------------------------------------------ decodificação
def check_digit(vin):
    """Dígito verificador (posição 9) do padrão norte-americano; carros de outros mercados nem sempre o usam."""
    tr = {c: v for v, cs in enumerate(['0', '1AJ', '2BKS', '3CLT', '4DMU', '5ENV', '6FPW', '7GRX', '8HY', '9IZ']) for c in cs}
    w = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
    s = sum(tr.get(c, 0) * w[i] for i, c in enumerate(vin)) % 11
    return 'X' if s == 10 else str(s)

def model_year(c):
    if c in YEAR_CODES: return 2010 + YEAR_CODES.index(c)
    if c.isdigit() and c != '0': return 2000 + int(c)
    return None

def chassis_code(ebr, known=None):
    """EBR da KIS -> código de chassi do HMI (F06M6 -> F06, F04LK -> F04, RR4EWB -> RR04)."""
    if not ebr: return ''
    if known and ebr in known: return ebr
    m = re.match(r'^(RR)(\d)(?:EWB)?$', ebr)
    if m: return 'RR%02d' % int(m.group(2))
    return ebr[:3] if re.match(r'^[A-Z]\d\d', ebr) else ebr

def generation(chassis, year):
    """Geração do iDrive provável para o chassi e o ano-modelo: 'id4' (CIC), 'id5'/'id6' (NBT Evo), 'id7' (MGU), 'id8' (MGU22) ou None."""
    from . import catalog
    y = year or 0
    if chassis in ID8 or (chassis in ID8_FROM and y >= ID8_FROM[chassis]): return 'id8'
    if chassis in ID7_ALWAYS or (chassis in ID7_FROM and y >= ID7_FROM[chassis]): return 'id7'
    if any(chassis in chs for _, chs, _ in catalog.SERIES_INFO.values()):
        return 'id6' if y >= 2018 else 'id5'                 # ano-modelo 2018 = produção a partir de 07/2017 (iDrive 6); antes, iDrive 5 (NBT Evo ID5/ID4)
    if re.match(r'^E\d\d', chassis or '') or (y and y <= 2012): return 'id4'
    return None

def series_of(chassis):
    from . import catalog
    for sid, (_, chs, _) in catalog.SERIES_INFO.items():
        if chassis in chs: return sid
    return None

def decode(vin, psdz=None, wait=False):
    from . import catalog, codegen
    v = (vin or '').strip().upper().replace(' ', '')
    if not VIN_RE.match(v):
        raise ValueError('VIN inválido: são 17 letras e números, sem I, O e Q' if len(v) == 17 else 'VIN inválido: são 17 caracteres (você digitou %d)' % len(v))
    brand_w, maker = WMI.get(v[:3], (None, 'Fabricante desconhecido (%s)' % v[:3]))
    year = model_year(v[9]); tkey = v[3:7]
    out = {'vin': v, 'wmi': v[:3], 'maker': maker, 'type_key': tkey, 'model_year': year, 'plant': v[10], 'serial': v[11:],
           'check_digit_ok': check_digit(v) == v[8], 'table': table_status(), 'found': False, 'notes': []}
    if brand_w == 'moto': raise ValueError('esse VIN é de uma moto BMW (Motorrad): o IDEmu emula as centrais dos carros')
    types = load_types(psdz or catalog.load_settings().get('psdz_path'), wait=wait)
    out['table'] = table_status()
    t = (types or {}).get(tkey)
    known = set(codegen.enum_values('BAUREIHE'))
    if t:
        ch = chassis_code(t.get('EBR'), known)
        brand = BRAND_KIS.get(t.get('MARKE'), brand_w or 'bmw')
        if brand == 'bmw' and brand_w in ('bmw_m', 'bmw_i'): brand = brand_w if brand_w == 'bmw_i' else 'bmw'
        hub = t.get('HUBR')
        engine = ' '.join(x for x in [t.get('MOT', '')[:3], ('%.1f l' % (int(hub) / 1000.0)).replace('.', ',') if hub and hub.isdigit() and int(hub) > 0 else '',
                                      ('%s cil.' % t['ZYL']) if t.get('ZYL') and t['ZYL'] != '0' else ''] if x)
        if t.get('ELEKTRO') and t['ELEKTRO'] not in ('NOEL', ''): engine = (engine + ' · elétrico').strip(' ·')
        out.update(found=True, chassis=ch, chassis_name=catalog.CHASSIS_NAMES.get(ch, ch), brand=brand, ebr=t.get('EBR'),
                   body=BODY.get(t.get('KFORM'), t.get('KFORM') or ''), engine=engine, engine_code=t.get('MOT', ''), drive=DRIVE.get(t.get('ANTR'), t.get('ANTR') or ''),
                   gearbox=GEARBOX.get(t.get('GETR'), ''), steering='direita' if t.get('LENK') == 'RL' else 'esquerda', market='EUA/Canadá' if t.get('AUSF') == 'US' else 'Europa e resto do mundo',
                   us=t.get('AUSF') == 'US', m_sport=t.get('MSPORT') == 'MS', kis_series=t.get('ms'))
    elif types is None:
        out['notes'].append('A tabela de tipos está sendo montada a partir da sua PSdZData (cerca de 1 minuto). Tente de novo em instantes.')
        return out
    else:
        out['notes'].append('O código de tipo %s não está na base KIS da sua PSdZData (carro mais antigo que a série F ou de outra marca).' % tkey)
        out['brand'] = brand_w or 'bmw'
    out['generation'] = generation(out.get('chassis', ''), year)
    out['series'] = series_of(out.get('chassis', ''))
    out['env'] = suggest_env(out)
    return out

def suggest_env(d):
    """Parâmetros do ambiente que reproduzem o carro do VIN (para o assistente e para aplicar a um ambiente existente)."""
    from . import catalog
    gen = d.get('generation'); y = d.get('model_year') or 2017
    us = d.get('us')
    coding = {'vin': d['vin'], 'year': max(2012, min(2022, y - 1)), 'month': 7, 'lci': 1}
    if us: coding.update(language='en_US', country='US', units='imperial')
    if gen in ('id5', 'id6'):
        coding['hmi_version'] = 'id6_light' if gen == 'id6' else 'id5'
        coding['hu_variant'] = 'professional'
        coding['display'] = catalog.hu_variant('professional')['display']
        coding['navi'] = 'us' if us else 'ece'
    name = ' '.join(x for x in [d.get('chassis'), d.get('chassis_name') if d.get('chassis_name') != d.get('chassis') else '', str(y) if d.get('model_year') else ''] if x)
    return {'generation': gen, 'series': d.get('series'), 'chassis': d.get('chassis'), 'brand': d.get('brand'), 'name': name,
            'model_name': ' · '.join(x for x in [d.get('body'), d.get('engine')] if x), 'coding': coding}

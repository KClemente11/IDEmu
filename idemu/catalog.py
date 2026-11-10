"""Catálogo do PSDZData: séries, chassis, pacotes SWFL necessários e versões disponíveis."""
import os, re, json, glob, shutil, sys, tempfile
from . import codegen

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.abspath(os.environ.get('IDEMU_STATE_DIR') or ROOT_DIR)
SETTINGS = os.path.join(STATE_DIR, 'settings.json')
WSL = bool(os.environ.get('IDEMU_WSL'))
NATIVE_BIN = os.path.join(ROOT_DIR, 'bin', 'windows')

def native_evo_ready():
    return sys.platform == 'win32' and all(
        os.path.isfile(os.path.join(NATIVE_BIN, name))
        for name in ('qemu-system-arm.exe', 'glhost.exe')
    )

def native_cic_ready():
    return sys.platform == 'win32' and os.path.isfile(os.path.join(NATIVE_BIN, 'qemu-system-sh4.exe'))

def runtime_root():
    return os.path.join(STATE_DIR, 'run') if sys.platform == 'win32' else '/tmp/idemu-%d' % os.getuid()

def load_settings():
    paths = [SETTINGS]
    if WSL and STATE_DIR != ROOT_DIR:
        paths.append(os.path.join(ROOT_DIR, 'settings.json'))
    for path in paths:
        try:
            with open(path) as f: return json.load(f)
        except FileNotFoundError:
            continue
        except (ValueError, OSError):
            return {}
    defaults = ((r'C:\BMW\PSdZData',) if sys.platform == 'win32' else
                ('/mnt/c/BMW/PSdZData', os.path.expanduser('~/IDEmu')) if WSL else ())
    for default in defaults:
        if psdz_ok(default):
            return {'psdz_path': default}
    return {}

def save_settings(d):
    s = load_settings(); s.update(d)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SETTINGS, 'w') as f: json.dump(s, f, indent=1)

# Séries com NBT Evo (iDrive 5/6) e os chassis de cada uma, conferidos na base KIS da PSdZData (kiswb/<série>/KIS.data, campo EBR dos tipos de veículo).
SERIES_INFO = {
    'F001': ('Série 7 (F01/F02/F03) e Rolls-Royce Ghost', ['F01', 'F02', 'F03', 'RR04'], 'bmw'),
    'F010': ('Série 5/6 (F06/F07/F10/F11/F12/F13/F18)', ['F06', 'F07', 'F10', 'F11', 'F12', 'F13', 'F18'], 'bmw'),
    'F020': ('Série 1/2/3/4, M2/M3/M4 (F2x/F3x/F8x)', ['F20', 'F21', 'F22', 'F23', 'F30', 'F31', 'F32', 'F33', 'F34', 'F35', 'F36', 'F80', 'F82', 'F83', 'F87'], 'bmw'),
    'F025': ('X3/X4/X5/X6, X5 M/X6 M (F15/F16/F25/F26/F85/F86)', ['F15', 'F16', 'F25', 'F26', 'F85', 'F86'], 'bmw'),
    'F056': ('X1/X2/Série 2 Active e Gran Tourer, MINI (F39/F4x/F5x/F60)', ['F39', 'F45', 'F46', 'F48', 'F49', 'F52', 'F54', 'F55', 'F56', 'F57', 'F60'], 'bmw'),
    'I001': ('BMW i3 e i8 (I01/I12/I15)', ['I01', 'I12', 'I15'], 'bmw_i'),
    'S15A': ('Série 5/6 GT/7, X3/X4, M5 e Rolls-Royce (G01/G02/G11/G12/G30/G31/G32/F90)', ['G01', 'G02', 'G11', 'G12', 'G30', 'G31', 'G32', 'F90', 'F97', 'F98', 'RR11', 'RR12', 'RR31'], 'bmw'),
}
CHASSIS_BRAND = {'F54': 'mini', 'F55': 'mini', 'F56': 'mini', 'F57': 'mini', 'F60': 'mini', 'I01': 'bmw_i', 'I12': 'bmw_i', 'I15': 'bmw_i',
                 'RR04': 'rr', 'RR11': 'rr', 'RR12': 'rr', 'RR31': 'rr'}
CHASSIS_NAMES = {
    'F01': 'Série 7', 'F02': 'Série 7 longo', 'F03': 'Série 7 blindado', 'F06': 'Série 6 Gran Coupé', 'F07': 'Série 5 GT', 'F10': 'Série 5 sedã', 'F11': 'Série 5 Touring',
    'F12': 'Série 6 conversível', 'F13': 'Série 6 cupê', 'F18': 'Série 5 longo (China)', 'F20': 'Série 1 5 portas', 'F21': 'Série 1 3 portas', 'F22': 'Série 2 cupê',
    'F23': 'Série 2 conversível', 'F30': 'Série 3 sedã', 'F31': 'Série 3 Touring', 'F32': 'Série 4 cupê', 'F33': 'Série 4 conversível', 'F34': 'Série 3 GT',
    'F35': 'Série 3 longo (China)', 'F36': 'Série 4 Gran Coupé', 'F80': 'M3 sedã', 'F82': 'M4 cupê', 'F83': 'M4 conversível', 'F87': 'M2 cupê',
    'F15': 'X5', 'F16': 'X6', 'F25': 'X3', 'F26': 'X4', 'F85': 'X5 M', 'F86': 'X6 M', 'F39': 'X2', 'F45': 'Série 2 Active Tourer', 'F46': 'Série 2 Gran Tourer',
    'F48': 'X1', 'F49': 'X1 longo (China)', 'F52': 'Série 1 sedã (China)', 'F54': 'MINI Clubman', 'F55': 'MINI 5 portas', 'F56': 'MINI 3 portas',
    'F57': 'MINI conversível', 'F60': 'MINI Countryman', 'I01': 'i3', 'I12': 'i8 cupê', 'I15': 'i8 Roadster', 'G01': 'X3', 'G02': 'X4', 'G11': 'Série 7',
    'G12': 'Série 7 longo', 'G30': 'Série 5 sedã', 'G31': 'Série 5 Touring', 'G32': 'Série 6 GT', 'F90': 'M5', 'F97': 'X3 M', 'F98': 'X4 M',
    'RR04': 'Rolls-Royce Ghost', 'RR11': 'Rolls-Royce Phantom', 'RR12': 'Rolls-Royce Phantom longo', 'RR31': 'Rolls-Royce Cullinan'}
def chassis_brand(code, default='bmw'): return CHASSIS_BRAND.get(code, default)
NAVI_NAMES = {'keine_navi': 'Sem navegação', 'ece': 'Europa e resto do mundo (ECE)', 'us': 'América do Norte (US)', 'japan': 'Japão', 'china': 'China', 'korea': 'Coreia do Sul',
              'hongkong': 'Hong Kong', 'taiwan': 'Taiwan', 'navi_vorbereitung': 'Preparação para navegação', 'tv_ohne_navi': 'TV sem navegação',
              'permanente_sli_anzeige_ece': 'Sem navegação, com limite de velocidade (ECE)'}
# Tipos de head unit que o IDEmu monta sobre o firmware do NBT Evo (a PSdZData só traz o firmware do HU_NBTEVO; o EntryNav e o Business são reproduzidos pela
# codificação: tamanho e resolução do display, navegação e toque, como nos carros que saíam com essas unidades).
HU_VARIANTS = [
    {'id': 'professional', 'name': 'Navigation Professional', 'sub': 'NBT Evo · display de 10,25" 1440 × 540 · navegação · tela de toque',
     'display': '10_25_1440x540', 'navi': True, 'touch': True},
    {'id': 'business', 'name': 'Navigation Business', 'sub': 'Display de 8,8" 1280 × 480 · navegação · tela de toque',
     'display': '8_8_1280x480', 'navi': True, 'touch': True},
    {'id': 'entrynav', 'name': 'EntryNav', 'sub': 'Display de 6,5" 800 × 480 · navegação · sem tela de toque (só o controlador)',
     'display': '6_5_800x480', 'navi': True, 'touch': False},
]
def hu_variant(vid): return next((v for v in HU_VARIANTS if v['id'] == vid), None)
ROLE_TEXT = {
    'os': ('Sistema base (QNX, serviços, drivers, boot)', 'Contém o IFS de boot e o sistema de arquivos da head unit (bin, lib, etc, opt/sys...).'),
    'brand': ('Dados da marca (temas, widgets, textos)', 'Recursos visuais e de conteúdo da marca selecionada (BMW, MINI, Rolls-Royce).'),
    'hmi': ('Interface (HmiMain3D e dados comuns)', 'Executável do iDrive, shaders, fontes, modelos 3D do carro e dados comuns.'),
}
BRAND_SWFL = {'bmw': '00002719', 'bmw_i': '00002719', 'bmw_m': '00002719', 'mini': '00002716', 'rr': '00002718'}
OS_SWFL, HMI_SWFL = '0000271a', '00002720'
LANGS = [('pt_BR', 'Português (Brasil)'), ('pt_PT', 'Português (Portugal)'), ('en_GB', 'English (UK)'), ('en_US', 'English (US)'),
         ('de_DE', 'Deutsch'), ('es_ES', 'Español'), ('fr_FR', 'Français'), ('it_IT', 'Italiano'), ('nl_NL', 'Nederlands'),
         ('pl_PL', 'Polski'), ('ru_RU', 'Русский'), ('tr_TR', 'Türkçe'), ('ja_JP', '日本語'), ('ko_KR', '한국어'), ('zh_CN', '中文(简体)')]
COUNTRIES = [('BR', 'Brasil'), ('PT', 'Portugal'), ('DE', 'Alemanha'), ('GB', 'Reino Unido'), ('US', 'Estados Unidos'), ('ES', 'Espanha'),
             ('FR', 'França'), ('IT', 'Itália'), ('JP', 'Japão'), ('CN', 'China'), ('KR', 'Coreia do Sul')]
DISPLAYS = [('10_25_1440x540', '10,25" 1440x540 (padrão iDrive 6)'), ('8_8_1280x480', '8,8" 1280x480'), ('6_5_800x480', '6,5" 800x480')]

def psdz_ok(path):
    return bool(path) and os.path.isdir(os.path.join(path, 'swe', 'swfl')) and os.path.isdir(os.path.join(path, 'mainseries'))

def swfl_files(psdz, sid):
    out = []
    for p in sorted(glob.glob(os.path.join(psdz, 'swe', 'swfl', 'swfl_%s.bin.*' % sid))):
        m = re.search(r'\.bin\.(\d{3}_\d{3}_\d{3})$', p)
        out.append({'file': os.path.basename(p), 'version': m.group(1) if m else '', 'size': os.path.getsize(p), 'path': p})
    out.sort(key=lambda f: f['version'], reverse=True)
    return out

def series_available(psdz):
    res = []
    for sid in sorted(SERIES_INFO):
        d = glob.glob(os.path.join(psdz, 'mainseries', sid, '*', 'odx', 'src', 'odx-f', 'HU_NBTEVO.odx-f'))
        if d: res.append(sid)
    return res

APPROX_MB = {'0000271a': 880, '00002720': 710, '00002719': 480}
# Nível de funcionalidade de cada versão do iDrive no IDEmu. Estados: full (funciona), half (funciona em parte) e none (não funciona).
# Cada versão traz a nota do que falta; o percentual é a média (full = 1, half = 0,5, none = 0). Fontes: docs/OUTRAS_GERACOES.md, docs/TOQUE.md, docs/CELULAR.md, docs/PENDRIVE.md.
FEATURES = [('screen', 'Tela e interface real do HMI'), ('touch', 'Toque na tela'), ('rotor', 'Rotor e botões'), ('can', 'Sinais do carro (CAN)'),
            ('map', 'GPS e mapa'), ('cluster', 'Cluster e HUD'), ('phone', 'Celular conectado'), ('coding', 'Editor de codificação'),
            ('ssh', 'Acesso SSH'), ('media', 'Rádio, mídia e áudio'), ('usb', 'Pen drive'), ('stable', 'Estabilidade')]
LEVEL_NOTES = {
    'id6': {'can': ('half', 'Velocidade, marcha, terminal e estado dos pneus chegam ao HMI; autonomia, tanque e computador de bordo ainda não'), 'cluster': ('half', 'Painel virtual pelo CAN e pelo GPS; o HMI não manda conteúdo a ele'),
            'media': ('none', 'Sem rádio nem fonte de áudio'), 'usb': ('none', 'Sem controlador USB virtual')},
    'id5': {'touch': ('half', 'A tela leva vários segundos para refletir cada toque'), 'rotor': ('half', 'A tela leva vários segundos para refletir cada entrada'),
            'can': ('half', 'Mesma ponte do iDrive 6, menos testada'), 'map': ('none', 'O HMI cai nos menus de navegação; mapa não verificado'),
            'cluster': ('half', 'Painel virtual pelo CAN e pelo GPS; o HMI não manda conteúdo a ele'), 'media': ('none', 'Sem rádio nem fonte de áudio'),
            'usb': ('none', 'Sem controlador USB virtual'), 'stable': ('half', 'O HMI cai de vez em quando')},
    'id7': {'screen': ('half', 'Tela central e do banco traseiro (uma por ambiente); sem mapa, mídia nem dados do carro'), 'rotor': ('half', 'Rotor, setas, MENU, BACK, OPTION, MEDIA e COM funcionam; MAP e NAV não'),
            'can': ('none', 'Sem CAN virtual'), 'map': ('none', 'Sem GPS nem mapa'), 'cluster': ('none', 'Sem cluster nem HUD'), 'phone': ('half', 'Tela e toque; sem GPS'),
            'coding': ('half', 'Edita 1.288 parâmetros e a VM reinicia para aplicar; o efeito depende dos serviços que o HMI ainda não encontra'), 'ssh': ('none', 'Sem acesso SSH'),
            'media': ('none', 'Sem rádio nem áudio'), 'usb': ('none', 'Sem pen drive'), 'stable': ('half', 'O primeiro boot leva cerca de 2 minutos; os seguintes, cerca de 1 segundo')},
    'id4': {'rotor': ('half', 'Rotor, aperto, inclinação, MENU, BACK, OPTION, MEDIA e MAP (rádio) funcionam; NAV e COM não; a tela leva alguns segundos para reagir'), 'touch': ('none', 'O CIC não tem tela de toque'), 'can': ('none', 'Sem CAN virtual'), 'map': ('none', 'Sem GPS nem mapa'), 'cluster': ('none', 'Sem cluster nem HUD'),
            'phone': ('none', 'Sem celular'), 'coding': ('none', 'Sem editor de codificação'), 'ssh': ('none', 'Sem acesso SSH'), 'media': ('none', 'Sem rádio nem áudio'),
            'usb': ('none', 'Sem pen drive'), 'stable': ('half', 'Boot de cerca de 1 minuto, sem boot rápido; vários serviços do carro ausentes')},
    'id8': {'can': ('half', 'Só relógio e temperatura são simulados'), 'map': ('none', 'Sem mapa nem GPS virtual'), 'cluster': ('none', 'Só a tela central é desenhada'),
            'phone': ('half', 'Tela, toque e botões; sem GPS'), 'coding': ('half', 'Edita 1.264 parâmetros e a VM reinicia para aplicar; o efeito depende dos serviços que o HMI ainda não encontra'), 'ssh': ('none', 'Sem acesso SSH'),
            'media': ('none', 'Sem rádio nem áudio'), 'usb': ('none', 'O pen drive ainda não aparece no HMI')},
}

def level_of(gen_id):
    # Nível de funcionalidade de uma geração: {'pct', 'name', 'features': [{'id', 'label', 'state', 'note'}]}.
    notes = LEVEL_NOTES.get(gen_id, {}); feats = []; pts = 0.0
    for fid, label in FEATURES:
        state, note = notes.get(fid, ('full', ''))
        pts += {'full': 1.0, 'half': 0.5}.get(state, 0.0)
        feats.append({'id': fid, 'label': label, 'state': state, 'note': note})
    pct = int(round(100.0 * pts / len(FEATURES)))
    return {'pct': pct, 'name': 'Alto' if pct >= 70 else 'Médio' if pct >= 45 else 'Baixo' if pct >= 25 else 'Mínimo', 'features': feats}

GENERATIONS = [
    {'id': 'id6', 'name': 'iDrive 6', 'sub': 'NBT Evo · 2016–2020 · QNX 6.5', 'hmi_version': 'id6_light', 'supported': True},
    {'id': 'id5', 'name': 'iDrive 5', 'sub': 'NBT / NBT Evo · usa os mesmos arquivos do iDrive 6', 'hmi_version': 'id5', 'supported': True},
    {'id': 'id4', 'name': 'iDrive 4', 'sub': 'CIC High · Harman "BMW L6" · SH-4A + QNX 6.3 · lê os pacotes 3a6 e 417 da PSdZData', 'hmi_version': 'id4', 'supported': True, 'direct': 'cic'},
    {'id': 'id7', 'name': 'iDrive 7', 'sub': 'MGU · Linux x86 · tela central ou do banco traseiro (RSE) · lê os arquivos direto da PSdZData', 'hmi_version': 'id7', 'supported': True, 'direct': 'mgu7'},
    {'id': 'id8', 'name': 'iDrive 8', 'sub': 'MGU22 · Linux ARM64 · BMW i7 G70 · lê os arquivos direto da PSdZData', 'hmi_version': 'id8', 'supported': True, 'direct': 'mgu22'},
]
for _g in GENERATIONS: _g['level'] = level_of(_g['id'])
DIRECT_BACKENDS = {'cic': 'cic', 'mgu7': 'mgu7', 'mgu22': 'mgu'}

def backend_supported(kind):
    if kind is None: return True
    if WSL:
        qemu = os.path.join(ROOT_DIR, 'bin', 'qemu-system-sh4')
        return kind == 'cic' and os.path.isfile(qemu) and os.access(qemu, os.X_OK)
    if sys.platform == 'win32':
        return kind == 'cic' and native_cic_ready()
    return kind in DIRECT_BACKENDS

for _g in GENERATIONS:
    _g['supported'] = backend_supported(_g.get('direct'))
    if _g['id'] == 'id5' and native_evo_ready():
        _g['supported'] = False

def scan_folder(root, wanted, max_depth=7, max_seconds=25):
    # Procura em root arquivos swfl_<id>.bin.<versão> (ids em wanted): raiz do psdzdata, pasta swe/swfl ou qualquer pasta que os contenha.
    # Devolve {id: [arquivos]} (mais novo primeiro) e quantas pastas foram varridas.
    import time as _t
    rx = re.compile(r'^swfl_([0-9a-fA-F]{8})\.bin\.(\d{3}_\d{3}_\d{3})$')
    want = {w.lower() for w in wanted}
    found = {w: [] for w in want}; seen = set()
    root = os.path.abspath(os.path.expanduser(root))
    t_end = _t.time() + max_seconds; scanned = 0
    def add(path):
        n = os.path.basename(path); m = rx.match(n)
        if not m or m.group(1).lower() not in want or path in seen: return
        try: size = os.path.getsize(path)
        except OSError: return
        seen.add(path); found[m.group(1).lower()].append({'file': n, 'version': m.group(2), 'size': size, 'path': path})
    # atalhos prováveis primeiro; depois varredura limitada
    for sub in ('', 'swe/swfl', 'psdzdata/swe/swfl', 'swfl'):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            try:
                for n in os.listdir(d): add(os.path.join(d, n))
            except OSError: pass
    if not any(found.values()):
        stack = [(root, 0)]
        while stack and _t.time() < t_end:
            d, depth = stack.pop(); scanned += 1
            try: ents = list(os.scandir(d))
            except OSError: continue
            for e in ents:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if depth < max_depth and not e.name.startswith('.') and e.name not in ('Library', 'node_modules', 'System', 'Applications'): stack.append((e.path, depth + 1))
                    else: add(e.path)
                except OSError: pass
    for v in found.values(): v.sort(key=lambda f: f['version'], reverse=True)
    return {'files': found, 'scanned': scanned, 'timeout': _t.time() >= t_end}

def build_catalog(psdz):
    ok = psdz_ok(psdz)
    cat = {'psdz_ok': ok, 'series': [], 'roles': [], 'by_series': {}, 'languages': [{'code': c, 'name': n} for c, n in LANGS],
           'countries': [{'code': c, 'name': n} for c, n in COUNTRIES], 'displays': [{'code': c, 'name': n} for c, n in DISPLAYS],
           'hmi_versions': [{'code': c, 'name': n} for c, n in (('id6_light', 'iDrive 6 (tiles)'), ('id6', 'iDrive 6 completo'), ('id5', 'iDrive 5'))],
           'navi': [{'code': c, 'name': NAVI_NAMES.get(c, c)} for c in codegen.enum_values('NAVI_VARIANTE')], 'generations': GENERATIONS, 'hu_variants': HU_VARIANTS}
    baureihe = set(codegen.enum_values('BAUREIHE'))
    sids = series_available(psdz) if ok else sorted(SERIES_INFO)      # sem a pasta psdzdata, o catálogo vem da lista interna
    for sid in sids:
        name, chs, brand = SERIES_INFO[sid]
        cat['series'].append({'id': sid, 'name': name, 'chassis': [{'code': c, 'name': CHASSIS_NAMES.get(c, c), 'brand': chassis_brand(c, brand), 'ego_model': c} for c in chs if not baureihe or c in baureihe]})
        cat['by_series'][sid] = {'roles': {'os': OS_SWFL, 'brand': dict(BRAND_SWFL), 'hmi': HMI_SWFL}}
    brand_names = {'00002719': 'BMW', '00002716': 'MINI', '00002718': 'Rolls-Royce'}
    roles = [('os', OS_SWFL), ('hmi', HMI_SWFL)] + [('brand', i) for i in ('00002719', '00002716', '00002718')]
    for role, sid in roles:
        label, help_ = ROLE_TEXT[role]
        if role == 'brand': label = 'Dados da marca %s (temas, widgets, textos)' % brand_names[sid]
        cat['roles'].append({'role': role, 'id': sid, 'label': label, 'help': help_, 'required': True, 'approx_mb': APPROX_MB.get(sid),
                             'files': swfl_files(psdz, sid) if ok else []})
    cat['brand_files'] = {b: (swfl_files(psdz, s) if ok else []) for b, s in BRAND_SWFL.items()}
    return cat


# ---------------------------------------------------------------- pacotes SWFL exigidos por geração (iDrive 4, 7 e 8)
# O usuário pode apontar a PSdZData inteira, escolher os arquivos um a um ou mandar o app procurar numa pasta.
# Os arquivos escolhidos ficam como links em packages/swe/swfl (o "estágio"), que tem o mesmo formato de uma PSdZData para os montadores.
STAGE = os.path.join(STATE_DIR, 'packages')
MGU22_VER = '007_034_003'
CIC_VERSION = '008_090_002'
CIC_PACKAGES = ('000003a6', '00000417')
MGU7_APP_IDS = '566c 566d 566e 566f 5670 5671 5672 5673 5675 5678 567a'.split()
MGU7_DATA_IDS = '566b 567b 567c 567d 567e 5682 5683'.split()
MGU7_APP_VER = '030_016_002'
MGU7_KERNEL_PKG = '00005684'
MGU7_KERNEL_VER = '036_010_004'
SWFL_RX = re.compile(r'^swfl_([0-9a-fA-F]{8})\.bin\.(\d{3}_\d{3}_\d{3})$')

def required_packages(kind):
    # [{id, version, label, help, role}] dos pacotes que a geração precisa
    if kind == 'cic':
        lab = {'000003a6': ('Sistema do CIC (aplicativos e HMI)', 'os'), '00000417': ('Dados do CIC (mapas, vozes e recursos)', 'data')}
        return [{'id': i, 'version': CIC_VERSION, 'label': lab[i][0], 'role': lab[i][1], 'help': 'Pacote do iDrive 4 (CIC)'} for i in CIC_PACKAGES]
    if kind == 'mgu7':
        out = [{'id': '0000' + i, 'version': MGU7_APP_VER, 'label': 'Aplicativo %s' % i.upper(), 'role': 'app', 'help': 'Sistema e aplicativos do iDrive 7'} for i in MGU7_APP_IDS]
        out += [{'id': '0000' + i, 'version': MGU7_APP_VER, 'label': 'Dados %s' % i.upper(), 'role': 'data', 'help': 'Dados e recursos do iDrive 7'} for i in MGU7_DATA_IDS]
        out.append({'id': MGU7_KERNEL_PKG, 'version': MGU7_KERNEL_VER, 'label': 'Kernel do Linux', 'role': 'kernel', 'help': 'Núcleo do sistema do iDrive 7'})
        return out
    if kind == 'mgu22':
        return [{'id': '00009ff7', 'version': MGU22_VER, 'label': 'Kernel e sistema base', 'role': 'kernel', 'help': 'Imagem de boot e raiz do iDrive 8', 'approx_mb': 0},
                {'id': '00009fc6', 'version': MGU22_VER, 'label': 'HMI (IVI)', 'role': 'hmi', 'help': 'Interface do iDrive 8 e tabela de codificação'},
                {'id': '00009ff9', 'version': MGU22_VER, 'label': 'Extras (EXT)', 'role': 'data', 'help': 'Dados adicionais do iDrive 8'}]
    return []

def _psdz_roots(kind, psdz):
    if not psdz: return []
    roots = [psdz, os.path.join(psdz, 'psdzdata')]
    folder = {'cic': 'CIC', 'mgu7': 'ID7', 'mgu22': 'id8'}.get(kind)
    if folder: roots.append(os.path.join(psdz, folder))
    return roots

def _search_dirs(kind, psdz):
    dirs = []
    for root in _psdz_roots(kind, psdz):
        dirs.append(os.path.join(root, 'swe', 'swfl'))
    if psdz: dirs.append(psdz)
    dirs.append(os.path.join(STAGE, 'swe', 'swfl'))
    if kind == 'cic': dirs.append(os.path.expanduser('~/Downloads/System files/ID4'))
    return dirs

def package_status(kind, psdz=None):
    # estado de cada pacote exigido: encontrado (onde) ou faltando; ok = todos encontrados
    if psdz is None: psdz = load_settings().get('psdz_path')
    items = []
    for r in required_packages(kind):
        name = 'swfl_%s.bin.%s' % (r['id'], r['version']); it = dict(r, file=name, found=False, path=None, size=0, source=None, other=[])
        for d in _search_dirs(kind, psdz):
            f = os.path.join(d, name)
            if os.path.isfile(f):
                it.update(found=True, path=os.path.realpath(f), size=os.path.getsize(f), source='psdz' if d != os.path.join(STAGE, 'swe', 'swfl') else 'escolhido'); break
        if not it['found']:
            for d in _search_dirs(kind, psdz):
                for g in glob.glob(os.path.join(d, 'swfl_%s.bin.*' % r['id'])): it['other'].append(os.path.basename(g))
        items.append(it)
    return {'kind': kind, 'ok': bool(items) and all(i['found'] for i in items), 'items': items, 'have': sum(1 for i in items if i['found']), 'total': len(items)}

def packages_ok(kind): return package_status(kind)['ok']

def evo_package_status(swfl=None, brand='bmw'):
    """Check an Evo profile's selected files, or discover files in the configured folder."""
    dirs = _search_dirs('evo', load_settings().get('psdz_path')) if swfl is None else ()
    items = []
    for role, sid in (('os', OS_SWFL), ('brand', BRAND_SWFL.get(brand)), ('hmi', HMI_SWFL)):
        label, help_ = ROLE_TEXT[role]
        pattern = f'swfl_{sid}.bin.*' if sid else 'swfl_*.bin.*'
        candidates = [swfl.get(role)] if swfl is not None else sorted(
            (path for folder in dirs for path in glob.glob(os.path.join(folder, pattern))),
            key=os.path.basename, reverse=True)
        item = dict(role=role, id=sid, label=label, help=help_, file=pattern,
                    found=False, path=None, size=0, source=None, other=[])
        for path in candidates:
            if not isinstance(path, str) or not os.path.isfile(path): continue
            name = os.path.basename(path)
            match = SWFL_RX.fullmatch(name)
            if match and match[1].lower() == sid:
                item.update(found=True, file=name, path=os.path.realpath(path), size=os.path.getsize(path))
                break
        items.append(item)
    have = sum(item['found'] for item in items)
    return {'kind': 'evo', 'ok': have == len(items), 'items': items, 'have': have, 'total': len(items)}

def _stage_package(path, dst, kind):
    if os.path.normcase(os.path.realpath(dst)) == os.path.normcase(os.path.realpath(path)):
        return
    if sys.platform == 'win32' and kind == 'cic':
        # A per-user Windows installation may not have permission to create symlinks.
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(dst), delete=False) as staged:
            temp_path = staged.name
        try:
            shutil.copyfile(path, temp_path)
            os.replace(temp_path, dst)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    else:
        if os.path.lexists(dst): os.unlink(dst)
        os.symlink(path, dst)

def stage_file(path, kind):
    # liga um arquivo escolhido no estágio; devolve (ok, mensagem). O nome precisa ser o de um pacote exigido
    path = os.path.abspath(os.path.expanduser(path or ''))
    n = os.path.basename(path); m = SWFL_RX.match(n)
    if not os.path.isfile(path): return False, 'arquivo inexistente'
    if not m: return False, 'o nome do arquivo precisa ser swfl_<id>.bin.<versão>'
    want = {r['id']: r['version'] for r in required_packages(kind)}
    sid = m.group(1).lower()
    if sid not in want: return False, 'este arquivo não é usado por esta versão do iDrive'
    if m.group(2) != want[sid]: return False, 'versão %s: o IDEmu precisa da %s' % (m.group(2), want[sid])
    d = os.path.join(STAGE, 'swe', 'swfl'); os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, n)
    try:
        _stage_package(path, dst, kind)
    except OSError as e: return False, 'não consegui gravar o arquivo: %s' % e
    return True, 'ok'

def effective_psdz(kind):
    # pasta no formato PSdZData que os montadores leem: a PSdZData salva se tem tudo, senão o estágio (links)
    psdz = load_settings().get('psdz_path')
    st = package_status(kind, psdz)
    for root in _psdz_roots(kind, psdz):
        if st['items'] and all(os.path.isfile(os.path.join(root, 'swe', 'swfl', i['file'])) for i in st['items']):
            return root
    d = os.path.join(STAGE, 'swe', 'swfl'); os.makedirs(d, exist_ok=True)
    for i in st['items']:
        if i['found']:
            dst = os.path.join(d, i['file'])
            if not os.path.exists(dst):
                try:
                    _stage_package(i['path'], dst, kind)
                except OSError: pass
    return STAGE

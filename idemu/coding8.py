"""Editor de codificação do iDrive 8 (MGU22): parâmetros, valores atuais e de fábrica, backups.

Fonte: o firmware (`tools/mgu/gen_coding8.py`): o esquema cafd_mgu_02_a.bin dá nome, id e opções de cada parâmetro do CAF "infotainment" (1.264) e o
MGU22_Coding.txt dá o valor do carro (G70BEV) e a seção. O resultado fica em mgu22/coding8.json.

"Gravar" (flash) = guarda as mudanças em env.json (coding.extra: {NOME: número}) e reinicia a VM. A cada partida o IDEmu junta ao initramfs uma `coding.tab`
própria do ambiente (a de fábrica, mgu22/guest/coding.tab, com os ids alterados); o `libcod.so.0` do guest responde `cod_get_flag` com ela e o init a conta
em "== coding applied N"."""
import json, os
from . import coding as c6

AREA_LABELS = {'EXBOX_COMFORT': 'Comfort', 'EXBOX_DRIVER_ASSISTANCE': 'Driver assistance', 'EXBOX_ICC': 'Instrument cluster and ICC', 'EXBOX_CLIMATE': 'Climate',
               'VEHICLE_INFO': 'Vehicle information', 'ENTERTAINMENT': 'Entertainment and audio', 'HMI': 'HMI and touch', 'EXBOX_LIGHT': 'Lights', 'NAVI': 'Navigation',
               'EXBOX_PARKING': 'Parking and cameras', 'FES': 'Driving modes (FES)', 'EXBOX_M': 'BMW M', 'EXBOX_SEAT': 'Seats', 'EXBOX_ELECTRIC_VEHICLE': 'Electric vehicle',
               'EXBOX_VEHICLE': 'Vehicle', 'LANGUAGE': 'Languages', 'MYMODES': 'My Modes', 'SPEECH': 'Speech', 'MINI_MODES': 'MINI modes', 'HW_INFO_HU': 'Head unit hardware',
               'HW_INFO': 'Hardware', 'LIFECYCLE': 'Lifecycle and power', 'CHINA_TYPE_APPROVAL_SW_VERSION_NUMBERS': 'China type approval', 'EA_UI_DRIVING_EXPERIENCE': 'Driving experience',
               'NETWORK': 'Network', 'BOOTLOADER': 'Bootloader', 'infotainment': 'Other'}
# Parâmetros de destaque (aba "Popular"): nome, grupo, rótulo, descrição. Só entram os que existem no dicionário.
POPULAR = [
    ('CID_TOUCH', 'Display and touch', 'Touch screen', 'Central display accepts touch input.'),
    ('CID_HMI_TOUCH', 'Display and touch', 'HMI touch control', 'The HMI reacts to touch events from the central display.'),
    ('CID_TOUCH_PROXIMITY', 'Display and touch', 'Touch proximity', 'Proximity sensing of the hand before the touch.'),
    ('CID_HMI_ACTIVATION_VIA_TOUCH', 'Display and touch', 'Wake by touch', 'Touching the display activates the HMI.'),
    ('HMI_ID_VERSION', 'Display and touch', 'iDrive generation', 'Look and structure of the interface.'),
    ('SETUP_WIZARD', 'Display and touch', 'Setup wizard', 'First-start assistant.'),
    ('LEGAL_DISCLAIMER_TIME', 'Display and touch', 'Startup legal disclaimer', 'Seconds the disclaimer stays on screen at startup.'),
    ('DEVELOPER_MENU', 'Display and touch', 'Developer menu', 'Hidden developer menu in the HMI.'),
    ('SERVICE_MENU', 'Display and touch', 'Service menu', 'Service menu in the HMI.'),
    ('EFFICIENCY_TRAINER', 'Display and touch', 'Efficiency trainer', 'Driving efficiency coach.'),
    ('SPEEDLOCK_SPELLER_INPUT', 'Video and driving', 'Lock text input while driving', 'Which input methods stay locked while moving.'),
    ('SPEEDLOCK_TEXT_LENGTH', 'Video and driving', 'Text length while driving', 'How much text can be read while moving.'),
    ('SPEEDLOCK_CAR_STANDSTILL', 'Video and driving', 'What counts as stopped', 'Condition that releases the speed lock.'),
    ('VIDEO_SPEEDLOCK_CONDITION', 'Video and driving', 'Video in motion', 'Condition for showing video.'),
    ('ENT_VIDEO_SUPPORT', 'Video and driving', 'Video playback', 'Video playback is available.'),
    ('KIDS_MODE', 'Entertainment', 'Kids mode', 'Child mode for the entertainment menu.'),
    ('AUDIO_SYSTEM', 'Entertainment', 'Audio system', 'Installed sound system.'),
    ('HIGH_END_AUDIO_B_AND_W', 'Entertainment', 'Bowers & Wilkins', 'High-end audio from Bowers & Wilkins.'),
    ('ENT_MIRACAST_SUPPORT', 'Entertainment', 'Miracast', 'Screen mirroring by Miracast.'),
    ('MIRRORING', 'Entertainment', 'Phone mirroring', 'Smartphone mirroring.'),
    ('MM_SPORT_MODE_AVAILABILITY', 'My Modes', 'Sport mode', 'Sport mode is offered in My Modes.'),
    ('MM_EFFICIENT_MODE_AVAILABILITY', 'My Modes', 'Efficient mode', 'Efficient mode is offered in My Modes.'),
    ('MM_CINEMA_MODE_AVAILABILITY', 'My Modes', 'Cinema mode', 'Cinema mode is offered in My Modes.'),
    ('MM_WELLBEING_MODE_AVAILABILITY', 'My Modes', 'Wellbeing mode', 'Wellbeing mode is offered in My Modes.'),
    ('MM_SILENT_MODE_AVAILABILITY', 'My Modes', 'Silent mode', 'Silent mode is offered in My Modes.'),
    ('MM_EXPRESSIVE_MODE_AVAILABILITY', 'My Modes', 'Expressive mode', 'Expressive mode is offered in My Modes.'),
    ('MM_ORIGINAL_MODE_AVAILABILITY', 'My Modes', 'Original mode', 'Original mode is offered in My Modes.'),
    ('DRIVE_RECORDER', 'Vehicle', 'Drive recorder', 'Drive recorder menu.'),
    ('CAMERA_SYSTEM', 'Vehicle', 'Camera system', 'Which camera system is installed.'),
    ('PANORAMA_DISPLAY', 'Vehicle', 'Panorama display', 'Panorama display is installed.'),
    ('GEARBOX_TYPE', 'Vehicle', 'Gearbox type', 'Type of transmission.'),
    ('COUNTRY', 'Vehicle', 'Country', 'Country variant of the car.'),
]
MAX_NUM = (1 << 31) - 1
_cache = {}


def path():
    from . import mgu
    return os.path.join(mgu.OUT, 'coding8.json')


def available():
    return os.path.isfile(path())


def ensure(log=print):
    """Extrai o dicionário do firmware (cerca de 6 s) se ainda não existir; precisa da PSdZData configurada."""
    if available():
        return
    from . import catalog, mgu
    psdz = catalog.effective_psdz('mgu22')
    if not catalog.packages_ok('mgu22'):
        raise ValueError('o dicionário de codificação do iDrive 8 ainda não foi extraído: configure a PSdZData e reconstrua o ambiente')
    import importlib.util
    spec = importlib.util.spec_from_file_location('gen_coding8', os.path.join(mgu.TOOLS, 'gen_coding8.py'))
    m = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, mgu.TOOLS)
    spec.loader.exec_module(m)
    log('iDrive 8: extraindo o dicionário de codificação do firmware')
    m.from_psdz(psdz, path())


def load():
    ensure()
    p = path()
    m = os.path.getmtime(p)
    if _cache.get('m') != m:
        with open(p) as f:
            d = json.load(f)
        params = {x['name']: x for x in d['params']}
        _cache.clear()
        _cache.update(m=m, d=d, params=params)
    return _cache['params']


def _bits(p):
    top = max([o['value'] for o in p['options']] or [0])
    if not p['options']:
        return 31
    return max(1, int(top).bit_length())


def _max(p):
    return (1 << _bits(p)) - 1 if p['options'] else MAX_NUM


def _valid(p, num):
    """Opções: só os valores do esquema; sem opções: qualquer inteiro de 0 a 2^31-1."""
    if p['options']:
        return any(o['value'] == num for o in p['options'])
    return 0 <= num <= MAX_NUM


def factory_tab():
    """{id: valor} da tabela de fábrica (mgu22/guest/coding.tab, a que o libcod lê sem alterações)."""
    from . import mgu
    out = {}
    with open(os.path.join(mgu.OUT, 'guest', 'coding.tab')) as f:
        for line in f:
            a = line.split()
            if len(a) == 2:
                out[int(a[0], 16)] = int(a[1])
    return out


def build_tab(env):
    """Texto de coding.tab do ambiente (fábrica + mudanças de env.coding.extra); None se não há mudança (vale a tabela de fábrica da imagem)."""
    extra = (env.get('coding') or {}).get('extra') or {}
    params = load()
    changes = {params[n]['id']: int(v) for n, v in extra.items() if n in params}
    if not changes:
        return None
    tab = factory_tab()
    tab.update(changes)
    return ''.join('%x %d\n' % (k, tab[k]) for k in sorted(tab))


def _options(p):
    return [{'value': o['value'], 'raw': o['raw'], 'label': c6.value_label(p['name'], o['raw'])} for o in p['options']]


def describe(env, env_dir):
    params = load()
    extra = (env.get('coding') or {}).get('extra') or {}
    pop = {p[0]: p for p in POPULAR}
    out = []
    for name, p in params.items():
        coded = name in extra
        q = pop.get(name)
        out.append({'name': name, 'label': q[2] if q else c6._humanize(name), 'desc': q[3] if q else '', 'popular': q[1] if q else None,
                    'group': p['group'], 'bits': _bits(p), 'max': _max(p), 'options': _options(p), 'factory': p['default'],
                    'value': int(extra[name]) if coded else p['default'], 'coded': coded})
    groups = sorted({x['group'] for x in out})
    order = [q[0] for q in POPULAR if q[0] in params]
    return {'params': out, 'groups': [{'id': g, 'label': AREA_LABELS.get(g, g.replace('_', ' ').title())} for g in groups],
            'popular_order': order, 'popular_groups': list(dict.fromkeys(q[1] for q in POPULAR if q[0] in params)), 'backups': c6.list_backups(env_dir)}


def apply_changes(env, changes):
    """Aplica {NOME: valor} a env['coding']['extra']; None volta ao padrão. Devolve [(nome, antes, depois)]."""
    params = load()
    cd = env.setdefault('coding', {})
    extra = dict(cd.get('extra') or {})
    done = []
    for name, val in changes.items():
        p = params.get(name)
        if not p:
            raise ValueError('parâmetro desconhecido: %s' % name)
        if val is None:
            done.append((name, extra.pop(name, None), None))
            continue
        num = val
        if not isinstance(num, int) or isinstance(num, bool):
            num = next((o['value'] for o in p['options'] if o['raw'] == str(val)), None)
        if num is None or not _valid(p, num):
            raise ValueError('valor inválido para %s: %r' % (name, val))
        if num == p['default']:
            done.append((name, extra.pop(name, None), None))        # igual à fábrica: não precisa guardar
            continue
        done.append((name, extra.get(name), num))
        extra[name] = num
    cd['extra'] = extra
    return done

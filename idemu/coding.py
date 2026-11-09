"""Editor de codificação da head unit (como um app de coding): lista os parâmetros do CAFD, valores atuais e de fábrica, backups e "flash".

Fontes, todas do próprio firmware:
  * parâmetros/valores/posição: dicionário CODING_FEATURE da libhmicoding (idemu/data/coding_dict.json.z, via codegen);
  * grupo do CAFD e valor de fábrica: símbolos nbtSysetDefaults_getCbf<GRUPO>_CB_F<NOME> da mesma biblioteca (extraídos do SWFL do ambiente).

"Flash" = grava a codificação em env.json, regenera coding.tab em shim.img e reinicia a head unit; o HMI lê a tabela ao subir (src/shim/hook.c)."""
import json, os, re, shutil, struct, tempfile, time
from . import codegen

META_VERSION = 1

# ---- parâmetros de destaque (a tela "Popular"): nome, descrição, grupo ----
POPULAR = [
    ('language', 'Display', 'Head unit language', 'Language of every menu. Virtual parameter: selects the matching LANGUAGE_* entry as master.'),
    ('STARTUP_TYPE', 'Display', 'Startup screen', 'What the screen shows while the head unit starts.'),
    ('STARTUP_EMBLEM', 'Display', 'Startup logo', 'Which logo variant the startup animation uses.'),
    ('HMI_ID_VERSION', 'Display', 'iDrive generation', 'Look and structure of the interface (ID6 tiles, ID5 list...).'),
    ('HMI_MAIN_MENU_VERSION', 'Display', 'Main menu style', 'Standard or modern main menu.'),
    ('COMPASS', 'Display', 'Compass', 'Compass in the navigation split screen.'),
    ('SETUP_WIZARD', 'Display', 'Setup wizard', 'First-start assistant.'),
    ('ACOUSTIC_TOUCH_FEEDBACK', 'Display', 'Touch sound', 'Plays a sound when the screen is touched.'),
    ('VIDEO_SPEEDLOCK_CONDITION', 'Video and driving', 'Video in motion', 'Condition for showing video: none means it is never blocked by the speed lock.'),
    ('VIDEO_HANDBRAKE', 'Video and driving', 'Video needs handbrake', 'Video only with the handbrake on.'),
    ('SPEEDLOCK_MOVING_PICTURES', 'Video and driving', 'Lock moving pictures while driving', 'Blocks moving pictures above the speed limit.'),
    ('SPEEDLOCK_CAR_STANDSTILL', 'Video and driving', 'What counts as stopped', 'Condition that releases the speed lock.'),
    ('SPEEDLOCK_SPELLER_INPUT', 'Video and driving', 'Lock text input while driving', 'Which input methods stay locked while moving.'),
    ('SPEEDLOCK_TEXT_LENGTH', 'Video and driving', 'Text length while driving', 'How much text can be read while moving.'),
    ('SPEEDLOCK_SEE_ALL', 'Video and driving', 'Show all while driving', 'Keeps restricted content visible while moving.'),
    ('LEGAL_DISCLAIMER_TIME', 'Video and driving', 'Startup legal disclaimer', 'Disclaimer shown at startup: none, with timeout or permanent.'),
    ('MACRO_CAM_LEGALDISCLAIMER', 'Video and driving', 'Camera legal disclaimer', 'Disclaimer shown on the camera view.'),
    ('A4A_LEGAL_DISCLAIMER', 'Video and driving', 'Apps legal disclaimer', 'Disclaimer shown when opening phone apps.'),
    ('DRIVE_EXPERIENCE', 'Vehicle menus', 'Driving experience', 'Driving experience menu.'),
    ('CONDITION_CHECK', 'Vehicle menus', 'Vehicle check', 'Vehicle check menu.'),
    ('SERVICE_HISTORY', 'Vehicle menus', 'Service history', 'Service history menu.'),
    ('OELSTANDSMENUE', 'Vehicle menus', 'Oil level menu', 'Oil level item in the vehicle menu.'),
    ('MOMENTANVERBRAUCHSANZEIGE', 'Vehicle menus', 'Instant consumption', 'Shows the instant fuel consumption.'),
    ('RDC', 'Vehicle menus', 'Tyre pressure menu (RDC)', 'Tyre pressure monitoring menu.'),
    ('REIFENUEBERWACHUNG_RDC_RPA', 'Vehicle menus', 'Tyre monitoring system', 'Which system monitors the tyres: RDC, RPA or none.'),
    ('RDC_DRUCK_TEMP', 'Vehicle menus', 'Tyre values shown', 'Pressure only, or pressure and temperature.'),
    ('M_MENUE', 'Vehicle menus', 'M menu', 'M vehicle menu.'),
    ('MDRIVE', 'Vehicle menus', 'M Drive', 'M Drive item.'),
    ('M_LAPTIMER', 'Vehicle menus', 'M lap timer', 'Lap timer.'),
    ('HEADUP_DISPLAY', 'Vehicle menus', 'Head-up display menu', 'Head-up display settings.'),
    ('SERVICE_MENUE', 'Developer', 'Service menu', 'Hidden service menu.'),
    ('ENTWICKLER_MENUE', 'Developer', 'Developer menu', 'Hidden developer menu.'),
    ('NAVI_VARIANTE', 'Navigation', 'Navigation variant', 'Which navigation system the car has.'),
    ('NAVI_SHOW_GEOCORDINATES', 'Navigation', 'Show coordinates', 'Shows latitude and longitude in the position view.'),
    ('NAVI_GEO_COORDINATE_INPUT', 'Navigation', 'Enter coordinates', 'Allows entering a destination by coordinates.'),
    ('SYSTEM_GPS_RECEIVER', 'Navigation', 'GPS receiver', 'The system has a GPS receiver.'),
    ('GPS_FROM_NAVI', 'Navigation', 'GPS from navigation', 'Position comes from the navigation system.'),
    ('A4A', 'Phone and apps', 'Apps (A4A)', 'Phone apps integration.'),
    ('A4A_ANDROID', 'Phone and apps', 'Android apps', 'Apps integration for Android phones.'),
    ('A4A_WIRELESS_IOS', 'Phone and apps', 'Wireless iOS', 'Wireless connection with iPhones.'),
    ('A4A_WIRELESS_ANDROID', 'Phone and apps', 'Wireless Android', 'Wireless connection with Android phones.'),
    ('CARPLAY_FULLSCREEN', 'Phone and apps', 'CarPlay full screen', 'Uses the whole screen for CarPlay.'),
    ('MIRRORING', 'Phone and apps', 'Screen mirroring', 'Mirrors the phone screen.'),
    ('AUDIO_SYSTEM', 'Audio', 'Audio system', 'Audio system fitted in the car.'),
    ('HIGH_END_AUDIO_MENUE', 'Audio', 'High-end audio menu', 'High-end audio menu and light staging.'),
    ('REVERSE_GONG', 'Audio', 'Reverse chime', 'Chime when reverse gear is engaged.'),
    ('DAYDRIVING_LIGHT', 'Lights and comfort', 'Daytime running lights', 'Setting offered for daytime running lights.'),
    ('WELCOME_LIGHT', 'Lights and comfort', 'Welcome light', 'Welcome light item.'),
    ('5_FACH_TIPPBLINKEN', 'Lights and comfort', 'Five-flash indicator', 'Offers five flashes on a short indicator tap.'),
    ('ACOUSTICAL_LOCK_CONFIRM', 'Lights and comfort', 'Lock confirmation sound', 'Sound when the car locks.'),
    ('DOOR_LOCK_AFTER_DRIVING_AWAY', 'Lights and comfort', 'Lock after driving away', 'Offers locking the doors after driving away.'),
    ('DEFAULT_WEG_EINHEIT', 'Units', 'Distance unit', 'Default distance unit.'),
    ('DEFAULT_TEMPERATUR', 'Units', 'Temperature unit', 'Default temperature unit.'),
    ('DEFAULT_ZEIT_EINHEIT', 'Units', 'Time format', 'Default time format.'),
    ('DEFAULT_DATUM', 'Units', 'Date format', 'Default date format.'),
    ('DEFAULT_DRUCK_EINHEIT', 'Units', 'Pressure unit', 'Default pressure unit.'),
    ('VERBRAUCH', 'Units', 'Consumption unit', 'Fuel consumption unit.'),
    ('BAUREIHE', 'Vehicle', 'Chassis', 'Chassis the head unit believes it is in. A wrong value can change the car model shown.'),
    ('LCI', 'Vehicle', 'Facelift (LCI)', 'Facelift version of the car.'),
    ('PRODUKTLINIE', 'Vehicle', 'Product line', 'Vehicle product line.'),
    ('GETRIEBETYP', 'Vehicle', 'Gearbox', 'Manual or automatic.'),
    ('BAUART', 'Vehicle', 'Body style', 'Body style of the car.'),
    ('ANTRIEB', 'Vehicle', 'Drive type', 'Vehicle drive type.'),
]

# rótulos de valores: dicionário alemão/abreviações -> inglês (o i18n da interface traduz para os demais idiomas)
VALUE_WORDS = {'nicht_aktiv': 'Not active', 'aktiv': 'Active', 'inaktiv': 'Not active', 'keine': 'None', 'kein': 'None', 'none': 'None', 'kein_menue': 'No menu', 'alle_anderen': 'All others',
               'off': 'Off', 'on': 'On', 'standard': 'Standard', 'default': 'Default', 'handbrake': 'Handbrake', 'gearbox_p': 'Gear in P', 'handbrake_and_gearbox_p': 'Handbrake and gear in P',
               'handbrake_or_gearbox_p': 'Handbrake or gear in P', 'kein_ld': 'None', 'ld_mit_timeout': 'With timeout', 'permanent': 'Permanent', 'black': 'Black screen', 'splash': 'Splash image',
               'animation': 'Animation', 'pwf_welcome': 'Welcome animation', 'handschalter': 'Manual', 'automatik': 'Automatic', 'perm_off': 'Always off', 'perm_on': 'Always on',
               'schmales_display': 'Narrow display', 'breites_display': 'Wide display', 'limousine': 'Sedan', 'touring': 'Touring', 'coupe': 'Coupe', 'cabrio': 'Convertible', 'stereo': 'Stereo',
               'whole_text': 'Whole text', 'one_page': 'One page', 'no_text': 'No text', 'internal': 'Internal', 'external': 'External', 'druck': 'Pressure', 'druck_und_temperatur': 'Pressure and temperature',
               'keine_navi': 'No navigation', 'kuehlung': 'Cooling', 'heizung': 'Heating', 'heizung_kuehlung': 'Heating and cooling', 'teil_aktiv': 'Partly active', 'unknown': 'Unknown', 'Unbekannt': 'Unknown'}

WORD_GLOSSARY = {'ENT': 'Entertainment', 'CDMM': 'Media', 'HMI': 'HMI', 'NAVI': 'Navigation', 'KOMBI': 'Cluster', 'KI': 'Cluster', 'HUD': 'Head-up', 'SEAT': 'Seat', 'SITZE': 'Seats', 'ZBE': 'Controller', 'CID': 'Screen',
                 'AKTIVIERUNG': 'Activation', 'EINHEIT': 'Unit', 'VERBRAUCH': 'Consumption', 'REIFEN': 'Tyres', 'LICHT': 'Light', 'MENUE': 'Menu', 'FOND': 'Rear', 'HEIZUNG': 'Heating', 'EIN': 'On', 'AUS': 'Off',
                 'ANZEIGE': 'Display', 'EINSTELLUNG': 'Setting', 'BELEUCHTUNG': 'Lighting', 'PIM': 'Personal info', 'FES': 'Driving modes', 'HVAC': 'Climate', 'RSE': 'Rear screens', 'TI': 'Traffic info', 'SDARS': 'Satellite radio'}

GROUP_LABELS = {'AUDIO_TUNER_TRAFFIC': 'Audio, tuner, traffic', 'CAF_ID': 'CAFD identification', 'DISPLAY_PIP_CONFIG': 'Display and picture-in-picture', 'EFFICIENT_DYNAMICS': 'EfficientDynamics', 'EXBOX': 'Vehicle (EXBOX)',
                'FES': 'Driving modes (FES)', 'HMI': 'HMI', 'HUD': 'Head-up display', 'KOMBI': 'Instrument cluster', 'LANGUAGE': 'Languages', 'NAVIGATION': 'Navigation', 'SARAH': 'Driver assistance (SARAH)', 'SIGNATURE': 'Signature',
                'SYSTEM_EINSTELLUNGEN': 'System settings', 'TELEFON_TELEMATIK_ONLINE': 'Phone, telematics, online', 'TL_ID': 'Target list ID', 'TOUCH_COMMAND': 'Touch Command', 'OTHER': 'Other'}

MONTHS = codegen.MONTHS


def _humanize(name):
    words = [w for w in name.split('_') if w]
    return ' '.join(WORD_GLOSSARY.get(w, w.capitalize() if w.isalpha() and len(w) > 3 else w) for w in words)


def value_label(param, raw):
    """Texto legível de um valor do dicionário ("va_X" sem sufixo é o próprio parâmetro ligado)."""
    if raw == 'va_%s' % param or raw == param:
        return 'Active'
    if raw in VALUE_WORDS:
        return VALUE_WORDS[raw]
    m = re.match(r'^wert_(.+)$', raw)
    if m:
        return m.group(1)
    return raw.replace('_', ' ')


def _read_defaults(lib_path):
    """(nome -> grupo, nome -> valor de fábrica) dos símbolos nbtSysetDefaults_getCbf<GRUPO>_CB_F<NOME> (funções 'mov r0,#v; bx lr'), sem depender de bibliotecas de ELF."""
    d = open(lib_path, 'rb').read()
    if d[:4] != b'\x7fELF' or d[4] != 1:
        raise ValueError('libhmicoding.so não é ELF32')
    shoff, shentsize, shnum = struct.unpack_from('<I', d, 32)[0], struct.unpack_from('<H', d, 46)[0], struct.unpack_from('<H', d, 48)[0]
    phoff, phentsize, phnum = struct.unpack_from('<I', d, 28)[0], struct.unpack_from('<H', d, 42)[0], struct.unpack_from('<H', d, 44)[0]
    secs = [struct.unpack_from('<10I', d, shoff + i * shentsize) for i in range(shnum)]
    dyn = [s for s in secs if s[1] == 11][0]      # SHT_DYNSYM
    strs = secs[dyn[6]]
    segs = [struct.unpack_from('<8I', d, phoff + i * phentsize) for i in range(phnum)]
    def off(a):
        for s in segs:
            if s[0] == 1 and s[2] <= a < s[2] + s[4]:
                return a - s[2] + s[1]
        return None
    groups, defaults = {}, {}
    for i in range(dyn[5] // 16):
        nm, val, size, info, other, shndx = struct.unpack_from('<IIIBBH', d, dyn[4] + i * 16)
        e = d.index(b'\0', strs[4] + nm)
        s = d[strs[4] + nm:e].decode('latin1')
        m = re.match(r'^nbtSysetDefaults_getCbf(.+?)_CB_F(.+)$', s)
        if not m:
            continue
        groups[m.group(2)] = m.group(1)
        o = off(val & ~1)
        if o is None or size != 8 or val & 1:
            continue
        w0, w1 = struct.unpack_from('<II', d, o)
        if w1 != 0xe12fff1e:
            continue
        if w0 & 0xfffff000 == 0xe3a00000:      # mov r0, #imm (rotacionado)
            rot = (w0 >> 8 & 15) * 2
            imm = w0 & 255
            defaults[m.group(2)] = ((imm >> rot) | (imm << (32 - rot))) & 0xffffffff if rot else imm
        elif w0 & 0xfff0f000 == 0xe3000000:    # movw r0, #imm16
            defaults[m.group(2)] = ((w0 >> 4) & 0xf000) | (w0 & 0xfff)
    return groups, defaults


def load_meta(env, env_dir, refresh=False):
    """Grupo e valor de fábrica de cada parâmetro, extraídos uma vez do SWFL do ambiente e guardados em <env>/coding_meta.json."""
    p = os.path.join(env_dir, 'coding_meta.json')
    sw = (env.get('swfl') or {}).get('hmi', '')
    if not refresh:
        try:
            with open(p) as f:
                m = json.load(f)
            if m.get('version') == META_VERSION and m.get('swfl') == os.path.basename(sw):
                return m
        except (OSError, ValueError):
            pass
    from . import swfl
    tmp = tempfile.mkdtemp(prefix='idemu-coding')
    try:
        swfl.extract(sw, tmp, lambda tp, n, m: n == 'libhmicoding.so')
        libs = [os.path.join(dp, f) for dp, _, fs in os.walk(tmp) for f in fs if f == 'libhmicoding.so']
        if not libs:
            raise ValueError('libhmicoding.so não encontrada no pacote HMI')
        groups, defaults = _read_defaults(libs[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    m = {'version': META_VERSION, 'swfl': os.path.basename(sw), 'groups': groups, 'defaults': defaults}
    with open(p, 'w') as f:
        json.dump(m, f)
    return m


def _options(name, rows):
    seen, out = set(), []
    for y in rows:
        raw = y['value']
        short = raw.replace('va_' + name + '_', '')
        if short == 'VariantVal' or y['val'] in seen:
            continue
        seen.add(y['val'])
        out.append({'value': y['val'], 'raw': short, 'label': value_label(name, short)})
    return sorted(out, key=lambda o: o['value'])


def _current_of(name, val, rows):
    """Número do valor gravado em env.coding.extra / perfil (texto do dicionário ou inteiro)."""
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    for y in rows:
        if y['value'].replace('va_' + name + '_', '') == str(val):
            return y['val']
    return None


def describe(env, env_dir):
    """Tudo que a tela de coding mostra: parâmetros com valor atual, de fábrica e opções."""
    d = codegen.load_dict()
    meta = load_meta(env, env_dir)
    prof = codegen.profile_for(env)
    popular = {p[0]: p for p in POPULAR}
    out = []
    for name, rows in d.items():
        e = rows[0]
        if e.get('end', e['byte']) > e['byte'] or e['mask'] == 0:
            continue                # campos de mais de um byte: a tabela do guest só grava um byte por parâmetro
        bits = bin(e['mask']).count('1')
        opts = _options(name, rows)
        factory = meta['defaults'].get(name)
        if factory is None:
            factory = opts[0]['value'] if opts and len(opts) == 1 else None
        cur = _current_of(name, prof[name], rows) if name in prof else None
        p = popular.get(name)
        out.append({'name': name, 'label': p[2] if p else _humanize(name), 'desc': p[3] if p else '', 'popular': p[1] if p else None,
                    'group': meta['groups'].get(name, 'OTHER'), 'bits': bits, 'max': (1 << bits) - 1, 'options': opts,
                    'factory': factory, 'value': cur if cur is not None else factory, 'coded': name in prof})
    groups = sorted({x['group'] for x in out})
    lang = (env.get('coding') or {}).get('language', 'en_GB')
    from .catalog import LANGS
    names = dict(LANGS)
    virtual = {'name': 'language', 'label': 'Head unit language', 'desc': popular['language'][3], 'popular': 'Display', 'group': 'LANGUAGE', 'bits': 0, 'max': 0, 'virtual': True,
               'options': [{'value': c, 'raw': c, 'label': names.get(c, c)} for c in codegen.LANG_FEATURE], 'factory': None, 'value': lang, 'coded': True}
    return {'params': [virtual] + out, 'groups': [{'id': g, 'label': GROUP_LABELS.get(g, g.replace('_', ' ').title())} for g in groups],
            'popular_order': [p[0] for p in POPULAR], 'popular_groups': list(dict.fromkeys(p[1] for p in POPULAR)),
            'backups': list_backups(env_dir)}


def apply_changes(env, changes):
    """Aplica {NOME: valor} (número ou texto do dicionário) a env['coding']; valor None volta ao padrão. Devolve a lista [(nome, antes, depois)]."""
    cd = env.setdefault('coding', {})
    extra = dict(cd.get('extra') or {})
    d = codegen.load_dict()
    done = []
    for name, val in changes.items():
        if name == 'language':
            if val not in codegen.LANG_FEATURE:
                raise ValueError('idioma desconhecido: %s' % val)
            done.append((name, cd.get('language'), val))
            cd['language'] = val
            continue
        if name not in d:
            raise ValueError('parâmetro desconhecido: %s' % name)
        e = d[name][0]
        if val is None:
            done.append((name, extra.pop(name, None), None))
            continue
        num = _current_of(name, val, d[name])
        bits = bin(e['mask']).count('1')
        if num is None or not 0 <= num < (1 << bits):
            raise ValueError('valor inválido para %s: %r' % (name, val))
        done.append((name, extra.get(name), num))
        extra[name] = num
    cd['extra'] = extra
    return done


# ---- backups ----
def _backup_dir(env_dir):
    return os.path.join(env_dir, 'coding_backups')


def backup(env, env_dir, note=''):
    d = _backup_dir(env_dir)
    os.makedirs(d, exist_ok=True)
    bid = time.strftime('%Y%m%d-%H%M%S')
    p = os.path.join(d, bid + '.json')
    n = 1
    while os.path.exists(p):
        n += 1
        p = os.path.join(d, '%s-%d.json' % (bid, n))
    with open(p, 'w') as f:
        json.dump({'note': note, 'created': time.time(), 'chassis': env.get('chassis'), 'vin': (env.get('coding') or {}).get('vin'), 'coding': env.get('coding')}, f, indent=1, ensure_ascii=False)
    # guarda os 30 mais recentes
    for old in sorted(os.listdir(d))[:-30]:
        os.unlink(os.path.join(d, old))
    return os.path.basename(p)[:-5]


def list_backups(env_dir):
    d = _backup_dir(env_dir)
    out = []
    if os.path.isdir(d):
        for n in sorted(os.listdir(d), reverse=True):
            try:
                with open(os.path.join(d, n)) as f:
                    j = json.load(f)
                out.append({'id': n[:-5], 'note': j.get('note', ''), 'created': j.get('created'), 'changed': len((j.get('coding') or {}).get('extra') or {})})
            except (OSError, ValueError):
                pass
    return out


def read_backup(env_dir, bid):
    if not re.match(r'^[0-9-]+$', bid or ''):
        raise ValueError('backup inválido')
    with open(os.path.join(_backup_dir(env_dir), bid + '.json')) as f:
        return json.load(f)

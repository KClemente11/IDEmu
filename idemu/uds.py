"""UDS diagnostic emulator for the iDrive 5/6 head unit (the virtual car's ECUs as seen through the ZGW).

On the car, diagnostic tools on the head unit open HSFZ (TCP 6801) to the central gateway and send UDS requests
addressed to an ECU (DME 0x12, EGS 0x18, ...). In the emulator a small daemon in the guest (/fs/shim/hsfzd) plays the
gateway: it listens on 6801 on the gateway's link-local address and forwards each request over UART1 to the host,
where UdsEmulator.handle() builds the reply from a per-environment configuration (<env>/uds.json).

Configuration (JSON):
  {
    "gateway_ips": ["169.254.199.99"],             # extra addresses the guest gateway answers on (gateway-ip.txt
                                                    # files found in the overlay are added automatically at build time)
    "unknown_ecu": "silent" | "nrc",                # no ECU at that address: time out (like the car) or answer 7F xx 11
    "ecus": {
      "12": {
        "name": "DME",
        "dids": { "4205": <value>, ... },           # ReadDataByIdentifier 22 xx xx -> 62 xx xx <data>
        "obd":  { "0C": <value>, ... },             # OBD mode 01 PIDs -> 41 pid <data>
        "raw":  [ {"request": "2F 01 ..", "response": "6F 01 00"} ],   # exact requests; '..' matches any byte
        "dtcs": [ {"code": "123456", "status": "2F"} ]                  # 19 02 -> 59 02 ...; 14 clears them
      }
    }
  }

A <value> is one of
  {"hex": "FFFF"}                                   fixed bytes
  {"bytes": 2, "scale": 0.0078125, "offset": 0, "signed": false, "value": 101.3}
                                                    physical value -> raw = (value - offset) / scale, big-endian
  ... plus "wave": {"min": 100, "max": 240, "period": 8} to sweep between min and max (seconds per cycle)
  {"length": 36, "fields": [{"name": "...", "pos": 0, "bytes": 2, ...}, ...]}   a record with several values
Optional keys: "name", "unit", "mask" (raw & mask), "little" (little-endian).
"""
import collections
import copy
import json
import math
import os
import threading
import time

DEFAULT_IP = '169.254.199.99'
TESTER = 0xF4           # HSFZ source address of a diagnostic tool on the head unit
CAN_TESTER_ID = 0x6F1   # BMW diagnostic CAN ids: tester 0x6F1, ECU replies on 0x600 + address
MAX_REPLY = 1000        # bytes; the guest UART line buffer limits a reply to about this much

# ---------------------------------------------------------------------------------------------------------- presets
def _v(name, unit, nbytes, scale, value=None, offset=0.0, signed=False, wave=None, **kw):
    d = {'name': name, 'unit': unit, 'bytes': nbytes, 'scale': scale, 'offset': offset}
    if signed: d['signed'] = True
    if value is not None: d['value'] = value
    if wave: d['wave'] = {'min': wave[0], 'max': wave[1], 'period': wave[2]}
    d.update(kw)
    return d


PRESETS = collections.OrderedDict()
PRESETS['b58'] = {
    'label': 'B58 / 340i (BoostDeck, ShiftDeck, MHD maps)',
    'note': 'Signals from ID6_apps docs/SIGNALS.md (the collector.c request table).',
    'ecus': {
        '12': {'name': 'DME', 'dids': {
            '4201': _v('Ambient pressure', 'kPa', 2, 1 / 256.0, 101.3),
            '4205': _v('Boost pressure (absolute)', 'kPa', 2, 1 / 128.0, wave=(100, 240, 8)),
            '5889': _v('Lambda', '', 2, 16 / 65535.0, wave=(0.80, 1.00, 5)),
            '4A49': _v('Ignition timing', 'deg', 2, 0.1, signed=True, wave=(4, 22, 7)),
            '580F': _v('Intake air temperature', 'C', 1, 0.75, 32, offset=-48),
            '56D7': _v('Rail pressure', 'bar', 2, 1 / 50.0, wave=(60, 200, 6)),
            '586F': _v('Oil pressure', 'bar', 2, 1 / 1000.0, wave=(2.0, 4.5, 9)),
            '4300': _v('Coolant temperature', 'C', 2, 0.1, 92, offset=-273.15),
        }, 'obd': {
            '0C': _v('Engine speed', 'rpm', 2, 0.25, wave=(900, 6500, 6)),
            '0D': _v('Vehicle speed', 'km/h', 1, 1, wave=(0, 120, 20)),
            '05': _v('Coolant temperature', 'C', 1, 1, 92, offset=-40),
        }},
        '18': {'name': 'EGS', 'dids': {
            'DA12': _v('Transmission oil temperature', 'C', 2, 1, 75, offset=-48),
        }},
    },
}
PRESETS['s63tu'] = {
    'label': 'S63TU (s63tu_r0.prg STATUS_MESSWERTE)',
    'note': 'Record layout read from the STATUS_MESSWERTE job. The request bytes in the decompile start "22 40": the DID '
            'is assumed to be 4000. Field positions count from the first data byte after the DID, assuming the long '
            '(4-byte) EDIABAS header; check both against the .prg before relying on them.',
    'ecus': {
        '12': {'name': 'DME', 'dids': {
            '4000': {'name': 'STATUS_MESSWERTE', 'length': 36, 'fields': [
                _v('STAT_LR1_MW (lambda bank 1)', '', 2, 0.000244140625, 1.0, pos=0),
                _v('STAT_VFZG_MW (vehicle speed)', 'km/h', 2, 0.0078125, wave=(0, 120, 20), pos=4),
                _v('STAT_NMOT_W_MW (engine speed)', '1/min', 2, 0.25, wave=(800, 6500, 6), pos=6),
                _v('STAT_NSOL_MW (target idle)', '1/min', 2, 0.25, 700, pos=8),
                _v('STAT_CAM_IN (intake cam)', 'degCA', 2, 0.0078125, 20, signed=True, pos=10),
                _v('STAT_CAM_EX (exhaust cam)', 'degCA', 2, 0.0078125, -15, signed=True, pos=12),
                _v('STAT_TIA (intake air)', 'C', 1, 0.75, 30, offset=-48, pos=14),
                _v('STAT_TMOT (coolant)', 'C', 1, 0.75, 90, offset=-48, pos=15),
                _v('STAT_IGA_IGC (ignition angle)', 'deg', 2, 0.1, wave=(2, 25, 7), signed=True, pos=16),
                _v('STAT_TPS_AV_1 (throttle)', '% DK', 2, 0.0244140625, wave=(2, 80, 6), signed=True, pos=18),
                _v('STAT_MAF_KGH_MES_BAS (air mass)', 'kg/h', 2, 0.1, wave=(40, 900, 6), signed=True, pos=20),
                _v('STAT_TQI_AV (torque)', 'Nm', 2, 0.5, wave=(40, 650, 6), signed=True, pos=22),
                _v('STAT_VB (battery)', 'V', 1, 0.0942, 14.1, pos=24),
                _v('STAT_V_PVS_1 (pedal sensor)', 'V', 2, 0.0048828125, 0.75, pos=25, mask=1023),
                _v('STAT_TMOTLINF', 'C', 1, 0.75, 90, offset=-48, pos=27),
                _v('STAT_NL_1', 'V', 2, 0.0048828125, 1.0, pos=28),
                _v('STAT_NL_4', 'V', 2, 0.0048828125, 1.0, pos=30),
                _v('STAT_NL_3', 'V', 2, 0.0048828125, 1.0, pos=32),
                _v('STAT_NL_2', 'V', 2, 0.0048828125, 1.0, pos=34),
            ]},
        }},
    },
}
SERVICES = {0x10: 'DiagnosticSessionControl', 0x11: 'ECUReset', 0x14: 'ClearDTC', 0x19: 'ReadDTC', 0x22: 'ReadDataByIdentifier',
            0x27: 'SecurityAccess', 0x2F: 'IOControl', 0x31: 'RoutineControl', 0x3E: 'TesterPresent', 0x01: 'OBD mode 01',
            0x09: 'OBD mode 09'}


def default_config():
    cfg = {'gateway_ips': [DEFAULT_IP], 'unknown_ecu': 'silent', 'ecus': {}}
    merge_preset(cfg, 'b58')
    return cfg


def merge_preset(cfg, name):
    p = PRESETS[name]
    for addr, ecu in p['ecus'].items():
        dst = cfg.setdefault('ecus', {}).setdefault(addr, {'name': ecu.get('name', '')})
        if not dst.get('name'): dst['name'] = ecu.get('name', '')
        for kind in ('dids', 'obd'):
            if ecu.get(kind): dst.setdefault(kind, {}).update(copy.deepcopy(ecu[kind]))
        if ecu.get('raw'): dst.setdefault('raw', []).extend(copy.deepcopy(ecu['raw']))
    return cfg


# ---------------------------------------------------------------------------------------------------------- encoding
def hexb(s):
    return bytes.fromhex(''.join(str(s).split()).replace('0x', '').replace('0X', ''))


def norm_key(k, width):
    k = str(k).strip().upper().replace('0X', '')
    int(k, 16)
    return k.zfill(width)


def phys_value(v, t):
    w = v.get('wave')
    if w:
        lo, hi, per = float(w.get('min', 0)), float(w.get('max', 0)), max(0.2, float(w.get('period', 5)))
        return lo + (hi - lo) * (0.5 - 0.5 * math.cos(2 * math.pi * t / per))
    return float(v.get('value', 0) or 0)


def encode_field(v, t):
    """Raw bytes of one value description at time t."""
    if 'hex' in v:
        return hexb(v['hex'])
    n = int(v.get('bytes', 1))
    scale = float(v.get('scale', 1) or 1)
    raw = int(round((phys_value(v, t) - float(v.get('offset', 0) or 0)) / scale))
    if v.get('signed'):
        lo, hi = -(1 << (8 * n - 1)), (1 << (8 * n - 1)) - 1
    else:
        lo, hi = 0, (1 << (8 * n)) - 1
    raw = max(lo, min(hi, raw))
    if v.get('mask') is not None: raw &= int(v['mask'])
    return (raw & ((1 << (8 * n)) - 1)).to_bytes(n, 'little' if v.get('little') else 'big')


def encode_value(v, t):
    if 'fields' in v:
        size = int(v.get('length') or max(int(f.get('pos', 0)) + int(f.get('bytes', 1)) for f in v['fields']))
        buf = bytearray(size)
        for f in v['fields']:
            b = encode_field(f, t); p = int(f.get('pos', 0))
            buf[p:p + len(b)] = b
        return bytes(buf[:size])
    return encode_field(v, t)


def describe(v, t):
    """'101.3 kPa' style text for the log (first field of a record)."""
    if 'hex' in v: return 'hex ' + hexb(v['hex']).hex().upper()
    if 'fields' in v: return '%d fields' % len(v['fields'])
    x = phys_value(v, t)
    txt = ('%.3f' % x).rstrip('0').rstrip('.')
    return (txt if txt not in ('-0', '') else '0') + ((' ' + v['unit']) if v.get('unit') else '')


def isotp_frames(addr, payload):
    """BMW extended-addressing ISO-TP frames (first byte = target address) for the CAN monitor."""
    if len(payload) <= 6:
        return [bytes([addr, len(payload)]) + payload]
    out = [bytes([addr, 0x10 | (len(payload) >> 8 & 0xF), len(payload) & 0xFF]) + payload[:5]]
    sn, i = 1, 5
    while i < len(payload):
        out.append(bytes([addr, 0x20 | (sn & 0xF)]) + payload[i:i + 6]); sn += 1; i += 6
    return out


# ---------------------------------------------------------------------------------------------------------- emulator
class UdsEmulator(object):
    def __init__(self, path, can=None, log_path=None):
        self.path, self.can, self.log_path = path, can, log_path
        self._lock = threading.RLock()
        self._t0 = time.monotonic()
        self._ring = collections.deque(maxlen=600)
        self._seq = 0
        self._cleared = set()
        self.cfg = self.load()
        self.stats = {'requests': 0, 'positive': 0, 'negative': 0, 'silent': 0}

    # --- configuration ---------------------------------------------------------------------------------------------
    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = default_config()
        return validate(cfg)

    def config(self):
        with self._lock:
            return copy.deepcopy(self.cfg)

    def save(self, cfg):
        cfg = validate(cfg)
        with self._lock:
            self.cfg = cfg
            self._cleared.clear()
        save_config(self.path, cfg)
        return cfg

    def set_value(self, ecu, kind, key, value, field=None):
        """Changes "value" of one entry (or of one field of a record) and drops its sweep."""
        with self._lock:
            cfg = copy.deepcopy(self.cfg)
            e = cfg['ecus'][norm_key(ecu, 2)][kind][norm_key(key, 4 if kind == 'dids' else 2)]
            if field is not None: e = e['fields'][int(field)]
            e.pop('wave', None); e.pop('hex', None); e['value'] = float(value)
        return self.save(cfg)

    # --- requests ----------------------------------------------------------------------------------------------------
    def now(self):
        return time.monotonic() - self._t0

    def handle(self, src, tgt, req):
        """Reply bytes for one UDS request, or None for no reply (the tester times out)."""
        req = bytes(req)
        with self._lock:
            cfg, t = self.cfg, self.now()
            ecu = cfg['ecus'].get('%02X' % tgt)
            resp, note = self._answer(cfg, ecu, tgt, req, t)
            self.stats['requests'] += 1
            self.stats['silent' if resp is None else 'negative' if resp[:1] == b'\x7f' else 'positive'] += 1
            self._seq += 1
            item = {'seq': self._seq, 't': round(t, 3), 'src': '%02X' % src, 'ecu': '%02X' % tgt,
                    'ecu_name': (ecu or {}).get('name', ''), 'req': req.hex().upper(),
                    'resp': None if resp is None else resp.hex().upper(), 'note': note}
            self._ring.append(item)
        self._log(item)
        self._to_can(tgt, req, resp, note)
        return resp

    def _answer(self, cfg, ecu, tgt, req, t):
        if not req: return None, 'empty request'
        sid = req[0]
        if ecu is None:
            return (bytes([0x7F, sid, 0x11]), 'no ECU %02X configured' % tgt) if cfg.get('unknown_ecu') == 'nrc' else (None, 'no ECU %02X configured (no reply)' % tgt)
        for rule in ecu.get('raw') or []:
            pat = ''.join(str(rule.get('request', '')).split()).upper()
            if len(pat) == 2 * len(req) and all(pat[i:i + 2] == '..' or int(pat[i:i + 2], 16) == req[i // 2] for i in range(0, len(pat), 2)):
                r = rule.get('response')
                return (None, 'raw rule: no reply') if r in (None, '') else (hexb(r), rule.get('name') or 'raw rule')
        if sid == 0x22:
            if len(req) < 3 or (len(req) - 1) % 2: return bytes([0x7F, 0x22, 0x13]), 'bad length'
            out, notes = bytearray([0x62]), []
            for i in range(1, len(req), 2):
                did = '%02X%02X' % (req[i], req[i + 1])
                v = (ecu.get('dids') or {}).get(did)
                if v is None: continue
                out += req[i:i + 2] + encode_value(v, t)
                notes.append('%s %s = %s' % (did, v.get('name', ''), describe(v, t)))
            if len(out) == 1: return bytes([0x7F, 0x22, 0x31]), 'DID %s not configured' % req[1:].hex().upper()
            return bytes(out[:MAX_REPLY]), '; '.join(notes)
        if sid == 0x01:
            if len(req) < 2: return bytes([0x7F, 0x01, 0x13]), 'bad length'
            out, notes = bytearray([0x41]), []
            for pid in req[1:7]:
                if pid in (0x00, 0x20, 0x40, 0x60):             # supported-PID bitmaps
                    bits = 0
                    for k in (ecu.get('obd') or {}):
                        p = int(k, 16)
                        if pid < p <= pid + 0x20: bits |= 1 << (32 - (p - pid))
                    out += bytes([pid]) + bits.to_bytes(4, 'big'); continue
                v = (ecu.get('obd') or {}).get('%02X' % pid)
                if v is None: continue
                out += bytes([pid]) + encode_value(v, t)
                notes.append('PID %02X %s = %s' % (pid, v.get('name', ''), describe(v, t)))
            if len(out) == 1: return bytes([0x7F, 0x01, 0x12]), 'PID %s not configured' % req[1:].hex().upper()
            return bytes(out), '; '.join(notes) or 'supported PIDs'
        if sid == 0x09 and req[1:2] == b'\x02':
            vin = str(cfg.get('vin') or 'WBA00000000000000')[:17].ljust(17, '0').encode('ascii', 'replace')
            return b'\x49\x02\x01' + vin, 'VIN'
        if sid == 0x10 and len(req) >= 2:
            return bytes([0x50, req[1], 0x00, 0x32, 0x01, 0xF4]), 'session %02X' % req[1]
        if sid == 0x3E:
            if len(req) >= 2 and req[1] & 0x80: return None, 'tester present (no reply requested)'
            return bytes([0x7E, 0x00]), 'tester present'
        if sid == 0x11 and len(req) >= 2:
            return bytes([0x51, req[1]]), 'reset %02X' % req[1]
        if sid == 0x19 and len(req) >= 3 and req[1] == 0x02:
            out = bytearray([0x59, 0x02, 0xFF])
            dtcs = [] if tgt in self._cleared else (ecu.get('dtcs') or [])
            for d in dtcs:
                st = int(str(d.get('status', '2F')), 16)
                if st & req[2]: out += hexb(d['code'])[:3].rjust(3, b'\0') + bytes([st])
            return bytes(out), '%d DTC(s)' % ((len(out) - 3) // 4)
        if sid == 0x14:
            self._cleared.add(tgt)
            return b'\x54', 'DTCs cleared'
        if sid == 0x27 and len(req) >= 2:
            return (bytes([0x67, req[1], 0x12, 0x34, 0x56, 0x78]), 'seed') if req[1] & 1 else (bytes([0x67, req[1]]), 'key accepted')
        if sid == 0x2F and len(req) >= 2:                  # also the 3-byte MHD map switch 2F 01 <slot>
            return bytes([0x6F]) + req[1:], 'IO control echo'
        if sid == 0x31 and len(req) >= 4:
            return bytes([0x71]) + req[1:4], 'routine %s' % req[2:4].hex().upper()
        return bytes([0x7F, sid, 0x11]), 'service %02X not supported' % sid

    # --- output ------------------------------------------------------------------------------------------------------
    def transactions(self, since=0, limit=200):
        with self._lock:
            items = [x for x in self._ring if x['seq'] > int(since or 0)][-int(limit):]
            return {'seq': self._seq, 'items': items, 'stats': dict(self.stats)}

    def _log(self, it):
        if not self.log_path: return
        svc = SERVICES.get(int(it['req'][:2] or '0', 16), '')
        line = '%9.3f  %s(%s) <- %s  %s  =>  %s   %s\n' % (it['t'], it['ecu'], it['ecu_name'] or '?', it['src'], it['req'],
                                                      it['resp'] if it['resp'] is not None else '(no reply)', (svc + ': ' if svc else '') + (it['note'] or ''))
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(line)
        except OSError:
            pass

    def _to_can(self, tgt, req, resp, note):
        can = self.can
        if not can or not hasattr(can, 'log_only'): return
        try:
            short = (note or '').split(';')[0][:60]
            for i, fr in enumerate(isotp_frames(tgt, req)):
                can.log_only(CAN_TESTER_ID, fr, 'UDS -> %02X %s' % (tgt, SERVICES.get(req[0], '')) if i == 0 else None, 'req')
            if resp is not None:
                frames = isotp_frames(0xF1, resp)      # on the CAN side the tester is F1
                if len(frames) > 1: can.log_only(CAN_TESTER_ID, bytes([tgt, 0x30, 0x00, 0x00]), 'flow control', 'req')
                for i, fr in enumerate(frames):
                    can.log_only(0x600 + tgt, fr, ('UDS <- %02X %s' % (tgt, short)) if i == 0 else None, 'resp')
        except Exception:
            pass


def validate(cfg):
    """Normalises keys (upper-case hex) and checks every value can be encoded. Raises ValueError with the bad entry."""
    if not isinstance(cfg, dict): raise ValueError('UDS configuration must be a JSON object')
    out = {'gateway_ips': [], 'unknown_ecu': 'nrc' if cfg.get('unknown_ecu') == 'nrc' else 'silent', 'ecus': {}}
    if cfg.get('vin'): out['vin'] = str(cfg['vin'])
    for ip in cfg.get('gateway_ips') or [DEFAULT_IP]:
        parts = str(ip).strip().split('.')
        if len(parts) != 4 or not all(p.isdigit() and int(p) < 256 for p in parts):
            raise ValueError('gateway address %r is not an IPv4 address' % ip)
        out['gateway_ips'].append('.'.join(str(int(p)) for p in parts))
    for addr, ecu in (cfg.get('ecus') or {}).items():
        try:
            a = norm_key(addr, 2)
        except ValueError:
            raise ValueError('ECU address %r is not hex' % addr)
        if len(a) != 2: raise ValueError('ECU address %r must be one byte' % addr)
        e = {'name': str((ecu or {}).get('name', ''))}
        for kind, width in (('dids', 4), ('obd', 2)):
            items = {}
            for k, v in ((ecu or {}).get(kind) or {}).items():
                try:
                    kk = norm_key(k, width)
                except ValueError:
                    raise ValueError('ECU %s: %s key %r is not hex' % (a, kind, k))
                if len(kk) != width: raise ValueError('ECU %s: %s key %r is too long' % (a, kind, k))
                if not isinstance(v, dict): raise ValueError('ECU %s %s %s: value must be an object' % (a, kind, kk))
                try:
                    encode_value(v, 0.0)
                except Exception as ex:
                    raise ValueError('ECU %s %s %s: %s' % (a, kind, kk, ex))
                items[kk] = v
            if items: e[kind] = items
        for i, r in enumerate((ecu or {}).get('raw') or []):
            try:
                pat = ''.join(str(r.get('request', '')).split())
                if not pat or len(pat) % 2: raise ValueError('request must be whole bytes')
                for j in range(0, len(pat), 2):
                    if pat[j:j + 2] != '..': int(pat[j:j + 2], 16)
                if r.get('response'): hexb(r['response'])
            except Exception as ex:
                raise ValueError('ECU %s raw rule %d: %s' % (a, i + 1, ex))
            e.setdefault('raw', []).append(r)
        if (ecu or {}).get('dtcs'): e['dtcs'] = ecu['dtcs']
        out['ecus'][a] = e
    return out


def config_path(env_dir):
    return os.path.join(env_dir, 'uds.json')


def load_config(env_dir):
    try:
        with open(config_path(env_dir), encoding='utf-8') as f:
            return validate(json.load(f))
    except (OSError, ValueError):
        return default_config()


def save_config(path, cfg):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, path)


def gateway_ips(env_dir, overlay_files=()):
    """Addresses the guest gateway answers on: the configured ones plus every gateway-ip.txt shipped in the overlay."""
    ips = list(load_config(env_dir).get('gateway_ips') or [DEFAULT_IP])
    for rel, p in overlay_files:
        if os.path.basename(rel).lower() != 'gateway-ip.txt': continue
        try:
            with open(p, encoding='ascii', errors='replace') as f:
                ip = f.read().strip()
            validate({'gateway_ips': [ip]})
        except (OSError, ValueError):
            continue
        if ip not in ips: ips.append(ip)
    return ips

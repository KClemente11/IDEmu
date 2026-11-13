"""canbus – barramento CAN virtual do IDEmu (lado do host, testável sem a VM).

  * banco de sinais em JSON (idemu/data/can_signals.json), empacotamento bit a bit
    (Intel/Motorola, com sinal), vários sinais por ID;
  * gerador cíclico com relógio monotônico (deadline fixo, sem drift);
  * cenários com keyframes e interpolação (idemu/data/can_scenarios.json);
  * gravação/replay no formato candump `(1234567890.123456) can0 1A0#0011223344556677`;
  * servidor TCP texto opcional (127.0.0.1): `ID#HEXDATA` por linha, `set <sinal> <valor>`.

Somente biblioteca padrão (Python 3.9). Thread-safe.
"""
import bisect
import collections
import json
import os
import queue
import re
import socket
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SIGNALS = os.path.join(HERE, "data", "can_signals.json")
DEFAULT_SCENARIOS = os.path.join(HERE, "data", "can_scenarios.json")
RING_SIZE = 5000
MAX_STD_ID = 0x7FF
MAX_EXT_ID = 0x1FFFFFFF

_CANDUMP_RE = re.compile(r"^\s*\((\d+(?:\.\d+)?)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f.]*)")


# ---------------------------------------------------------------------------
# empacotamento de bits
# ---------------------------------------------------------------------------
def _motorola_positions(start_bit, length):
    """Posições (byte*8+bit) do MSB ao LSB, numeração DBC (start_bit = MSB)."""
    p = start_bit
    out = []
    for _ in range(length):
        out.append(p)
        p = p + 15 if (p % 8) == 0 else p - 1
    return out


def _positions(start_bit, length, order):
    if order == "motorola":
        return _motorola_positions(start_bit, length)           # MSB -> LSB
    return [start_bit + i for i in range(length - 1, -1, -1)]   # MSB -> LSB (Intel)


def pack_raw(buf, start_bit, length, order, raw):
    """Escreve `raw` (inteiro sem sinal, `length` bits) em `buf` (bytearray)."""
    for i, pos in enumerate(_positions(start_bit, length, order)):
        bit = (raw >> (length - 1 - i)) & 1
        byte, b = pos >> 3, pos & 7
        if bit:
            buf[byte] |= (1 << b)
        else:
            buf[byte] &= ~(1 << b) & 0xFF


def unpack_raw(data, start_bit, length, order):
    raw = 0
    for pos in _positions(start_bit, length, order):
        byte, b = pos >> 3, pos & 7
        bit = (data[byte] >> b) & 1 if byte < len(data) else 0
        raw = (raw << 1) | bit
    return raw


class Signal(object):
    """Definição de um sinal + conversão físico <-> bruto."""

    def __init__(self, d):
        self.d = dict(d)
        self.name = d["name"]
        self.label = d.get("label", self.name)
        self.group = d.get("group", "Outros")
        self.unit = d.get("unit", "")
        self.can_id = int(d["can_id"])
        self.start_bit = int(d["start_bit"])
        self.length = int(d["length"])
        self.order = d.get("byte_order", "intel")
        if self.order not in ("intel", "motorola"):
            raise ValueError("byte_order inválido em %s: %r" % (self.name, self.order))
        self.signed = bool(d.get("signed", False))
        self.factor = float(d.get("factor", 1))
        self.offset = float(d.get("offset", 0))
        self.kind = d.get("kind", "number")
        if self.kind not in ("number", "bool", "enum"):
            raise ValueError("kind inválido em %s: %r" % (self.name, self.kind))
        self.enum = d.get("enum") if self.kind == "enum" else None
        self.min = d.get("min", 0)
        self.max = d.get("max", 1 if self.kind == "bool" else (1 << self.length) - 1)
        self.step = d.get("step", 1)
        self.cycle_ms = d.get("cycle_ms")
        self.default = d.get("default", 0)
        self.auto = d.get("auto")
        if not 1 <= self.length <= 64:
            raise ValueError("length inválido em %s" % self.name)
        if self.factor == 0:
            raise ValueError("factor 0 em %s" % self.name)

    def to_raw(self, value):
        raw = int(round((float(value) - self.offset) / self.factor))
        if self.signed:
            lo, hi = -(1 << (self.length - 1)), (1 << (self.length - 1)) - 1
            raw = max(lo, min(hi, raw))
            if raw < 0:
                raw += 1 << self.length
        else:
            raw = max(0, min((1 << self.length) - 1, raw))
        return raw

    def from_raw(self, raw):
        if self.signed and raw & (1 << (self.length - 1)):
            raw -= 1 << self.length
        v = raw * self.factor + self.offset
        if self.kind != "number":
            return int(round(v))
        return round(v, 6)

    def pack(self, buf, value):
        pack_raw(buf, self.start_bit, self.length, self.order, self.to_raw(value))

    def unpack(self, data):
        return self.from_raw(unpack_raw(data, self.start_bit, self.length, self.order))

    def last_bit_byte(self):
        return max(p >> 3 for p in _positions(self.start_bit, self.length, self.order))

    def coerce(self, value):
        """Valida/normaliza um valor vindo do usuário."""
        if self.kind == "bool":
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("1", "true", "on", "sim", "yes", "t"):
                    return 1
                if v in ("0", "false", "off", "nao", "não", "no", "f"):
                    return 0
                raise ValueError("valor booleano inválido para %s: %r" % (self.name, value))
            return 1 if value else 0
        if self.kind == "enum":
            keys = self.enum or {}
            if isinstance(value, str):
                v = value.strip()
                if v in keys:
                    return int(v)
                for k, lab in keys.items():
                    if lab.lower() == v.lower():
                        return int(k)
                try:
                    value = float(v)
                except ValueError:
                    raise ValueError("valor inválido para %s: %r" % (self.name, value))
            iv = int(round(float(value)))
            if str(iv) not in keys:
                raise ValueError("valor %r fora do enum de %s (%s)" % (value, self.name, ", ".join(sorted(keys))))
            return iv
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise ValueError("valor numérico inválido para %s: %r" % (self.name, value))
        if f != f or f in (float("inf"), float("-inf")):
            raise ValueError("valor inválido para %s: %r" % (self.name, value))
        if self.min is not None:
            f = max(float(self.min), f)
        if self.max is not None:
            f = min(float(self.max), f)
        return int(f) if f == int(f) else f


class _Frame(object):
    def __init__(self, can_id, ext, dlc, init, cycle_ms, name):
        self.can_id = can_id
        self.ext = ext
        self.dlc = dlc
        self.init = bytearray(init)
        self.cycle_ms = cycle_ms
        self.name = name
        self.signals = []
        self.counter = 0


def fmt_id(can_id, ext=False):
    return ("%08X" % can_id) if ext else ("%03X" % can_id)


def parse_candump_line(line):
    """Devolve (ts, can_id, data, ext) ou None."""
    m = _CANDUMP_RE.match(line)
    if not m:
        return None
    ts = float(m.group(1))
    idtxt = m.group(2)
    cid = int(idtxt, 16)
    ext = len(idtxt) > 3
    hx = m.group(3).replace(".", "")
    if len(hx) % 2 or len(hx) > 16:
        return None
    return ts, cid, bytes(bytearray.fromhex(hx)), ext


# ---------------------------------------------------------------------------
# cliente TCP
# ---------------------------------------------------------------------------
class _TcpClient(object):
    def __init__(self, bus, sock, addr):
        self.bus = bus
        self.sock = sock
        self.addr = addr
        self.q = queue.Queue(maxsize=5000)
        self.alive = True
        self.t_r = threading.Thread(target=self._reader, name="can-tcp-r", daemon=True)
        self.t_w = threading.Thread(target=self._writer, name="can-tcp-w", daemon=True)

    def start(self):
        self.t_r.start()
        self.t_w.start()

    def send(self, line):
        if not self.alive:
            return
        try:
            self.q.put_nowait(line)
        except queue.Full:
            pass                                    # cliente lento: descarta

    def close(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.bus._drop_client(self)

    def _writer(self):
        while self.alive:
            line = self.q.get()
            if line is None:
                break
            try:
                self.sock.sendall(line.encode("ascii", "replace"))
            except OSError:
                break
        self.close()

    def _reader(self):
        buf = b""
        while self.alive:
            try:
                d = self.sock.recv(4096)
            except OSError:
                break
            if not d:
                break
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                reply = self.bus._handle_tcp_line(line.decode("ascii", "replace").strip())
                if reply:
                    self.send(reply + "\n")
            if len(buf) > 4096:
                buf = b""
        self.close()


# ---------------------------------------------------------------------------
class CanBus(object):
    def __init__(self, signals_path=None, tcp_port=None, rec_dir=None, scenarios_path=None):
        self.signals_path = signals_path or DEFAULT_SIGNALS
        self.scenarios_path = scenarios_path or DEFAULT_SCENARIOS
        self.tcp_port = tcp_port
        self.rec_dir = rec_dir or os.path.join(_tmpdir(), "idemu-can")
        self._lock = threading.RLock()
        self._cbs = []
        self._ring = collections.deque(maxlen=RING_SIZE)
        self._seq = 0
        self._t0 = time.monotonic()
        self._stop = threading.Event()
        self._threads = []
        self._running = False
        self._frames = {}               # can_id -> _Frame
        self._signals = collections.OrderedDict()
        self._values = {}
        self._manual = set()            # sinais 'auto' definidos manualmente
        self._scenarios = collections.OrderedDict()
        self._active = None
        self._active_t0 = 0.0
        self._rec_fh = None
        self._rec_path = None
        self._replay_stop = threading.Event()
        self._replay_thread = None
        self._replaying = False
        self._srv = None
        self._clients = []
        self._load_signals()
        self._load_scenarios()

    # --- carga do banco ------------------------------------------------
    def _load_signals(self):
        with open(self.signals_path, "r", encoding="utf-8") as f:
            db = json.load(f)
        frames = {}
        for fd in db.get("frames", []):
            cid = int(fd["can_id"])
            init = bytes(bytearray.fromhex(fd.get("init", ""))) if fd.get("init") else b""
            dlc = int(fd.get("dlc", 8))
            init = init.ljust(dlc, b"\x00")[:dlc]
            frames[cid] = _Frame(cid, bool(fd.get("ext", False)), dlc, init, fd.get("cycle_ms"), fd.get("name"))
        for sd in db["signals"]:
            sg = Signal(sd)
            if sg.name in self._signals:
                raise ValueError("sinal duplicado: %s" % sg.name)
            fr = frames.get(sg.can_id)
            if fr is None:
                fr = _Frame(sg.can_id, sg.can_id > MAX_STD_ID, 8, b"\x00" * 8, sg.cycle_ms, None)
                frames[sg.can_id] = fr
            if sg.last_bit_byte() >= fr.dlc:
                raise ValueError("sinal %s não cabe no DLC %d do ID 0x%X" % (sg.name, fr.dlc, fr.can_id))
            if fr.cycle_ms is None:
                fr.cycle_ms = sg.cycle_ms
            if sg.cycle_ms is None:
                sg.cycle_ms = fr.cycle_ms
            if fr.cycle_ms is None or fr.cycle_ms <= 0:
                raise ValueError("cycle_ms ausente para o ID 0x%X" % fr.can_id)
            fr.signals.append(sg)
            self._signals[sg.name] = sg
            self._values[sg.name] = sg.coerce(sg.default)
        self._frames = frames

    def _load_scenarios(self):
        if not os.path.exists(self.scenarios_path):
            return
        with open(self.scenarios_path, "r", encoding="utf-8") as f:
            db = json.load(f)
        for sc in db.get("scenarios", []):
            for sname in list(sc.get("tracks", {}).keys()) + [b["signal"] for b in sc.get("blink", [])]:
                if sname not in self._signals:
                    raise ValueError("cenário %s referencia sinal desconhecido %s" % (sc["id"], sname))
            self._scenarios[sc["id"]] = sc

    # --- ciclo de vida -------------------------------------------------
    def start(self):
        with self._lock:
            if self._running:
                return
            self._stop.clear()
            self._running = True
            self._t0 = time.monotonic()
            self._threads = [threading.Thread(target=self._tx_loop, name="can-tx", daemon=True),
                             threading.Thread(target=self._sim_loop, name="can-sim", daemon=True)]
        if self.tcp_port is not None:
            self._start_tcp()
        for t in self._threads:
            t.start()

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop.set()
            self._active = None
        self._replay_stop.set()
        self._stop_tcp()
        for t in self._threads:
            t.join(timeout=2)
        if self._replay_thread is not None:
            self._replay_thread.join(timeout=2)
            self._replay_thread = None
        self.record(False)

    @property
    def running(self):
        return self._running

    # --- callbacks / emissão ---------------------------------------------
    def on_frame(self, cb):
        with self._lock:
            self._cbs.append(cb)
        return cb

    def remove_on_frame(self, cb):
        with self._lock:
            if cb in self._cbs:
                self._cbs.remove(cb)

    def _emit(self, can_id, data, ext, name, direction, ts=None):
        ts = time.time() if ts is None else ts
        data = bytes(data)
        t_rel = time.monotonic() - self._t0
        with self._lock:
            self._seq += 1
            self._ring.append((self._seq, t_rel, can_id, ext, data, direction, name))
            cbs = list(self._cbs)
            clients = list(self._clients) if direction == "tx" else ()
            rec = self._rec_fh
            if rec is not None:
                try:
                    rec.write("(%.6f) can0 %s#%s\n" % (ts, fmt_id(can_id, ext), data.hex().upper()))
                except (OSError, ValueError):
                    pass
        if clients:
            line = "%s#%s\n" % (fmt_id(can_id, ext), data.hex().upper())
            for c in clients:
                c.send(line)
        for cb in cbs:
            try:
                cb(ts, can_id, data, ext, name, direction)
            except Exception:                           # um callback ruim não derruba o barramento
                pass

    # --- sinais --------------------------------------------------------
    def set_signal(self, name, value):
        """Define o valor de um sinal. `None` em sinais 'auto' (relógio) volta ao automático."""
        sg = self._signals.get(name)
        if sg is None:
            raise KeyError("sinal desconhecido: %s" % name)
        with self._lock:
            if value is None:
                if sg.auto:
                    self._manual.discard(name)
                    self._values[name] = self._auto_value(sg)
                    return self._values[name]
                raise ValueError("sinal %s não tem modo automático" % name)
            v = sg.coerce(value)
            self._values[name] = v
            if sg.auto:
                self._manual.add(name)
            return v

    def _set_internal(self, name, value):
        sg = self._signals[name]
        with self._lock:
            self._values[name] = sg.coerce(value)

    def get_signal(self, name):
        if name not in self._signals:
            raise KeyError("sinal desconhecido: %s" % name)
        with self._lock:
            return self._values[name]

    def signal_names(self):
        return list(self._signals.keys())

    @staticmethod
    def _auto_value(sg):
        lt = time.localtime()
        return {"hour": lt.tm_hour, "minute": lt.tm_min, "second": lt.tm_sec, "day": lt.tm_mday,
                "month": lt.tm_mon, "year": lt.tm_year}[sg.auto]

    def snapshot(self):
        """Formato de GET /api/can/signals."""
        groups = collections.OrderedDict()
        with self._lock:
            for name, sg in self._signals.items():
                item = {"name": name, "label": sg.label, "unit": sg.unit, "min": sg.min, "max": sg.max,
                        "value": self._values[name], "can_id": sg.can_id, "cycle_ms": sg.cycle_ms,
                        "step": sg.step, "kind": sg.kind,
                        "enum": dict(sg.enum) if sg.enum else None}
                groups.setdefault(sg.group, []).append(item)
            return {"groups": [{"name": g, "signals": s} for g, s in groups.items()],
                    "running": self._running, "scenario": self._active,
                    "recording": os.path.basename(self._rec_path) if self._rec_fh else None,
                    "replaying": self._replaying}

    def frame_bytes(self, can_id):
        """Bytes atuais do quadro cíclico `can_id` (útil nos testes)."""
        fr = self._frames[can_id]
        with self._lock:
            return self._build(fr)

    def _build(self, fr):
        buf = bytearray(fr.init)
        for sg in fr.signals:
            sg.pack(buf, self._values[sg.name])
        return bytes(buf)

    # --- gerador cíclico --------------------------------------------------
    def _tx_loop(self):
        now = time.monotonic()
        nxt = {}
        periods = {}
        for i, (cid, fr) in enumerate(sorted((c, f) for c, f in self._frames.items() if f.signals)):
            periods[cid] = fr.cycle_ms / 1000.0
            nxt[cid] = now + 0.002 + i * 0.0007            # escalonamento leve na partida
        while not self._stop.is_set():
            cid = min(nxt, key=nxt.get)
            wait = nxt[cid] - time.monotonic()
            if wait > 0 and self._stop.wait(wait):
                break
            period = periods[cid]
            nxt[cid] += period
            late = time.monotonic() - nxt[cid]
            if late > 5 * period:                          # ficou muito atrás: ressincroniza
                nxt[cid] = time.monotonic() + period
            if self._replaying:
                continue
            fr = self._frames[cid]
            with self._lock:
                data = self._build(fr)
            self._emit(cid, data, fr.ext, fr.name or fr.signals[0].name, "tx")

    # --- simulação: cenários, relógio, hodômetro ----------------------------
    def _sim_loop(self):
        last = time.monotonic()
        while not self._stop.wait(0.05):
            now = time.monotonic()
            dt = now - last
            last = now
            try:
                self._sim_step(now, dt)
            except Exception:
                pass

    def _sim_step(self, now, dt):
        with self._lock:
            for name, sg in self._signals.items():
                if sg.auto and name not in self._manual:
                    self._values[name] = self._auto_value(sg)
            if self._active is not None:
                self._scenario_step(now - self._active_t0)
            spd = self._values.get("vehicle_speed", 0)
            if "odometer" in self._values and spd:
                self._values["odometer"] = round(self._values["odometer"] + spd * dt / 3600.0, 3)

    def _scenario_step(self, t):
        sc = self._scenarios[self._active]
        dur = float(sc.get("duration", 0)) or None
        if dur and t >= dur:
            if sc.get("loop", False):
                self._active_t0 += dur * int(t // dur)
                t = t % dur
            else:
                # aplica o estado final e encerra
                self._apply_tracks(sc, dur)
                self._active = None
                return
        self._apply_tracks(sc, t)

    def _apply_tracks(self, sc, t):
        tracks = sc.get("tracks", {})
        for name, kf in tracks.items():
            sg = self._signals[name]
            self._values[name] = sg.coerce(self._interp(kf, t, sg.kind != "number"))
        for b in sc.get("blink", []):
            if b["from"] <= t < b["to"]:
                on = int(((t - b["from"]) / (float(b.get("period", 0.7)) / 2.0))) % 2 == 0
                self._values[b["signal"]] = 1 if on else 0
            elif b["signal"] not in tracks and t >= b["to"] and t < b["to"] + 0.2:
                self._values[b["signal"]] = 0
        if sc.get("drivetrain"):
            self._drivetrain(tracks)

    @staticmethod
    def _interp(kf, t, step):
        ts = [k[0] for k in kf]
        if t <= ts[0]:
            return kf[0][1]
        if t >= ts[-1]:
            return kf[-1][1]
        i = bisect.bisect_right(ts, t) - 1
        t0, v0 = kf[i]
        t1, v1 = kf[i + 1]
        if step or t1 == t0:
            return v0
        return v0 + (v1 - v0) * (t - t0) / (t1 - t0)

    _RATIOS = (110.0, 64.0, 44.0, 33.0, 26.0, 21.5)       # rpm por km/h em cada marcha (modelo simples)

    def _drivetrain(self, tracks):
        v = float(self._values["vehicle_speed"])
        if self._values.get("terminal_state", 69) < 69:
            return
        gear = len(self._RATIOS)
        for g, r in enumerate(self._RATIOS, 1):
            if v * r < 2600:
                gear = g
                break
        rpm = max(800.0, v * self._RATIOS[gear - 1]) if v > 0.5 else 800.0
        if "engine_rpm" not in tracks:
            self._values["engine_rpm"] = self._signals["engine_rpm"].coerce(rpm)
        if "accelerator_pos" not in tracks:
            self._values["accelerator_pos"] = self._signals["accelerator_pos"].coerce(
                min(100.0, 6.0 + max(0.0, v - 20.0) * 0.12 + (rpm - 800.0) / 120.0) if v > 0.5 else 0.0)
        if "fuel_consumption" not in tracks:
            self._values["fuel_consumption"] = self._signals["fuel_consumption"].coerce(
                0.0 if v < 0.5 else min(40.0, 4.0 + v / 14.0))
        # exibição esportiva (MOST 0xC7B): torque ~ acelerador numa curva plana; potência = torque * rpm / rpm de potência máx.
        acc = float(self._values.get("accelerator_pos", 0.0))
        tq = acc * min(1.0, 0.6 + rpm / 4000.0)
        if "engine_torque_pct" in self._signals and "engine_torque_pct" not in tracks:
            self._values["engine_torque_pct"] = self._signals["engine_torque_pct"].coerce(round(tq))
        if "engine_power_pct" in self._signals and "engine_power_pct" not in tracks:
            self._values["engine_power_pct"] = self._signals["engine_power_pct"].coerce(round(tq * min(1.0, rpm / 6000.0)))

    def scenarios(self):
        """Formato de GET /api/can/scenarios."""
        with self._lock:
            return {"scenarios": [{"id": sid, "name": sc.get("name", sid), "desc": sc.get("desc", "")}
                                  for sid, sc in self._scenarios.items()],
                    "active": self._active}

    def run_scenario(self, id_or_None):
        with self._lock:
            if id_or_None is None:
                self._active = None
                return
            if id_or_None not in self._scenarios:
                raise KeyError("cenário desconhecido: %s" % id_or_None)
            self._active = id_or_None
            self._active_t0 = time.monotonic()
            self._scenario_step(0.0)

    @property
    def active_scenario(self):
        return self._active

    # --- injeção / quadros --------------------------------------------------
    def inject(self, can_id, data, ext=False, direction="tx"):
        can_id = int(can_id)
        if isinstance(data, str):
            data = bytes(bytearray.fromhex(data.replace(" ", "").replace(".", "")))
        data = bytes(data)
        if len(data) > 8:
            raise ValueError("quadro CAN tem no máximo 8 bytes de dados")
        if can_id < 0 or can_id > (MAX_EXT_ID if ext else MAX_STD_ID):
            raise ValueError("ID CAN fora da faixa: 0x%X" % can_id)
        if direction not in ("tx", "rx"):
            raise ValueError("direction deve ser 'tx' ou 'rx'")
        fr = self._frames.get(can_id)
        name = (fr.name or fr.signals[0].name) if fr and fr.signals else None
        self._emit(can_id, data, ext, name, direction)

    def log_only(self, can_id, data, name, direction):
        """Frame shown in the monitor only (e.g. the emulated UDS diagnostics): it is not sent to the guest, to TCP clients
        or to the frame callbacks, and it is not recorded."""
        with self._lock:
            self._seq += 1
            self._ring.append((self._seq, time.monotonic() - self._t0, int(can_id), False, bytes(data), direction, name))

    def frames_since(self, seq, limit=200):
        """Formato de GET /api/can/frames. `seq` devolvido = último quadro entregue."""
        seq = int(seq or 0)
        limit = max(1, min(int(limit or 200), RING_SIZE))
        with self._lock:
            latest = self._seq
            if not self._ring or seq >= latest:
                return {"seq": latest, "frames": []}
            first = self._ring[0][0]
            start = max(0, seq + 1 - first)
            items = []
            for i, f in enumerate(self._ring):
                if i < start:
                    continue
                items.append(f)
                if len(items) >= limit:
                    break
        frames = [{"seq": s, "t": round(t, 3), "id": fmt_id(cid, ext), "dlc": len(d), "data": d.hex().upper(),
                   "dir": direction, "name": name} for (s, t, cid, ext, d, direction, name) in items]
        return {"seq": items[-1][0] if items else latest, "frames": frames}

    # --- gravação / replay -----------------------------------------------------
    def record(self, on):
        """on=True: inicia e devolve o caminho do arquivo; on=False: encerra e devolve o caminho do
        arquivo gravado (None se não havia gravação)."""
        with self._lock:
            if on:
                if self._rec_fh is not None:
                    return self._rec_path
                os.makedirs(self.rec_dir, exist_ok=True)
                base = time.strftime("can_%Y%m%d_%H%M%S")
                path = os.path.join(self.rec_dir, base + ".log")
                n = 1
                while os.path.exists(path):
                    n += 1
                    path = os.path.join(self.rec_dir, "%s_%d.log" % (base, n))
                self._rec_fh = open(path, "w", buffering=1)
                self._rec_path = path
                return path
            if self._rec_fh is None:
                return None
            try:
                self._rec_fh.close()
            finally:
                self._rec_fh = None
            return self._rec_path

    def recordings(self):
        out = []
        try:
            names = sorted(os.listdir(self.rec_dir))
        except OSError:
            return out
        for n in names:
            p = os.path.join(self.rec_dir, n)
            if n.endswith((".log", ".candump")) and os.path.isfile(p):
                st = os.stat(p)
                out.append({"file": n, "size": st.st_size, "mtime": st.st_mtime,
                            "recording": p == self._rec_path and self._rec_fh is not None})
        return out

    def _resolve_rec(self, name):
        if os.path.isabs(name):
            return name
        if os.sep in name or name.startswith(".."):
            raise ValueError("nome de arquivo inválido: %s" % name)
        return os.path.join(self.rec_dir, name)

    def replay(self, file, loop=False):
        """Reproduz um arquivo candump respeitando os timestamps relativos. `file=None` para.
        Enquanto reproduz, o gerador cíclico fica em pausa."""
        if file is None:
            self._replay_stop.set()
            return
        path = self._resolve_rec(file)
        if not os.path.isfile(path):
            raise FileNotFoundError("gravação não encontrada: %s" % file)
        items = []
        with open(path, "r") as f:
            for line in f:
                p = parse_candump_line(line)
                if p:
                    items.append(p)
        if not items:
            raise ValueError("a gravação não contém quadros válidos: %s" % file)
        if self._replay_thread is not None and self._replay_thread.is_alive():
            self._replay_stop.set()
            self._replay_thread.join(timeout=2)
        self._replay_stop = threading.Event()
        stop = self._replay_stop
        self._replaying = True
        self._replay_thread = threading.Thread(target=self._replay_loop, args=(items, bool(loop), stop),
                                               name="can-replay", daemon=True)
        self._replay_thread.start()

    def _replay_loop(self, items, loop, stop):
        try:
            while not stop.is_set() and not self._stop.is_set():
                t0 = time.monotonic()
                base = items[0][0]
                for ts, cid, data, ext in items:
                    wait = (ts - base) - (time.monotonic() - t0)
                    if wait > 0 and (stop.wait(wait) or self._stop.is_set()):
                        return
                    if stop.is_set():
                        return
                    fr = self._frames.get(cid)
                    name = (fr.name or fr.signals[0].name) if fr and fr.signals else None
                    self._emit(cid, data, ext, name, "tx")
                if not loop:
                    return
        finally:
            self._replaying = False

    # --- servidor TCP ------------------------------------------------------------
    def _start_tcp(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", int(self.tcp_port)))
        s.listen(8)
        s.settimeout(0.3)
        self.tcp_port = s.getsockname()[1]
        self._srv = s
        self._tcp_thread = threading.Thread(target=self._accept_loop, name="can-tcp", daemon=True)
        self._tcp_thread.start()

    def _accept_loop(self):
        srv = self._srv
        while not self._stop.is_set():
            try:
                c, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            cl = _TcpClient(self, c, addr)
            with self._lock:
                self._clients.append(cl)
            cl.start()

    def _stop_tcp(self):
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
            self._srv = None
            t = getattr(self, "_tcp_thread", None)
            if t is not None:
                t.join(timeout=2)
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            c.close()

    def _drop_client(self, cl):
        with self._lock:
            if cl in self._clients:
                self._clients.remove(cl)

    def _handle_tcp_line(self, line):
        """Processa uma linha de um cliente TCP. Devolve texto de resposta ou None."""
        if not line or line.startswith("#"):
            return None
        parts = line.split()
        cmd = parts[0].lower()
        try:
            if cmd == "set" and len(parts) >= 3:
                v = self.set_signal(parts[1], " ".join(parts[2:]) if self._signals[parts[1]].kind == "enum"
                                    else parts[2])
                return "ok %s=%s" % (parts[1], v)
            if cmd == "get" and len(parts) == 2:
                return "%s=%s" % (parts[1], self.get_signal(parts[1]))
            if "#" in line:
                idtxt, _, hx = line.partition("#")
                idtxt = idtxt.strip()
                if not re.match(r"^[0-9A-Fa-f]{1,8}$", idtxt):
                    return None
                ext = len(idtxt) > 3
                self.inject(int(idtxt, 16), bytes(bytearray.fromhex(hx.strip().replace(".", ""))), ext, "rx")
                return None
            return "err comando desconhecido"
        except (KeyError, ValueError) as e:
            return "err %s" % (e.args[0] if e.args else e)


def _tmpdir():
    import tempfile
    return tempfile.gettempdir()

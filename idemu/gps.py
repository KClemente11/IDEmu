"""gps – GPS virtual (spoof) do IDEmu: NMEA 0183 (+ UBX opcional) a partir de uma posição simulada.

Modos: static, manual (anda em linha reta se speed_kmh>0), circle, route (GPX/pontos).
A velocidade pode ser a configurada (speed_kmh) ou a do CAN virtual (sync_can_speed).

Somente biblioteca padrão (Python 3.9). Thread-safe.
"""
import collections
import datetime
import math
import socket
import struct
import threading
import time
import xml.etree.ElementTree as ET

EARTH_R = 6371008.8            # raio médio da Terra (m)
KNOT = 1.852                   # km/h por nó
MODES = ("static", "manual", "circle", "route")

# WGS-84 (para ECEF no UBX NAV-SOL)
_WGS_A = 6378137.0
_WGS_F = 1 / 298.257223563
_WGS_E2 = _WGS_F * (2 - _WGS_F)

GPS_EPOCH = datetime.datetime(1980, 1, 6)
LEAP_SECONDS = 18


class GpsError(ValueError):
    """Erro de validação (mensagem em português)."""


# ---------------------------------------------------------------------------
# geodésia (esfera)
# ---------------------------------------------------------------------------
def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(lat, lon, bearing, dist_m):
    """Ponto a `dist_m` metros de (lat,lon) no rumo `bearing` (graus), círculo máximo."""
    d = dist_m / EARTH_R
    b = math.radians(bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# GPX
# ---------------------------------------------------------------------------
def parse_gpx(text):
    """Devolve lista [(lat, lon), ...] de trkpt (preferencial), rtept ou wpt."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    if not text or not text.strip():
        raise GpsError("GPX vazio")
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError as e:
        raise GpsError("GPX inválido (XML malformado): %s" % e)

    def local(tag):
        return tag.rsplit("}", 1)[-1]
    groups = {"trkpt": [], "rtept": [], "wpt": []}
    for el in root.iter():
        t = local(el.tag)
        if t in groups:
            groups[t].append(el)
    for kind in ("trkpt", "rtept", "wpt"):
        els = groups[kind]
        if els:
            pts = []
            for el in els:
                try:
                    pts.append((float(el.attrib["lat"]), float(el.attrib["lon"])))
                except (KeyError, ValueError):
                    raise GpsError("GPX: ponto <%s> sem lat/lon válidos" % kind)
            return pts
    raise GpsError("GPX sem pontos (esperado trkpt, rtept ou wpt)")


def _check_point(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise GpsError("coordenada inválida: %r, %r" % (lat, lon))
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0) or lat != lat or lon != lon:
        raise GpsError("coordenada fora da faixa: lat=%s lon=%s" % (lat, lon))
    return lat, lon


class Route(object):
    def __init__(self, name, points):
        pts = [_check_point(*p[:2]) for p in points]
        if len(pts) < 2:
            raise GpsError("a rota precisa de pelo menos 2 pontos (recebeu %d)" % len(pts))
        # remove pontos consecutivos idênticos
        clean = [pts[0]]
        for p in pts[1:]:
            if p != clean[-1]:
                clean.append(p)
        if len(clean) < 2:
            raise GpsError("a rota tem todos os pontos iguais")
        self.name = name
        self.points = clean
        self.cum = [0.0]
        for a, b in zip(clean, clean[1:]):
            self.cum.append(self.cum[-1] + haversine_m(a[0], a[1], b[0], b[1]))
        self.length_m = self.cum[-1]

    def at(self, dist_m):
        """(lat, lon, rumo) a `dist_m` metros do início (limitado ao fim)."""
        d = max(0.0, min(self.length_m, dist_m))
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= d:
                lo = mid
            else:
                hi = mid
        a, b = self.points[lo], self.points[lo + 1]
        brg = bearing_deg(a[0], a[1], b[0], b[1])
        lat, lon = destination(a[0], a[1], brg, d - self.cum[lo])
        return lat, lon, brg


# ---------------------------------------------------------------------------
# NMEA
# ---------------------------------------------------------------------------
def nmea_checksum(body):
    c = 0
    for ch in body.encode("ascii"):
        c ^= ch
    return "%02X" % c


def nmea_sentence(body):
    return "$%s*%s\r\n" % (body, nmea_checksum(body))


def verify_nmea(line):
    """True se a sentença '$....*HH' tem checksum correto."""
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, ck = line[1:].rpartition("*")
    return nmea_checksum(body) == ck.upper()


def _lat_nmea(lat):
    h = "N" if lat >= 0 else "S"
    a = abs(lat)
    d = int(a)
    return "%02d%08.5f" % (d, (a - d) * 60.0), h


def _lon_nmea(lon):
    h = "E" if lon >= 0 else "W"
    a = abs(lon)
    d = int(a)
    return "%03d%08.5f" % (d, (a - d) * 60.0), h


def _fletcher(payload):
    a = b = 0
    for x in bytearray(payload):
        a = (a + x) & 0xFF
        b = (b + a) & 0xFF
    return a, b


def ubx_frame(cls, mid, payload):
    head = struct.pack("<BBH", cls, mid, len(payload))
    a, b = _fletcher(head + payload)
    return b"\xb5\x62" + head + payload + bytes(bytearray([a, b]))


def verify_ubx(frame):
    """True se `frame` é um pacote UBX íntegro (sync, comprimento e checksum Fletcher)."""
    if len(frame) < 8 or frame[0:2] != b"\xb5\x62":
        return False
    (ln,) = struct.unpack("<H", frame[4:6])
    if len(frame) != 8 + ln:
        return False
    a, b = _fletcher(frame[2:6 + ln])
    return frame[6 + ln] == a and frame[7 + ln] == b


# ---------------------------------------------------------------------------
class GpsSim(object):
    def __init__(self, can=None, tcp_port=None, rate_hz=1.0, clock=None):
        self.can = can
        self.tcp_port = tcp_port
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._nmea_cbs = []
        self._ubx_cbs = []
        self._stop = threading.Event()
        self._thread = None
        self._srv = None
        self._clients = []
        self._tcp_thread = None
        self.rate_hz = float(rate_hz)
        # estado
        self.mode = "static"
        self.fix = True
        self.lat = -23.55052
        self.lon = -46.633309
        self.alt = 760.0
        self.speed_kmh = 0.0           # velocidade configurada
        self.cur_speed_kmh = 0.0       # velocidade efetiva (reportada)
        self.heading = 0.0
        self.sats = 9
        self.hdop = 0.9
        self.sync_can_speed = False
        self.sync_dir = "from_can"     # 'from_can' (CAN manda) | 'to_can' (GPS escreve vehicle_speed no CAN)
        self.radius_m = 300.0
        self.loop = True
        self.route = None
        self.route_dist = 0.0
        self._center = (self.lat, self.lon)
        self._theta = 0.0              # ângulo no círculo (rad, a partir do norte, horário)
        self._nmea_tail = collections.deque(maxlen=12)
        self._last_step = None
        self._tick = 0

    # --- callbacks --------------------------------------------------------
    def on_nmea(self, cb):
        with self._lock:
            self._nmea_cbs.append(cb)
        return cb

    def on_ubx(self, cb):
        with self._lock:
            self._ubx_cbs.append(cb)
        return cb

    # --- ciclo de vida ----------------------------------------------------------
    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._last_step = time.monotonic()
        if self.tcp_port is not None and self._srv is None:
            self._start_tcp()
        self._thread = threading.Thread(target=self._run, name="gps-sim", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self._stop_tcp()

    def _run(self):
        nxt = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now < nxt and self._stop.wait(nxt - now):
                break
            nxt += 1.0 / max(0.05, self.rate_hz)
            if time.monotonic() - nxt > 5:
                nxt = time.monotonic()
            try:
                self.step()
            except Exception:
                pass

    # --- simulação -----------------------------------------------------------------
    def step(self, dt=None):
        """Avança a simulação `dt` s (ou o tempo real desde o último passo), emite NMEA/UBX e
        devolve a lista de sentenças NMEA geradas (útil em testes)."""
        with self._lock:
            now = time.monotonic()
            if dt is None:
                dt = 0.0 if self._last_step is None else now - self._last_step
            self._last_step = now
            self._advance(max(0.0, dt))
            lines = self._build_nmea()
            ubx = self._build_ubx()
            for ln in lines:
                self._nmea_tail.append(ln.strip())
            cbs = list(self._nmea_cbs)
            ucbs = list(self._ubx_cbs)
            clients = list(self._clients)
        blob = "".join(lines)
        for ln in lines:
            for cb in cbs:
                try:
                    cb(ln)
                except Exception:
                    pass
        for u in ubx:
            for cb in ucbs:
                try:
                    cb(u)
                except Exception:
                    pass
        if clients:
            data = blob.encode("ascii")
            for c in clients:
                try:
                    c.sendall(data)
                except OSError:
                    self._drop_client(c)
        return lines

    def _can_speed(self):
        try:
            return float(self.can.get_signal("vehicle_speed"))
        except Exception:
            return None

    def _effective_speed(self):
        if self.mode == "static":
            return 0.0
        if self.sync_can_speed and self.can is not None and self.sync_dir == "from_can":
            v = self._can_speed()
            if v is not None:
                return max(0.0, v)
        return max(0.0, self.speed_kmh)

    def _advance(self, dt):
        v = self._effective_speed()
        self.cur_speed_kmh = v
        dist = v / 3.6 * dt
        if self.mode == "manual" and dist > 0:
            self.lat, self.lon = destination(self.lat, self.lon, self.heading, dist)
        elif self.mode == "circle":
            r = max(1.0, self.radius_m)
            self._theta = (self._theta + dist / r) % (2 * math.pi)
            self.lat, self.lon = destination(self._center[0], self._center[1], math.degrees(self._theta), r)
            self.heading = (math.degrees(self._theta) + 90.0) % 360.0
        elif self.mode == "route" and self.route is not None:
            self.route_dist += dist
            if self.route_dist >= self.route.length_m:
                if self.loop:
                    self.route_dist %= self.route.length_m
                else:
                    self.route_dist = self.route.length_m
                    self.cur_speed_kmh = 0.0
            lat, lon, brg = self.route.at(self.route_dist)
            self.lat, self.lon, self.heading = lat, lon, brg
        if self.sync_can_speed and self.can is not None and self.sync_dir == "to_can" and self.mode in ("route", "circle", "manual"):
            try:
                self.can.set_signal("vehicle_speed", self.cur_speed_kmh)
            except Exception:
                pass

    # --- NMEA ---------------------------------------------------------------------------
    def _sat_view(self, t):
        """Lista plausível de satélites visíveis [(prn, elev, azim, snr|None)]."""
        n_used = max(0, min(12, int(self.sats))) if self.fix else 0
        n_vis = min(12, max(n_used + 2, 4)) if (self.fix or self.sats) else 4
        out = []
        for i in range(n_vis):
            prn = [2, 5, 6, 9, 12, 13, 15, 17, 19, 24, 25, 29][i]
            az = int((i * 63 + t * 0.05) % 360)
            el = int(15 + (i * 37) % 70)
            snr = int(28 + (i * 7) % 20) if (self.fix and i < n_used) else (int(12 + i) if self.fix else None)
            out.append((prn, el, az, snr))
        return out, n_used

    def _build_nmea(self):
        t_unix = self._clock()
        dt = datetime.datetime.utcfromtimestamp(t_unix)
        hhmmss = "%02d%02d%05.2f" % (dt.hour, dt.minute, dt.second + dt.microsecond / 1e6)
        date = "%02d%02d%02d" % (dt.day, dt.month, dt.year % 100)
        lat_s, ns = _lat_nmea(self.lat)
        lon_s, ew = _lon_nmea(self.lon)
        view, n_used = self._sat_view(t_unix)
        spd_kn = self.cur_speed_kmh / KNOT
        hdg = self.heading % 360.0
        out = []
        if self.fix:
            out.append(nmea_sentence("GPGGA,%s,%s,%s,%s,%s,1,%02d,%.1f,%.1f,M,0.0,M,," % (
                hhmmss, lat_s, ns, lon_s, ew, n_used, self.hdop, self.alt)))
            out.append(nmea_sentence("GPRMC,%s,A,%s,%s,%s,%s,%.2f,%.1f,%s,,,A" % (
                hhmmss, lat_s, ns, lon_s, ew, spd_kn, hdg, date)))
        else:
            out.append(nmea_sentence("GPGGA,%s,,,,,0,00,99.99,,M,,M,," % hhmmss))
            out.append(nmea_sentence("GPRMC,%s,V,,,,,,,%s,,,N" % (hhmmss, date)))
        prns = ["%02d" % v[0] for v in view[:n_used]]
        prns += [""] * (12 - len(prns))
        if self.fix:
            pdop = self.hdop * 1.4
            vdop = max(self.hdop, math.sqrt(max(0.0, pdop * pdop - self.hdop * self.hdop)))
            out.append(nmea_sentence("GPGSA,A,3,%s,%.1f,%.1f,%.1f" % (",".join(prns), pdop, self.hdop, vdop)))
        else:
            out.append(nmea_sentence("GPGSA,A,1,,,,,,,,,,,,,99.99,99.99,99.99"))
        # GSV: 4 satélites por sentença
        msgs = [view[i:i + 4] for i in range(0, len(view), 4)] or [[]]
        for mi, grp in enumerate(msgs, 1):
            f = "GPGSV,%d,%d,%02d" % (len(msgs), mi, len(view))
            for prn, el, az, snr in grp:
                f += ",%02d,%02d,%03d,%s" % (prn, el, az, "" if snr is None else "%02d" % snr)
            out.append(nmea_sentence(f))
        if self.fix:
            out.append(nmea_sentence("GPVTG,%.1f,T,,M,%.2f,N,%.2f,K,A" % (hdg, spd_kn, self.cur_speed_kmh)))
            out.append(nmea_sentence("GPGLL,%s,%s,%s,%s,%s,A,A" % (lat_s, ns, lon_s, ew, hhmmss)))
        else:
            out.append(nmea_sentence("GPVTG,,T,,M,,N,,K,N"))
            out.append(nmea_sentence("GPGLL,,,,,%s,V,N" % hhmmss))
        return out

    # --- UBX --------------------------------------------------------------------------------
    @staticmethod
    def _ecef(lat, lon, h):
        p, l = math.radians(lat), math.radians(lon)
        n = _WGS_A / math.sqrt(1 - _WGS_E2 * math.sin(p) ** 2)
        return ((n + h) * math.cos(p) * math.cos(l), (n + h) * math.cos(p) * math.sin(l),
                (n * (1 - _WGS_E2) + h) * math.sin(p))

    def _build_ubx(self):
        if not self._ubx_cbs:
            return []
        t = self._clock()
        dt = datetime.datetime.utcfromtimestamp(t)
        gps_dt = dt + datetime.timedelta(seconds=LEAP_SECONDS)
        delta = gps_dt - GPS_EPOCH
        week = delta.days // 7
        tow_ms = int(((delta.days % 7) * 86400 + delta.seconds) * 1000 + dt.microsecond // 1000)
        fix = 3 if self.fix else 0
        nsv = max(0, min(255, int(self.sats))) if self.fix else 0
        lon_e7 = int(round(self.lon * 1e7))
        lat_e7 = int(round(self.lat * 1e7))
        h_mm = int(round(self.alt * 1000))
        hacc = int(round(max(1.0, self.hdop * 2.5) * 1000))
        vacc = int(round(max(1.0, self.hdop * 4.0) * 1000))
        v_ms = self.cur_speed_kmh / 3.6
        hdg = self.heading % 360.0
        vn = int(round(v_ms * math.cos(math.radians(hdg)) * 1000))
        ve = int(round(v_ms * math.sin(math.radians(hdg)) * 1000))
        gspeed = int(round(v_ms * 1000))
        head_e5 = int(round(hdg * 1e5))
        pdop = int(round(self.hdop * 1.4 * 100))
        valid = 0x07 if self.fix else 0x00           # validDate | validTime | fullyResolved
        flags = 0x01 if self.fix else 0x00           # gnssFixOK
        out = []
        # NAV-PVT (0x01 0x07), 92 bytes
        pvt = struct.pack("<IHBBBBBBIiBBBBiiiiIIiiiiiIIH6xihH",
                          tow_ms, dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, valid,
                          50, dt.microsecond * 1000, fix, flags, 0, nsv,
                          lon_e7, lat_e7, h_mm, h_mm, hacc, vacc,
                          vn, ve, 0, gspeed, head_e5, 500, 1000000, pdop, head_e5, 0, 0)
        out.append(ubx_frame(0x01, 0x07, pvt))
        # NAV-POSLLH (0x01 0x02), 28 bytes
        out.append(ubx_frame(0x01, 0x02, struct.pack("<IiiiiII", tow_ms, lon_e7, lat_e7, h_mm, h_mm, hacc, vacc)))
        # NAV-SOL (0x01 0x06), 52 bytes
        x, y, z = self._ecef(self.lat, self.lon, self.alt)
        cm = lambda m: int(round(m * 100))
        sol = struct.pack("<IihBBiiiIiiiIHBBI", tow_ms, 0, week, fix, flags,
                          cm(x), cm(y), cm(z), int(round(hacc / 10.0)), 0, 0, 0, 10, pdop, 0, nsv, 0)
        out.append(ubx_frame(0x01, 0x06, sol))
        return out

    # --- API de controle -----------------------------------------------------------------------
    def state(self):
        """Formato de GET /api/gps/state."""
        with self._lock:
            route = None
            if self.route is not None:
                prog = 0.0 if not self.route.length_m else min(1.0, self.route_dist / self.route.length_m)
                route = {"name": self.route.name, "points": len(self.route.points),
                         "progress": round(prog, 4), "length_km": round(self.route.length_m / 1000.0, 3)}
            return {"mode": self.mode, "fix": self.fix, "lat": round(self.lat, 7), "lon": round(self.lon, 7),
                    "alt": round(self.alt, 1), "speed_kmh": round(self.cur_speed_kmh, 2),
                    "heading": round(self.heading % 360.0, 1), "sats": int(self.sats), "hdop": self.hdop,
                    "route": route, "sync_can_speed": self.sync_can_speed,
                    "nmea_tail": list(self._nmea_tail)[-6:],
                    "radius_m": self.radius_m, "configured_speed_kmh": self.speed_kmh,
                    "sync_dir": self.sync_dir, "loop": self.loop, "rate_hz": self.rate_hz}

    def set(self, **kw):
        with self._lock:
            allowed = {"lat", "lon", "alt", "speed_kmh", "heading", "sats", "hdop", "fix", "sync_can_speed",
                       "radius_m", "loop", "rate_hz", "sync_dir"}
            bad = set(kw) - allowed
            if bad:
                raise GpsError("parâmetro(s) desconhecido(s): %s" % ", ".join(sorted(bad)))
            if ("lat" in kw) != ("lon" in kw) and ("lat" in kw or "lon" in kw):
                lat = kw.get("lat", self.lat)
                lon = kw.get("lon", self.lon)
                kw["lat"], kw["lon"] = lat, lon
            if "lat" in kw:
                lat, lon = _check_point(kw["lat"], kw["lon"])
                self._jump_locked(lat, lon)
            for k in ("alt", "speed_kmh", "heading", "hdop", "radius_m", "rate_hz"):
                if k in kw:
                    try:
                        v = float(kw[k])
                    except (TypeError, ValueError):
                        raise GpsError("valor inválido para %s: %r" % (k, kw[k]))
                    if v != v or v in (float("inf"), float("-inf")):
                        raise GpsError("valor inválido para %s: %r" % (k, kw[k]))
                    if k in ("speed_kmh", "hdop", "radius_m") and v < 0:
                        raise GpsError("%s não pode ser negativo" % k)
                    if k == "rate_hz" and not (0.05 <= v <= 20):
                        raise GpsError("rate_hz deve estar entre 0.05 e 20")
                    if k == "radius_m" and v < 1:
                        raise GpsError("radius_m deve ser >= 1")
                    if k == "heading":
                        v %= 360.0
                    setattr(self, k, v)
            if "sats" in kw:
                try:
                    self.sats = max(0, min(24, int(kw["sats"])))
                except (TypeError, ValueError):
                    raise GpsError("valor inválido para sats: %r" % (kw["sats"],))
            for k in ("fix", "sync_can_speed", "loop"):
                if k in kw:
                    setattr(self, k, bool(kw[k]))
            if "sync_dir" in kw:
                if kw["sync_dir"] not in ("from_can", "to_can"):
                    raise GpsError("sync_dir deve ser 'from_can' ou 'to_can'")
                self.sync_dir = kw["sync_dir"]

    def _jump_locked(self, lat, lon):
        self.lat, self.lon = lat, lon
        self._center = (lat, lon)
        self._theta = 0.0
        if self.mode == "route":
            self.mode = "manual"                      # saiu da rota
        if self.mode == "circle":
            self.lat, self.lon = destination(lat, lon, 0.0, self.radius_m)

    def jump(self, lat, lon):
        lat, lon = _check_point(lat, lon)
        with self._lock:
            self._jump_locked(lat, lon)

    def set_mode(self, mode, **kw):
        if mode not in MODES:
            raise GpsError("modo inválido: %r (use %s)" % (mode, ", ".join(MODES)))
        with self._lock:
            if mode == "route" and self.route is None:
                raise GpsError("nenhuma rota carregada: envie uma rota (GPX ou pontos) antes de usar o modo route")
            for k in ("radius_m", "speed_kmh", "heading", "sync_can_speed", "loop"):
                if k in kw and kw[k] is not None:
                    self.set(**{k: kw[k]})
            if mode == "circle":
                r = max(1.0, self.radius_m)
                if self.mode != "circle":
                    self._center = (self.lat, self.lon)
                    self._theta = 0.0
                if "center_lat" in kw and "center_lon" in kw:
                    self._center = _check_point(kw["center_lat"], kw["center_lon"])
                    self._theta = 0.0
                if self.speed_kmh <= 0 and not self.sync_can_speed:
                    self.speed_kmh = 30.0
                self.lat, self.lon = destination(self._center[0], self._center[1], math.degrees(self._theta), r)
            if mode == "route":
                if self.speed_kmh <= 0 and not self.sync_can_speed:
                    self.speed_kmh = 50.0
                lat, lon, brg = self.route.at(self.route_dist)
                self.lat, self.lon, self.heading = lat, lon, brg
            if mode == "manual" and self.mode == "circle":
                self._center = (self.lat, self.lon)
            self.mode = mode
            if mode == "static":
                self.cur_speed_kmh = 0.0

    def load_route(self, name, gpx=None, points=None, speed_kmh=50, loop=True):
        """Carrega uma rota (GPX em texto OU lista de [lat,lon]) e entra no modo route."""
        if (gpx is None) == (points is None):
            raise GpsError("informe 'gpx' (texto) OU 'points' (lista de [lat, lon])")
        if gpx is not None:
            pts = parse_gpx(gpx)
        else:
            if not isinstance(points, (list, tuple)) or not points:
                raise GpsError("rota sem pontos")
            pts = []
            for p in points:
                if not isinstance(p, (list, tuple)) or len(p) < 2:
                    if isinstance(p, dict) and "lat" in p and "lon" in p:
                        p = (p["lat"], p["lon"])
                    else:
                        raise GpsError("ponto inválido na rota: %r" % (p,))
                pts.append((p[0], p[1]))
        route = Route(name or "rota", pts)
        try:
            spd = float(speed_kmh)
        except (TypeError, ValueError):
            raise GpsError("speed_kmh inválido: %r" % (speed_kmh,))
        if spd < 0:
            raise GpsError("speed_kmh não pode ser negativo")
        with self._lock:
            self.route = route
            self.route_dist = 0.0
            self.speed_kmh = spd
            self.loop = bool(loop)
            self.mode = "route"
            self.lat, self.lon, self.heading = route.at(0.0)
            self._center = (self.lat, self.lon)

    # --- TCP ------------------------------------------------------------------------------------------
    def _start_tcp(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", int(self.tcp_port)))
        s.listen(8)
        s.settimeout(0.3)
        self.tcp_port = s.getsockname()[1]
        self._srv = s
        self._tcp_thread = threading.Thread(target=self._accept_loop, name="gps-tcp", daemon=True)
        self._tcp_thread.start()

    def _accept_loop(self):
        srv = self._srv
        while not self._stop.is_set():
            try:
                c, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            c.settimeout(2.0)
            with self._lock:
                self._clients.append(c)
                tail = list(self._nmea_tail)
            if tail:                                   # entrega o último ciclo já ao conectar
                try:
                    c.sendall(("\r\n".join(tail) + "\r\n").encode("ascii"))
                except OSError:
                    self._drop_client(c)

    def _drop_client(self, c):
        with self._lock:
            if c in self._clients:
                self._clients.remove(c)
        try:
            c.close()
        except OSError:
            pass

    def _stop_tcp(self):
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
            self._srv = None
            if self._tcp_thread is not None:
                self._tcp_thread.join(timeout=2)
                self._tcp_thread = None
        with self._lock:
            clients = list(self._clients)
            self._clients = []
        for c in clients:
            try:
                c.close()
            except OSError:
                pass

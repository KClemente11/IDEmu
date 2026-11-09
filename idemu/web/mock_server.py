#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor de TESTE (mock) do IDEmu: implementa todo o contrato de docs/API.md
com dados falsos e serve os arquivos estáticos de idemu/web/ em "/".

Uso:  python3 mock_server.py [--port 8799] [--psdz /pasta/psdzdata]
Somente biblioteca padrão (Python 3.9+).

Dicas de teste:
  * ambiente cujo nome contém "erro" falha aos 60% do build;
  * o display falso mostra a última entrada recebida (rotor, tecla, clique);
  * o rotor/tilt movem a seleção entre 6 blocos no display falso.
"""
import argparse
import datetime
import json
import math
import os
import random
import re
import struct
import sys
import threading
import time
import zlib
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.RLock()
BUILD_SECS = 10.0
BOOT_SECS = 15.0

# --------------------------------------------------------------------------
# Catálogo falso
# --------------------------------------------------------------------------
SERIES = [
    {"id": "F020", "name": "1/2/3/4-Series (F2x/F3x)", "chassis": [
        {"code": "F30", "name": "Série 3 (F30/F31/F34)", "brand": "bmw", "ego_model": "F30"},
        {"code": "F20", "name": "Série 1 (F20/F21)", "brand": "bmw", "ego_model": "F20"},
        {"code": "F22", "name": "Série 2 (F22/F23)", "brand": "bmw", "ego_model": "F22"},
        {"code": "F32", "name": "Série 4 (F32/F33/F36)", "brand": "bmw", "ego_model": "F32"}]},
    {"id": "F010", "name": "5/6/7-Series (F0x/F1x)", "chassis": [
        {"code": "F10", "name": "Série 5 (F10/F11)", "brand": "bmw", "ego_model": "F10"},
        {"code": "F01", "name": "Série 7 (F01/F02)", "brand": "bmw", "ego_model": "F01"},
        {"code": "F12", "name": "Série 6 (F06/F12/F13)", "brand": "bmw", "ego_model": "F12"},
        {"code": "RR5", "name": "Rolls-Royce Ghost (RR4/RR5)", "brand": "rr", "ego_model": "RR5"}]},
    {"id": "F025", "name": "X-Series (F25/F26)", "chassis": [
        {"code": "F25", "name": "X3 (F25)", "brand": "bmw", "ego_model": "F25"},
        {"code": "F26", "name": "X4 (F26)", "brand": "bmw", "ego_model": "F26"}]},
    {"id": "F056", "name": "MINI (F5x)", "chassis": [
        {"code": "F56", "name": "MINI Hatch 3 portas (F56)", "brand": "mini", "ego_model": "F56"},
        {"code": "F55", "name": "MINI Hatch 5 portas (F55)", "brand": "mini", "ego_model": "F55"},
        {"code": "F54", "name": "MINI Clubman (F54)", "brand": "mini", "ego_model": "F54"}]},
    {"id": "I001", "name": "BMW i (I01/I12)", "chassis": [
        {"code": "I01", "name": "BMW i3 (I01)", "brand": "bmw", "ego_model": "I01"},
        {"code": "I12", "name": "BMW i8 (I12)", "brand": "bmw", "ego_model": "I12"}]},
]
MODEL_NAMES = {"F30": "320i", "F20": "118i", "F22": "220i", "F32": "428i", "F10": "528i", "F01": "740i",
               "F12": "640i", "RR5": "Ghost", "F25": "xDrive28i", "F26": "xDrive35i", "F56": "Cooper S",
               "F55": "Cooper", "F54": "Cooper Clubman", "I01": "i3", "I12": "i8"}

BY_SERIES = {
    "F020": {"roles": {"os": "0000271a", "brand": {"bmw": "00002719", "mini": "00002716", "rr": "00002718"}, "hmi": "00002720"}},
    "F010": {"roles": {"os": "0000271a", "brand": {"bmw": "00002719", "mini": "00002716", "rr": "00002718"}, "hmi": "00002722"}},
    "F025": {"roles": {"os": "0000271a", "brand": {"bmw": "00002719", "mini": "00002716", "rr": "00002718"}, "hmi": "00002722"}},
    "F056": {"roles": {"os": "0000271a", "brand": {"bmw": "00002719", "mini": "00002716", "rr": "00002718"}, "hmi": "00002720"}},
    "I001": {"roles": {"os": "0000271c", "brand": {"bmw": "00002719", "mini": "00002716", "rr": "00002718"}, "hmi": "00002723"}},
}
# (papel, id, rótulo, ajuda, [(versão, tamanho)])
ROLE_DEFS = [
    ("os", "0000271a", "Sistema base (QNX, serviços, drivers)",
     "Imagem do sistema operacional do head unit: kernel QNX, serviços e drivers. Sem ela o emulador não inicia.",
     [("007_051_002", 612401152), ("007_050_001", 609288192), ("007_049_000", 598016000)]),
    ("os", "0000271c", "Sistema base (QNX, serviços, drivers) – BMW i",
     "Variante do sistema base usada pelos modelos BMW i.",
     [("007_051_002", 640221184), ("007_048_003", 631242752)]),
    ("brand", "00002719", "Dados da marca BMW",
     "Temas, sons e telas específicas da marca BMW.",
     [("007_051_001", 118220800), ("007_049_001", 115343360)]),
    ("brand", "00002716", "Dados da marca MINI",
     "Temas, sons e telas específicas da marca MINI.",
     [("007_051_001", 121634816), ("007_049_001", 119537664)]),
    ("brand", "00002718", "Dados da marca Rolls-Royce",
     "Temas, sons e telas específicas da marca Rolls-Royce.",
     [("007_050_000", 117440512)]),
    ("hmi", "00002720", "Interface HMI (iDrive 6, tiles)",
     "A interface gráfica (HMI) do iDrive: menus, tiles e navegação por rotor. Define a aparência da tela.",
     [("007_051_003", 893386752), ("007_050_002", 889192448), ("007_048_000", 880803840)]),
    ("hmi", "00002722", "Interface HMI (iDrive 6, tiles) – Séries 5/6/7/X",
     "Interface gráfica (HMI) para Séries 5/6/7 e X-Series.",
     [("007_051_001", 902823936), ("007_049_002", 897581056)]),
    ("hmi", "00002723", "Interface HMI (iDrive 6) – BMW i",
     "Interface gráfica (HMI) para os modelos BMW i.",
     [("007_050_004", 911212544)]),
]
LANGUAGES = [("pt_BR", "Português (Brasil)"), ("pt_PT", "Português (Portugal)"), ("en_GB", "English (UK)"),
             ("en_US", "English (US)"), ("de_DE", "Deutsch"), ("es_ES", "Español"), ("fr_FR", "Français"),
             ("it_IT", "Italiano"), ("nl_NL", "Nederlands"), ("ja_JP", "日本語")]
COUNTRIES = [("BR", "Brasil"), ("PT", "Portugal"), ("DE", "Alemanha"), ("GB", "Reino Unido"), ("US", "Estados Unidos"),
             ("ES", "Espanha"), ("FR", "França"), ("IT", "Itália"), ("AR", "Argentina"), ("JP", "Japão")]
DISPLAYS = [("10_25_1440x540", '10,25" 1440x540'), ("8_8_1280x480", '8,8" 1280x480'), ("6_5_800x480", '6,5" 800x480')]
HMI_VERSIONS = [("id6_light", "iDrive 6 (tiles)"), ("id6_full", "iDrive 6 (completo)"), ("id5", "iDrive 5")]

ENV_VERSION = "0.1"


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------
SETTINGS = {"psdz_path": None}
ENVS = {}          # id -> Env
BUILDS = {}        # id -> {"t0", "log":[], "emitted":int}
RUN = {"state": "stopped", "env": None, "t0": None, "t_run": None, "boot_step": "", "boot_pct": 0, "error": None,
       "last_input": "", "last_input_t": 0, "click": None, "click_t": 0, "sel": 0, "pressed": False}
LOGS = {"console": deque(maxlen=1500), "qemu": deque(maxlen=1500), "renderer": deque(maxlen=1500),
        "guest": deque(maxlen=1500)}

BOOT_STEPS = [(0, "Iniciando QEMU (ARM Cortex-A9)"), (12, "Carregando kernel QNX"), (30, "Montando partições SWFL"),
              (50, "Iniciando serviços do sistema"), (68, "Iniciando HMI do iDrive"),
              (85, "Conectando renderizador gráfico"), (95, "Aguardando primeira imagem da tela")]
BUILD_STEPS = [(0, "Validando arquivos SWFL"), (15, "Extraindo imagem do sistema base"), (40, "Aplicando dados da marca"),
               (60, "Integrando HMI"), (78, "Gerando codificação (FA/VIN)"), (92, "Criando disco virtual"),
               (100, "Concluído")]


def log(name, line):
    LOGS[name].append("[%s] %s" % (time.strftime("%H:%M:%S"), line))


def step_for(table, pct):
    s = table[0][1]
    for p, t in table:
        if pct >= p:
            s = t
    return s


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "ambiente"


def unique_id(name):
    base = slug(name)
    i, cand = 2, base
    while cand in ENVS:
        cand = "%s-%d" % (base, i)
        i += 1
    return cand


def default_coding():
    return {"language": "pt_BR", "units": "metric", "country": "BR", "vin": "WBA8A9C50GK000001", "year": 2017,
            "month": 7, "lci": 1, "display": "10_25_1440x540", "hmi_version": "id6_light", "navi": "keine_navi"}


def default_net():
    return {"ssh_port": 2222, "can_port": 29536, "gps_port": 29537}


def make_env(name, series, chassis, brand, swfl, coding, net, build_state="none"):
    eid = unique_id(name)
    e = {"id": eid, "name": name, "created": now_iso(), "series": series, "chassis": chassis, "brand": brand,
         "model_name": MODEL_NAMES.get(chassis, chassis), "swfl": swfl,
         "coding": dict(default_coding(), **(coding or {})), "net": dict(default_net(), **(net or {})),
         "build": {"state": build_state, "pct": 100 if build_state == "ready" else 0,
                   "step": "Concluído" if build_state == "ready" else "",
                   "error": None, "built_at": now_iso() if build_state == "ready" else None}}
    ENVS[eid] = e
    return e


# --------------------------------------------------------------------------
# CAN falso
# --------------------------------------------------------------------------
def sig(name, label, unit, mn, mx, value, can_id, cycle, step=1, kind="number", enum=None):
    return {"name": name, "label": label, "unit": unit, "min": mn, "max": mx, "value": value, "can_id": can_id,
            "cycle_ms": cycle, "step": step, "kind": kind, "enum": enum}


SIGNAL_GROUPS = [
    ("Motor", [
        sig("vehicle_speed", "Velocidade", "km/h", 0, 300, 0, 0x1A0, 20),
        sig("engine_rpm", "Rotação do motor", "rpm", 0, 7000, 0, 0x0F3, 20, 50),
        sig("coolant_temp", "Temperatura do líquido de arrefecimento", "°C", 0, 130, 20, 0x1D0, 100),
        sig("fuel_level", "Nível de combustível", "%", 0, 100, 65, 0x349, 500),
        sig("accel_pedal", "Pedal do acelerador", "%", 0, 100, 0, 0x0A8, 20),
    ]),
    ("Carroceria", [
        sig("ignition", "Ignição", "", 0, 3, 0, 0x130, 100, 1, "enum",
            {"0": "Desligada", "1": "Acessórios", "2": "Ligada", "3": "Partida"}),
        sig("gear", "Marcha", "", 0, 4, 0, 0x3FD, 100, 1, "enum",
            {"0": "P – Estacionar", "1": "R – Ré", "2": "N – Neutro", "3": "D – Drive", "4": "S – Sport"}),
        sig("handbrake", "Freio de estacionamento", "", 0, 1, 1, 0x34F, 200, 1, "bool"),
        sig("door_driver", "Porta do motorista aberta", "", 0, 1, 0, 0x2FC, 200, 1, "bool"),
        sig("turn_signal", "Pisca-pisca", "", 0, 3, 0, 0x1F6, 100, 1, "enum",
            {"0": "Desligado", "1": "Esquerdo", "2": "Direito", "3": "Alerta"}),
        sig("headlights", "Faróis", "", 0, 3, 0, 0x314, 200, 1, "enum",
            {"0": "Apagados", "1": "Lanterna", "2": "Baixo", "3": "Alto"}),
    ]),
    ("Ambiente", [
        sig("ext_temp", "Temperatura externa", "°C", -40, 60, 24.5, 0x2CA, 1000, 0.5),
        sig("night_mode", "Modo noturno do display", "", 0, 1, 0, 0x2A0, 500, 1, "bool"),
        sig("rain_sensor", "Sensor de chuva", "", 0, 1, 0, 0x2A6, 500, 1, "bool"),
    ]),
    ("Direção e freios", [
        sig("steering_angle", "Ângulo do volante", "°", -540, 540, 0, 0x0C4, 10, 1),
        sig("brake_pedal", "Pedal de freio", "", 0, 1, 0, 0x0B4, 20, 1, "bool"),
    ]),
]
SIGNALS = {s["name"]: s for _, g in SIGNAL_GROUPS for s in g}
SCENARIOS = [
    {"id": "city", "name": "Cidade", "desc": "Anda e para em baixa velocidade (0–50 km/h), com piscas."},
    {"id": "highway", "name": "Rodovia", "desc": "Velocidade de cruzeiro em torno de 120 km/h."},
    {"id": "parking", "name": "Manobra de estacionamento", "desc": "Marcha à ré em velocidade muito baixa."},
    {"id": "idle", "name": "Marcha lenta", "desc": "Ignição ligada, carro parado, motor em marcha lenta."},
]
CAN = {"seq": 0, "frames": deque(maxlen=6000), "due": {}, "scenario": None, "recording": False,
       "rec_frames": [], "recordings": [], "replay": None}
GPS = {"mode": "circle", "fix": True, "lat": -23.5505, "lon": -46.6333, "alt": 760.0, "speed_kmh": 40.0,
       "heading": 0.0, "sats": 9, "hdop": 0.9, "route": None, "route_pts": [], "route_loop": True, "route_pos": 0.0,
       "sync_can_speed": False, "radius_m": 300.0, "center": (-23.5505, -46.6333), "ang": 0.0, "nmea": deque(maxlen=40)}


def can_frame(cid, data_hex, direction="tx", name=None):
    CAN["seq"] += 1
    fr = {"seq": CAN["seq"], "t": round(time.time() - T0, 3), "id": "%03X" % cid if isinstance(cid, int) else cid,
          "dlc": len(data_hex) // 2, "data": data_hex.upper(), "dir": direction, "name": name}
    CAN["frames"].append(fr)
    if CAN["recording"]:
        CAN["rec_frames"].append(fr)
    return fr


def encode_signal(s):
    v = int(round((s["value"] - s["min"]) / (s["step"] or 1)))
    v &= 0xFFFF
    CAN.setdefault("ctr", 0)
    CAN["ctr"] = (CAN["ctr"] + 1) & 0xFF
    return "%02X%02X%02X%02X%02X%02X%02X%02X" % (v & 0xFF, v >> 8, int(s["can_id"]) & 0xFF, 0, 0, 0, CAN["ctr"] & 0x0F, 0xA5)


# --------------------------------------------------------------------------
# Simulação (thread de tick)
# --------------------------------------------------------------------------
T0 = time.time()
M_PER_DEG = 111320.0


def nmea_sum(body):
    c = 0
    for ch in body:
        c ^= ord(ch)
    return "$%s*%02X" % (body, c)


def fmt_lat(lat):
    a = abs(lat)
    d = int(a)
    return "%02d%07.4f,%s" % (d, (a - d) * 60, "N" if lat >= 0 else "S")


def fmt_lon(lon):
    a = abs(lon)
    d = int(a)
    return "%03d%07.4f,%s" % (d, (a - d) * 60, "E" if lon >= 0 else "W")


def route_length_m(pts):
    t = 0.0
    for a, b in zip(pts, pts[1:]):
        t += seg_m(a, b)
    return t


def seg_m(a, b):
    dlat = (b[0] - a[0]) * M_PER_DEG
    dlon = (b[1] - a[1]) * M_PER_DEG * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dlat, dlon)


def move(lat, lon, heading_deg, meters):
    h = math.radians(heading_deg)
    lat += meters * math.cos(h) / M_PER_DEG
    lon += meters * math.sin(h) / (M_PER_DEG * math.cos(math.radians(lat)))
    return lat, lon


def tick_gps(dt):
    g = GPS
    v = g["speed_kmh"] / 3.6
    mode = g["mode"]
    if mode == "circle":
        r = max(10.0, g["radius_m"])
        g["ang"] += (v / r) * dt
        clat, clon = g["center"]
        g["lat"] = clat + r * math.sin(g["ang"]) / M_PER_DEG
        g["lon"] = clon + r * math.cos(g["ang"]) / (M_PER_DEG * math.cos(math.radians(clat)))
        g["heading"] = (-math.degrees(g["ang"])) % 360.0
    elif mode == "route" and g["route_pts"]:
        pts = g["route_pts"]
        total = route_length_m(pts)
        if total > 0:
            g["route_pos"] += v * dt
            if g["route_pos"] >= total:
                g["route_pos"] = 0.0 if g["route_loop"] else total
            d = g["route_pos"]
            for a, b in zip(pts, pts[1:]):
                L = seg_m(a, b)
                if d <= L or (a, b) == (pts[-2], pts[-1]):
                    f = 0 if L == 0 else min(1.0, d / L)
                    g["lat"] = a[0] + (b[0] - a[0]) * f
                    g["lon"] = a[1] + (b[1] - a[1]) * f
                    dy = (b[0] - a[0]) * M_PER_DEG
                    dx = (b[1] - a[1]) * M_PER_DEG * math.cos(math.radians(a[0]))
                    if L > 0:
                        g["heading"] = (math.degrees(math.atan2(dx, dy))) % 360.0
                    break
                d -= L
            g["route"]["progress"] = round(g["route_pos"] / total, 3)
    elif mode == "manual" and v > 0:
        g["lat"], g["lon"] = move(g["lat"], g["lon"], g["heading"], v * dt)
    elif mode == "static":
        pass
    if g["sync_can_speed"] and RUN["state"] in ("booting", "running"):
        SIGNALS["vehicle_speed"]["value"] = round(g["speed_kmh"], 1)


_nmea_t = [0.0]


def tick_nmea():
    g = GPS
    if time.time() - _nmea_t[0] < 1.0:
        return
    _nmea_t[0] = time.time()
    ts = time.strftime("%H%M%S.00", time.gmtime())
    ds = time.strftime("%d%m%y", time.gmtime())
    gga = "GPGGA,%s,%s,%s,%d,%02d,%.1f,%.1f,M,0.0,M,," % (ts, fmt_lat(g["lat"]), fmt_lon(g["lon"]),
                                                      1 if g["fix"] else 0, g["sats"], g["hdop"], g["alt"])
    rmc = "GPRMC,%s,%s,%s,%s,%.1f,%.1f,%s,,,A" % (ts, "A" if g["fix"] else "V", fmt_lat(g["lat"]), fmt_lon(g["lon"]),
                                                  g["speed_kmh"] / 1.852, g["heading"], ds)
    g["nmea"].append(nmea_sum(gga))
    g["nmea"].append(nmea_sum(rmc))


def tick_scenario(t):
    sc = CAN["scenario"]
    if not sc:
        return
    S = SIGNALS
    if sc == "city":
        sp = max(0.0, 25 + 28 * math.sin(t / 7.0))
        S["vehicle_speed"]["value"] = round(sp, 1)
        S["engine_rpm"]["value"] = round(800 + sp * 38, -1)
        S["gear"]["value"] = 3
        S["ignition"]["value"] = 2
        S["turn_signal"]["value"] = 1 if int(t / 6) % 5 == 0 else (2 if int(t / 6) % 5 == 3 else 0)
        S["brake_pedal"]["value"] = 1 if math.cos(t / 7.0) < -0.7 else 0
        S["accel_pedal"]["value"] = round(max(0, 40 * math.cos(t / 7.0)), 0)
    elif sc == "highway":
        sp = 120 + 10 * math.sin(t / 11.0)
        S["vehicle_speed"]["value"] = round(sp, 1)
        S["engine_rpm"]["value"] = round(2400 + 120 * math.sin(t / 11.0), -1)
        S["gear"]["value"] = 3
        S["ignition"]["value"] = 2
        S["accel_pedal"]["value"] = 28
        S["steering_angle"]["value"] = round(8 * math.sin(t / 5.0), 0)
    elif sc == "parking":
        S["vehicle_speed"]["value"] = round(3 + 2 * math.sin(t / 3.0), 1)
        S["gear"]["value"] = 1
        S["ignition"]["value"] = 2
        S["engine_rpm"]["value"] = 900
        S["steering_angle"]["value"] = round(360 * math.sin(t / 4.0), 0)
    elif sc == "idle":
        S["vehicle_speed"]["value"] = 0
        S["engine_rpm"]["value"] = 780 + int(20 * math.sin(t))
        S["gear"]["value"] = 0
        S["ignition"]["value"] = 2


_last_tick = [time.time()]
_log_t = [0.0, 0.0, 0.0]


def tick():
    now = time.time()
    dt = now - _last_tick[0]
    _last_tick[0] = now
    with LOCK:
        # ---- builds
        for eid, b in list(BUILDS.items()):
            e = ENVS.get(eid)
            if not e or e["build"]["state"] != "building":
                continue
            el = now - b["t0"]
            fails = "erro" in e["name"].lower()
            pct = min(100.0, el / BUILD_SECS * 100.0)
            if fails and pct >= 60:
                e["build"].update(state="error", step="Falha", error="Falha simulada ao integrar o HMI (nome contém 'erro').")
                b["log"].append("[ERRO] Falha simulada ao integrar o HMI")
                continue
            e["build"]["pct"] = int(pct)
            e["build"]["step"] = step_for(BUILD_STEPS, pct)
            want = int(pct / 100.0 * 40)
            while b["emitted"] < want:
                b["emitted"] += 1
                b["log"].append("[build] %s ... %d/40" % (step_for(BUILD_STEPS, b["emitted"] * 2.5), b["emitted"]))
            if pct >= 100:
                e["build"].update(state="ready", pct=100, step="Concluído", error=None, built_at=now_iso())
                b["log"].append("[build] Ambiente pronto.")
        # ---- boot
        if RUN["state"] == "booting":
            el = now - RUN["t0"]
            pct = min(100.0, el / BOOT_SECS * 100.0)
            RUN["boot_pct"] = int(pct)
            RUN["boot_step"] = step_for(BOOT_STEPS, pct)
            if now - _log_t[0] > 0.8:
                _log_t[0] = now
                log("qemu", "boot: %s (%d%%)" % (RUN["boot_step"], pct))
                log("console", "IDEmu: %s" % RUN["boot_step"])
            if pct >= 100:
                RUN.update(state="running", t_run=now, boot_pct=100, boot_step="Sistema pronto")
                log("console", "Sistema pronto.")
                log("renderer", "Primeiro quadro entregue.")
        if RUN["state"] == "running":
            t = now - RUN["t0"]
            if now - _log_t[1] > 2.0:
                _log_t[1] = now
                log("renderer", "frame %d (%.1f fps)" % (frame_seq(), 4.0))
                log("guest", "hmi: heartbeat ok, uptime %ds" % t)
            if now - _log_t[2] > 5.0:
                _log_t[2] = now
                log("console", "can: %d quadros/s" % random.randint(60, 120))
        # ---- GPS / cenários / CAN
        if RUN["state"] in ("booting", "running"):
            tick_gps(dt)
            tick_nmea()
            tick_scenario(now - T0)
            if RUN["state"] == "running":
                for name, s in SIGNALS.items():
                    due = CAN["due"].get(name, 0)
                    if now >= due:
                        CAN["due"][name] = now + max(0.05, s["cycle_ms"] / 1000.0)
                        can_frame(s["can_id"], encode_signal(s), "tx", name)
                if random.random() < 0.25:
                    can_frame(random.choice([0x1D6, 0x2F7, 0x3A0, 0x5E0]), "%016X" % random.getrandbits(64), "rx", None)
                rp = CAN["replay"]
                if rp:
                    if now > rp["until"]:
                        if rp["loop"]:
                            rp["until"] = now + 4
                        else:
                            CAN["replay"] = None
                    elif random.random() < 0.6:
                        can_frame(random.choice([0x1A0, 0x130, 0x0F3]), "%016X" % random.getrandbits(64), "tx", None)


def ticker():
    while True:
        try:
            tick()
        except Exception as ex:  # noqa
            print("tick erro:", ex, file=sys.stderr)
        time.sleep(0.05)


# --------------------------------------------------------------------------
# PNG falso (1440x540) em Python puro
# --------------------------------------------------------------------------
W, H = 1440, 540
FONT_SRC = {
    "A": ".###./#...#/#...#/#####/#...#/#...#/#...#", "B": "####./#...#/#...#/####./#...#/#...#/####.",
    "C": ".###./#...#/#..../#..../#..../#...#/.###.", "D": "####./#...#/#...#/#...#/#...#/#...#/####.",
    "E": "#####/#..../#..../####./#..../#..../#####", "F": "#####/#..../#..../####./#..../#..../#....",
    "G": ".###./#...#/#..../#.###/#...#/#...#/.###.", "H": "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    "I": ".###./..#../..#../..#../..#../..#../.###.", "J": "..###/...#./...#./...#./...#./#..#./.##..",
    "K": "#...#/#..#./#.#../##.../#.#../#..#./#...#", "L": "#..../#..../#..../#..../#..../#..../#####",
    "M": "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#", "N": "#...#/##..#/#.#.#/#..##/#...#/#...#/#...#",
    "O": ".###./#...#/#...#/#...#/#...#/#...#/.###.", "P": "####./#...#/#...#/####./#..../#..../#....",
    "Q": ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#", "R": "####./#...#/#...#/####./#.#../#..#./#...#",
    "S": ".####/#..../#..../.###./....#/....#/####.", "T": "#####/..#../..#../..#../..#../..#../..#..",
    "U": "#...#/#...#/#...#/#...#/#...#/#...#/.###.", "V": "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    "W": "#...#/#...#/#...#/#.#.#/#.#.#/##.##/#...#", "X": "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    "Y": "#...#/#...#/.#.#./..#../..#../..#../..#..", "Z": "#####/....#/...#./..#../.#.../#..../#####",
    "0": ".###./#...#/#..##/#.#.#/##..#/#...#/.###.", "1": "..#../.##../..#../..#../..#../..#../.###.",
    "2": ".###./#...#/....#/...#./..#../.#.../#####", "3": "####./....#/....#/.###./....#/....#/####.",
    "4": "...#./..##./.#.#./#..#./#####/...#./...#.", "5": "#####/#..../####./....#/....#/#...#/.###.",
    "6": ".###./#..../#..../####./#...#/#...#/.###.", "7": "#####/....#/...#./..#../.#.../.#.../.#...",
    "8": ".###./#...#/#...#/.###./#...#/#...#/.###.", "9": ".###./#...#/#...#/.####/....#/....#/.###.",
    " ": "...../...../...../...../...../...../.....", ":": "...../..#../..#../...../..#../..#../.....",
    ".": "...../...../...../...../...../.##../.##..", "-": "...../...../...../#####/...../...../.....",
    "+": "...../..#../..#../#####/..#../..#../.....", ",": "...../...../...../...../.##../..#../.#...",
    "/": "....#/....#/...#./..#../.#.../#..../#....", "=": "...../...../#####/...../#####/...../.....",
    "_": "...../...../...../...../...../...../#####", "(": "..#../.#.../#..../#..../#..../.#.../..#..",
    ")": "..#../...#./....#/....#/....#/...#./..#..", "%": "##..#/##..#/...#./..#../.#.../#..##/#..##",
}
FONT = {k: v.split("/") for k, v in FONT_SRC.items()}
_BASE = [None]
_PNG_CACHE = {"seq": None, "data": b""}
TILES = [("RADIO", (36, 96, 168)), ("NAV", (30, 132, 112)), ("MIDIA", (150, 84, 40)),
         ("TEL", (110, 62, 150)), ("VEICULO", (60, 70, 90)), ("AJUSTES", (150, 50, 70))]
TILE_POS = [(40 + (i % 3) * 470, 100 + (i // 3) * 150) for i in range(6)]
TILE_W, TILE_H = 440, 130


def fill_rect(buf, x, y, w, h, color):
    x0, x1 = max(0, x), min(W, x + w)
    if x1 <= x0:
        return
    px = bytes(color) * (x1 - x0)
    for yy in range(max(0, y), min(H, y + h)):
        o = (yy * W + x0) * 3
        buf[o:o + len(px)] = px


def draw_text(buf, x, y, text, scale, color):
    cx = x
    for ch in str(text).upper():
        g = FONT.get(ch)
        if g is None:
            cx += 6 * scale
            continue
        for ry, row in enumerate(g):
            rx = 0
            while rx < 5:
                if row[rx] == "#":
                    run = rx
                    while run < 5 and row[run] == "#":
                        run += 1
                    fill_rect(buf, cx + rx * scale, y + ry * scale, (run - rx) * scale, scale, color)
                    rx = run
                else:
                    rx += 1
        cx += 6 * scale
    return cx


def base_frame():
    if _BASE[0] is None:
        buf = bytearray(W * H * 3)
        for y in range(H):
            f = y / float(H)
            c = (int(16 - 12 * f), int(26 - 20 * f), int(48 - 36 * f))
            o = y * W * 3
            buf[o:o + W * 3] = bytes(c) * W
        fill_rect(buf, 0, 0, W, 76, (18, 30, 56))
        fill_rect(buf, 0, 76, W, 3, (47, 140, 255))
        draw_text(buf, 28, 22, "IDEMU MOCK  NBT EVO ID6", 5, (210, 225, 250))
        for (label, col), (tx, ty) in zip(TILES, TILE_POS):
            fill_rect(buf, tx, ty, TILE_W, TILE_H, col)
            fill_rect(buf, tx, ty + TILE_H - 6, TILE_W, 6, tuple(int(c * 0.6) for c in col))
            draw_text(buf, tx + 24, ty + 24, label, 7, (240, 245, 255))
        _BASE[0] = buf
    return _BASE[0]


def frame_seq():
    if RUN["state"] != "running" or not RUN["t_run"]:
        return 0
    return int((time.time() - RUN["t_run"]) * 4) + 1


def png_chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def render_png(seq):
    buf = bytearray(base_frame())
    # seleção
    sel = RUN["sel"] % 6
    tx, ty = TILE_POS[sel]
    for (rx, ry, rw, rh) in ((tx - 6, ty - 6, TILE_W + 12, 6), (tx - 6, ty + TILE_H, TILE_W + 12, 6),
                             (tx - 6, ty, 6, TILE_H), (tx + TILE_W, ty, 6, TILE_H)):
        fill_rect(buf, rx, ry, rw, rh, (255, 255, 255) if not RUN["pressed"] else (255, 210, 60))
    # relógio
    draw_text(buf, W - 28 - 6 * 6 * 8, 22, time.strftime("%H:%M:%S"), 6, (255, 255, 255))
    # varredura
    fill_rect(buf, (seq * 36) % (W - 160), 82, 160, 6, (47, 140, 255))
    # telemetria
    env = ENVS.get(RUN["env"] or "", {})
    spd = SIGNALS["vehicle_speed"]["value"]
    rpm = SIGNALS["engine_rpm"]["value"]
    draw_text(buf, 40, 406, "VEL %d KM/H  RPM %d" % (spd, rpm), 4, (140, 220, 255))
    draw_text(buf, 40, 448, "GPS %.5f %.5f" % (GPS["lat"], GPS["lon"]), 3, (170, 190, 220))
    draw_text(buf, 40, 486, "AMBIENTE %s  QUADRO %d" % (env.get("name", "-"), seq), 3, (120, 140, 170))
    if time.time() - RUN["last_input_t"] < 6 and RUN["last_input"]:
        draw_text(buf, 700, 406, "ENTRADA: " + RUN["last_input"], 4, (255, 215, 90))
    if RUN["click"] and time.time() - RUN["click_t"] < 4:
        cx, cy = RUN["click"]
        fill_rect(buf, cx - 18, cy - 2, 37, 5, (255, 80, 80))
        fill_rect(buf, cx - 2, cy - 18, 5, 37, (255, 80, 80))
    rows = []
    stride = W * 3
    for y in range(H):
        o = y * stride
        rows.append(b"\x00" + bytes(buf[o:o + stride]))
    raw = b"".join(rows)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(raw, 1)) + png_chunk(b"IEND", b""))


# --------------------------------------------------------------------------
# Ações da API
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status, msg):
        Exception.__init__(self, msg)
        self.status = status
        self.msg = msg


def need(body, *keys):
    for k in keys:
        if k not in body or body[k] in (None, ""):
            raise ApiError(400, "Campo obrigatório ausente: %s." % k)


def get_env(eid):
    e = ENVS.get(eid)
    if not e:
        raise ApiError(404, "Ambiente não encontrado: %s." % eid)
    return e


def psdz_ok():
    p = SETTINGS["psdz_path"]
    return bool(p) and os.path.isdir(p)


def catalog():
    ok = psdz_ok()
    base = SETTINGS["psdz_path"] or ""
    roles = []
    for role, rid, label, help_, versions in ROLE_DEFS:
        files = []
        if ok:
            for ver, size in versions:
                fn = "swfl_%s.bin.%s" % (rid, ver)
                files.append({"file": fn, "version": ver, "size": size, "path": os.path.join(base, "swe", fn)})
        roles.append({"role": role, "id": rid, "label": label, "help": help_, "required": True, "files": files})
    return {"psdz_ok": ok, "series": SERIES, "roles": roles, "by_series": BY_SERIES,
            "languages": [{"code": c, "name": n} for c, n in LANGUAGES],
            "countries": [{"code": c, "name": n} for c, n in COUNTRIES],
            "displays": [{"code": c, "name": n} for c, n in DISPLAYS],
            "hmi_versions": [{"code": c, "name": n} for c, n in HMI_VERSIONS]}


VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def validate_coding(c):
    vin = (c or {}).get("vin")
    if vin is not None and not VIN_RE.match(str(vin).upper()):
        raise ApiError(400, "VIN inválido: use 17 caracteres (letras e números, sem I, O e Q).")


def validate_net(n):
    ports = []
    for k in ("ssh_port", "can_port", "gps_port"):
        if n and k in n:
            try:
                p = int(n[k])
            except Exception:
                raise ApiError(400, "Porta inválida: %s." % k)
            if not 1024 <= p <= 65535:
                raise ApiError(400, "Porta fora do intervalo 1024–65535: %s." % k)
            ports.append(p)
    if len(set(ports)) != len(ports):
        raise ApiError(400, "As portas SSH, CAN e GPS precisam ser diferentes.")


def a_state():
    return {"settings": dict(SETTINGS), "envs": list(ENVS.values()),
            "running": RUN["env"] if RUN["state"] in ("booting", "running") else None, "version": ENV_VERSION}


def a_settings(body):
    p = body.get("psdz_path")
    p = os.path.expanduser(p) if p else p
    SETTINGS["psdz_path"] = p or None
    if not p:
        return {"ok": True, "psdz_ok": False, "message": "Pasta psdzdata removida."}
    if not os.path.isdir(p):
        return {"ok": True, "psdz_ok": False, "message": "A pasta não existe ou não é um diretório: %s" % p}
    return {"ok": True, "psdz_ok": True, "message": "Pasta psdzdata válida: arquivos SWFL encontrados."}


def a_create(body):
    need(body, "name", "series", "chassis", "swfl")
    sw = body.get("swfl") or {}
    for r in ("os", "brand", "hmi"):
        if not sw.get(r):
            raise ApiError(400, "Arquivo SWFL ausente para o papel '%s'." % r)
    validate_coding(body.get("coding"))
    validate_net(body.get("net"))
    brand = body.get("brand") or "bmw"
    e = make_env(str(body["name"]).strip(), body["series"], body["chassis"], brand, sw, body.get("coding"), body.get("net"))
    return e


def a_update(e, body):
    if body.get("name"):
        e["name"] = str(body["name"]).strip()
    if "coding" in body:
        validate_coding(body["coding"])
        e["coding"].update(body["coding"])
    if "net" in body:
        validate_net(body["net"])
        e["net"].update(body["net"])
    return e


def a_build_start(e):
    if RUN["env"] == e["id"] and RUN["state"] in ("booting", "running"):
        raise ApiError(409, "Pare o ambiente antes de compilar.")
    if e["build"]["state"] == "building":
        raise ApiError(409, "O build já está em andamento.")
    e["build"].update(state="building", pct=0, step="Na fila", error=None)
    BUILDS[e["id"]] = {"t0": time.time(), "log": ["[build] Iniciando build de %s" % e["name"]], "emitted": 0}
    return {"ok": True}


def a_start(e):
    if RUN["state"] in ("booting", "running"):
        other = ENVS.get(RUN["env"], {}).get("name", RUN["env"])
        raise ApiError(409, "Já existe um ambiente em execução: %s." % other)
    if e["build"]["state"] != "ready":
        raise ApiError(409, "O ambiente ainda não foi compilado. Compile antes de iniciar.")
    for q in LOGS.values():
        q.clear()
    RUN.update(state="booting", env=e["id"], t0=time.time(), t_run=None, boot_step=BOOT_STEPS[0][1], boot_pct=0,
               error=None, last_input="", sel=0, pressed=False)
    CAN["due"].clear()
    log("console", "Iniciando %s (SSH %s, CAN %s, GPS %s)" % (e["name"], e["net"]["ssh_port"], e["net"]["can_port"], e["net"]["gps_port"]))
    return {"ok": True}


def a_stop(e):
    if RUN["env"] != e["id"] or RUN["state"] == "stopped":
        raise ApiError(409, "Este ambiente não está em execução.")
    RUN.update(state="stopped", env=None, t_run=None, boot_pct=0, boot_step="")
    CAN["scenario"] = None
    CAN["recording"] = False
    return {"ok": True}


def a_delete(e):
    if RUN["env"] == e["id"] and RUN["state"] != "stopped":
        raise ApiError(409, "Pare o ambiente antes de excluir.")
    ENVS.pop(e["id"], None)
    BUILDS.pop(e["id"], None)
    return {"ok": True}


def a_duplicate(e, body):
    name = str(body.get("name") or (e["name"] + " (cópia)")).strip()
    n = make_env(name, e["series"], e["chassis"], e["brand"], dict(e["swfl"]), dict(e["coding"]), dict(e["net"]),
                 build_state=e["build"]["state"] if e["build"]["state"] in ("ready", "none") else "none")
    return n


def a_run_status():
    st = RUN["state"]
    env = ENVS.get(RUN["env"] or "")
    up = (time.time() - RUN["t0"]) if RUN["t0"] and st != "stopped" else 0.0
    ports = {"ssh": env["net"]["ssh_port"], "can": env["net"]["can_port"], "gps": env["net"]["gps_port"]} if env else \
        {"ssh": 2222, "can": 29536, "gps": 29537}
    return {"state": st, "env": RUN["env"], "uptime_s": round(up, 1), "boot_step": RUN["boot_step"],
            "boot_pct": RUN["boot_pct"], "ports": ports, "frame_seq": frame_seq(),
            "fps": 4.0 if st == "running" else 0.0, "error": RUN["error"]}


def require_running():
    if RUN["state"] != "running":
        raise ApiError(409, "O emulador não está em execução (ou ainda está iniciando).")


KEYNAMES = {1: "MENU", 2: "BACK", 3: "OPTION", 4: "CD", 5: "RADIO", 6: "TEL", 7: "NAV", 8: "PRESS", 9: "N", 10: "S",
            11: "W", 12: "E", 13: "RIGHT", 14: "LEFT"}


def note_input(text):
    RUN["last_input"] = text
    RUN["last_input_t"] = time.time()
    log("guest", "input: " + text)


def a_key(b):
    require_running()
    code, val = int(b.get("code", 0)), int(b.get("val", 1))
    if code not in KEYNAMES:
        raise ApiError(400, "Código de tecla inválido: %s (use 1 a 14)." % code)
    RUN["pressed"] = bool(val) and code == 8
    note_input("%s %s" % (KEYNAMES[code], "DOWN" if val else "UP"))
    return {"ok": True}


def a_rotor(b):
    require_running()
    d = int(b.get("delta", 0))
    RUN["sel"] += d
    note_input("ROTOR %+d" % d)
    return {"ok": True}


def a_tilt(b):
    require_running()
    d = b.get("dir")
    if d not in ("up", "down", "left", "right"):
        raise ApiError(400, "Direção inválida (use up, down, left ou right).")
    RUN["sel"] += {"right": 1, "left": -1, "down": 3, "up": -3}[d]
    note_input("TILT " + d.upper())
    return {"ok": True}


def a_click(b):
    require_running()
    x, y = int(b.get("x", -1)), int(b.get("y", -1))
    if not (0 <= x < W and 0 <= y < H):
        raise ApiError(400, "Coordenadas fora do display (0–1439, 0–539).")
    if b.get("down"):
        RUN["click"] = (x, y)
        RUN["click_t"] = time.time()
    note_input("CLICK %s %d,%d" % ("DOWN" if b.get("down") else "UP", x, y))
    return {"ok": True}


def a_logs(q):
    name = (q.get("name") or ["console"])[0]
    tail = int((q.get("tail") or ["200"])[0])
    if name == "build":
        b = BUILDS.get(RUN["env"]) or (list(BUILDS.values())[-1] if BUILDS else None)
        lines = list(b["log"]) if b else []
    elif name in LOGS:
        lines = list(LOGS[name])
    else:
        raise ApiError(400, "Nome de log inválido: %s." % name)
    return {"lines": lines[-tail:]}


def a_can_signals():
    return {"groups": [{"name": n, "signals": [dict(s) for s in g]} for n, g in SIGNAL_GROUPS],
            "running": RUN["state"] == "running"}


def a_can_set(b):
    need(b, "name")
    s = SIGNALS.get(b["name"])
    if not s:
        raise ApiError(404, "Sinal desconhecido: %s." % b["name"])
    require_running()
    try:
        v = float(b.get("value"))
    except Exception:
        raise ApiError(400, "Valor inválido para %s." % s["name"])
    if v < s["min"] or v > s["max"]:
        raise ApiError(400, "Valor fora do intervalo (%s a %s) para %s." % (s["min"], s["max"], s["name"]))
    s["value"] = int(v) if float(v).is_integer() and s["step"] >= 1 else v
    can_frame(s["can_id"], encode_signal(s), "tx", s["name"])
    return {"ok": True}


def a_can_frame(b):
    need(b, "id", "data")
    require_running()
    try:
        cid = int(str(b["id"]), 16)
        data = str(b["data"]).replace(" ", "")
        int(data or "0", 16)
    except Exception:
        raise ApiError(400, "ID ou dados inválidos (use hexadecimal).")
    if len(data) % 2 or len(data) > 16:
        raise ApiError(400, "Os dados precisam ter de 1 a 8 bytes (número par de dígitos hex).")
    can_frame(cid, data, "tx", None)
    return {"ok": True}


def a_can_frames(q):
    since = int((q.get("since") or ["0"])[0])
    limit = int((q.get("limit") or ["200"])[0])
    fr = [f for f in CAN["frames"] if f["seq"] > since][:limit]
    return {"seq": CAN["seq"], "frames": fr}


def a_can_scenario(b):
    sid = b.get("id")
    if sid is None:
        CAN["scenario"] = None
        return {"ok": True}
    if sid not in [s["id"] for s in SCENARIOS]:
        raise ApiError(404, "Cenário desconhecido: %s." % sid)
    require_running()
    CAN["scenario"] = sid
    return {"ok": True}


def a_can_record(b):
    require_running()
    on = bool(b.get("on"))
    if on and not CAN["recording"]:
        CAN["rec_frames"] = []
        CAN["recording"] = True
    elif not on and CAN["recording"]:
        CAN["recording"] = False
        fn = "can_%s.log" % time.strftime("%Y%m%d_%H%M%S")
        CAN["recordings"].append({"file": fn, "frames": len(CAN["rec_frames"]),
                                  "size": len(CAN["rec_frames"]) * 36, "created": now_iso()})
    return {"ok": True}


def a_can_replay(b):
    need(b, "file")
    require_running()
    if b["file"] not in [r["file"] for r in CAN["recordings"]]:
        raise ApiError(404, "Gravação não encontrada: %s." % b["file"])
    CAN["replay"] = {"until": time.time() + 4, "loop": bool(b.get("loop"))}
    return {"ok": True}


def gps_state():
    g = GPS
    return {"mode": g["mode"], "fix": g["fix"], "lat": round(g["lat"], 6), "lon": round(g["lon"], 6),
            "alt": round(g["alt"], 1), "speed_kmh": round(g["speed_kmh"], 1), "heading": round(g["heading"], 1),
            "sats": g["sats"], "hdop": g["hdop"], "route": g["route"], "sync_can_speed": g["sync_can_speed"],
            "nmea_tail": list(g["nmea"])[-8:]}


def a_gps_set(b):
    g = GPS
    for k in ("lat", "lon", "alt", "speed_kmh", "heading", "hdop"):
        if k in b and b[k] is not None:
            try:
                g[k] = float(b[k])
            except Exception:
                raise ApiError(400, "Valor inválido: %s." % k)
    if "sats" in b:
        g["sats"] = int(b["sats"])
    for k in ("fix", "sync_can_speed"):
        if k in b:
            g[k] = bool(b[k])
    if "lat" in b or "lon" in b:
        g["center"] = (g["lat"], g["lon"])
        g["ang"] = 0.0
    return {"ok": True}


def a_gps_mode(b):
    m = b.get("mode")
    if m not in ("static", "route", "circle", "manual"):
        raise ApiError(400, "Modo inválido (static, route, circle ou manual).")
    g = GPS
    if m == "route" and not g["route_pts"]:
        raise ApiError(409, "Nenhuma rota carregada. Importe um arquivo GPX primeiro.")
    if m == "circle":
        if b.get("radius_m"):
            g["radius_m"] = float(b["radius_m"])
        # centro tal que o carro fique na posição atual sobre o círculo
        r = g["radius_m"]
        g["ang"] = 0.0
        g["center"] = (g["lat"], g["lon"] - r / (M_PER_DEG * math.cos(math.radians(g["lat"]))))
        if g["speed_kmh"] <= 0:
            g["speed_kmh"] = 40.0
    if m == "route":
        g["route_pos"] = 0.0
        if g["speed_kmh"] <= 0:
            g["speed_kmh"] = 50.0
    if m == "static":
        g["speed_kmh"] = 0.0
    g["mode"] = m
    return {"ok": True}


GPX_RE = re.compile(r"<(?:trkpt|rtept|wpt)\b[^>]*?\blat=[\"']([-0-9.eE+]+)[\"'][^>]*?\blon=[\"']([-0-9.eE+]+)[\"']", re.S)
GPX_RE2 = re.compile(r"<(?:trkpt|rtept|wpt)\b[^>]*?\blon=[\"']([-0-9.eE+]+)[\"'][^>]*?\blat=[\"']([-0-9.eE+]+)[\"']", re.S)


def a_gps_route(b):
    g = GPS
    if b.get("gpx"):
        pts = [[float(a), float(c)] for a, c in GPX_RE.findall(b["gpx"])]
        if not pts:
            pts = [[float(c), float(a)] for a, c in GPX_RE2.findall(b["gpx"])]
        if len(pts) < 2:
            raise ApiError(400, "O arquivo GPX não contém pontos suficientes (mínimo 2).")
        loop = True
    else:
        pts = [[float(p[0]), float(p[1])] for p in (b.get("points") or [])]
        if len(pts) < 2:
            raise ApiError(400, "Informe ao menos 2 pontos para a rota.")
        loop = bool(b.get("loop", True))
        if b.get("speed_kmh"):
            g["speed_kmh"] = float(b["speed_kmh"])
    g["route_pts"] = pts
    g["route_loop"] = loop
    g["route_pos"] = 0.0
    g["route"] = {"name": b.get("name") or "rota", "points": len(pts), "progress": 0.0,
                  "length_km": round(route_length_m(pts) / 1000.0, 2)}
    g["lat"], g["lon"] = pts[0]
    return {"ok": True}


def a_gps_jump(b):
    need(b, "lat", "lon")
    GPS["lat"], GPS["lon"] = float(b["lat"]), float(b["lon"])
    GPS["center"] = (GPS["lat"], GPS["lon"])
    GPS["ang"] = 0.0
    if GPS["mode"] == "circle":
        r = GPS["radius_m"]
        GPS["center"] = (GPS["lat"], GPS["lon"] - r / (M_PER_DEG * math.cos(math.radians(GPS["lat"]))))
    return {"ok": True}


def a_ssh():
    env = ENVS.get(RUN["env"] or "")
    port = env["net"]["ssh_port"] if env else 2222
    key = os.path.join(HERE, "..", "data", "id_ed25519")
    key = os.path.abspath(key)
    up = RUN["state"] == "running" and (time.time() - RUN["t_run"]) > 3
    return {"port": port, "host": "127.0.0.1", "user": "root", "key_path": key,
            "command": "ssh -i %s -p %d -o StrictHostKeyChecking=no root@127.0.0.1" % (key, port),
            "state": "up" if up else "down",
            "note": "Serviço SSH ativo no sistema convidado." if up else "O SSH só responde depois que o sistema terminar de iniciar."}


def a_fs_list(q):
    p = (q.get("path") or ["/"])[0] or "/"
    p = os.path.abspath(os.path.expanduser(p))
    if not os.path.isdir(p):
        raise ApiError(404, "Pasta não encontrada: %s" % p)
    entries = []
    try:
        for name in sorted(os.listdir(p), key=lambda s: s.lower()):
            fp = os.path.join(p, name)
            try:
                isd = os.path.isdir(fp)
                size = 0 if isd else os.path.getsize(fp)
            except OSError:
                continue
            entries.append({"name": name, "dir": isd, "size": size})
            if len(entries) >= 3000:
                break
    except PermissionError:
        raise ApiError(403, "Sem permissão para ler a pasta: %s" % p)
    parent = os.path.dirname(p) if p != "/" else None
    return {"path": p, "parent": parent, "entries": entries}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
CTYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
          ".json": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "IDEmuMock/0.1"

    def log_message(self, fmt, *args):
        if "-v" in sys.argv:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, body, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            v = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError(400, "Corpo da requisição não é um JSON válido.")
        return v if isinstance(v, dict) else {}

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/"):
            return self._api("GET", u)
        self._static(u.path)

    def do_POST(self):
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return self._json(404, {"error": "Não encontrado."})
        self._api("POST", u)

    def _static(self, path):
        path = unquote(path)
        if path in ("", "/"):
            path = "/index.html"
        if path == "/favicon.ico":
            path = "/favicon.svg"
        fp = os.path.normpath(os.path.join(HERE, path.lstrip("/")))
        if not fp.startswith(HERE + os.sep) or not os.path.isfile(fp):
            return self._json(404, {"error": "Arquivo não encontrado: %s" % path})
        with open(fp, "rb") as f:
            data = f.read()
        self._send(200, data, CTYPES.get(os.path.splitext(fp)[1].lower(), "application/octet-stream"))

    def _api(self, method, u):
        q = parse_qs(u.query)
        path = u.path
        try:
            body = self._body() if method == "POST" else {}
            with LOCK:
                if path == "/api/run/screen.png" and method == "GET":
                    if RUN["state"] != "running" or frame_seq() == 0:
                        raise ApiError(404, "Ainda não há imagem da tela.")
                    seq = frame_seq()
                    if _PNG_CACHE["seq"] != seq:
                        _PNG_CACHE["data"] = render_png(seq)
                        _PNG_CACHE["seq"] = seq
                    data = _PNG_CACHE["data"]
                    return self._send(200, data, "image/png", {"X-Frame-Seq": str(seq)})
                res = self._route(method, path, q, body)
            self._json(200, res)
        except ApiError as e:
            self._json(e.status, {"error": e.msg})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
            self._json(500, {"error": "Erro interno do mock: %s" % e})

    def _route(self, m, p, q, b):
        if m == "GET":
            if p == "/api/state":
                return a_state()
            if p == "/api/catalog":
                return catalog()
            mm = re.match(r"^/api/env/([^/]+)$", p)
            if mm:
                return get_env(mm.group(1))
            mm = re.match(r"^/api/env/([^/]+)/build$", p)
            if mm:
                e = get_env(mm.group(1))
                bl = BUILDS.get(e["id"], {"log": []})
                return {"state": e["build"]["state"], "pct": e["build"]["pct"], "step": e["build"]["step"],
                        "log": bl["log"][-60:], "error": e["build"]["error"]}
            if p == "/api/run/status":
                return a_run_status()
            if p == "/api/logs":
                return a_logs(q)
            if p == "/api/can/signals":
                return a_can_signals()
            if p == "/api/can/frames":
                return a_can_frames(q)
            if p == "/api/can/scenarios":
                return {"scenarios": SCENARIOS, "active": CAN["scenario"]}
            if p == "/api/can/recordings":
                return {"recordings": CAN["recordings"], "recording": CAN["recording"]}
            if p == "/api/gps/state":
                return gps_state()
            if p == "/api/ssh/info":
                return a_ssh()
            if p == "/api/fs/list":
                return a_fs_list(q)
        else:
            if p == "/api/settings":
                return a_settings(b)
            if p == "/api/env/create":
                return a_create(b)
            mm = re.match(r"^/api/env/([^/]+)/(update|build|start|stop|delete|duplicate)$", p)
            if mm:
                e = get_env(mm.group(1))
                act = mm.group(2)
                return {"update": lambda: a_update(e, b), "build": lambda: a_build_start(e),
                        "start": lambda: a_start(e), "stop": lambda: a_stop(e), "delete": lambda: a_delete(e),
                        "duplicate": lambda: a_duplicate(e, b)}[act]()
            table = {"/api/input/key": a_key, "/api/input/rotor": a_rotor, "/api/input/tilt": a_tilt,
                     "/api/input/click": a_click, "/api/can/set": a_can_set, "/api/can/frame": a_can_frame,
                     "/api/can/scenario": a_can_scenario, "/api/can/record": a_can_record,
                     "/api/can/replay": a_can_replay, "/api/gps/set": a_gps_set, "/api/gps/mode": a_gps_mode,
                     "/api/gps/route": a_gps_route, "/api/gps/jump": a_gps_jump}
            if p in table:
                return table[p](b)
        raise ApiError(404, "Rota não encontrada: %s %s" % (m, p))


def main():
    ap = argparse.ArgumentParser(description="Mock do back-end do IDEmu")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--psdz", default=None, help="pré-configura a pasta psdzdata")
    ap.add_argument("--empty", action="store_true", help="não cria o ambiente de exemplo")
    ap.add_argument("-v", action="store_true", help="mostra o log de acessos")
    args = ap.parse_args()
    SETTINGS["psdz_path"] = args.psdz
    if not args.empty:
        make_env("F30 BMW", "F020", "F30", "bmw",
                 {"os": "/psdzdata/swe/swfl_0000271a.bin.007_051_002",
                  "brand": "/psdzdata/swe/swfl_00002719.bin.007_051_001",
                  "hmi": "/psdzdata/swe/swfl_00002720.bin.007_051_003"}, {}, {}, build_state="ready")
    threading.Thread(target=ticker, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print("IDEmu mock em http://%s:%d  (Ctrl+C para sair)" % (args.host, args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

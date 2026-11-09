"""Painel de instrumentos (Kombi) e HUD virtuais do iDrive 5/6.

No carro, o cluster e o HUD desenham o que vem do CAN do próprio carro (velocidade, rotação, câmbio, combustível, luzes, alertas). A head unit só
manda a eles o conteúdo que ela gera (mensagens de check control, lista de mídia, guiamento da navegação). Aqui:

  * o estado vem do CAN virtual (`idemu/canbus.py`), do GPS virtual (`idemu/gps.py`) e das mensagens que o HMI manda por MOST ao Kombi (FBlock 0xE0)
    e ao HUD (0xE1), guardadas por `MostBridge.seen` (`idemu/most.py`);
  * a próxima curva da rota é calculada aqui, pela geometria da rota do GPS virtual. Não é o guiamento do HMI: o iDrive emulado não tem motor de
    navegação, então o HMI não manda manobras ao cluster.

`snapshot()` é o formato de GET /api/cluster; a tela é `IDE.tabDefs.cluster` em idemu/web/tabs.js."""
import json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNALS = ('vehicle_speed', 'engine_rpm', 'accelerator_pos', 'coolant_temp', 'fuel_level', 'fuel_level_2', 'fuel_consumption', 'odometer', 'terminal_state',
           'key_present', 'gear_position', 'driving_mode', 'headlight_low', 'headlight_high', 'turn_left', 'turn_right', 'hazard', 'parking_brake',
           'door_driver', 'door_passenger', 'door_rear_driver', 'door_rear_passenger', 'trunk_open', 'hood_open', 'seatbelt_driver', 'seatbelt_passenger',
           'tire_pressure_fl', 'tire_pressure_fr', 'tire_pressure_rl', 'tire_pressure_rr', 'outside_temp')
TANK_L = 62.0                        # o sinal fuel_level vai de 0 a 62 L (idemu/data/can_signals.json)
KOMBI, HUD = 0xE0, 0xE1              # FBlocks MOST (idemu/most.py)
TURN_MIN_DEG, LOOKAHEAD_M, STEP_M = 35.0, 2000.0, 20.0

_NAMES = None
def _names():
    """(fblock, função) -> (grupo, nome da propriedade), do mapa extraído do HmiMain3D (idemu/data/hmi_most_map.json)."""
    global _NAMES
    if _NAMES is None:
        _NAMES = {}
        try:
            with open(os.path.join(HERE, 'data', 'hmi_most_map.json')) as f: m = json.load(f)
            group = {}
            for d in m['devices']:
                if d.get('inst') is not None: group.setdefault(d['fblock'], d['group'])
            for fb, g in group.items():
                for fkt, name in (m['functions'].get(g) or {}).items(): _NAMES[(fb, int(fkt))] = (g, name)
        except Exception: pass
    return _NAMES

def _angle(a, b):
    """Diferença de rumo b - a, em graus, entre -180 e 180."""
    return (b - a + 540.0) % 360.0 - 180.0

def next_turn(route, dist_m):
    """Próxima curva da rota a partir de `dist_m`: {'dist_m', 'angle', 'dir'} ou None. `dir`: left, right, uturn.
    Compara o rumo atual com o rumo 25 m depois de cada ponto de amostragem (a cada 20 m, até 2 km); uma curva é uma mudança de pelo menos 35 graus."""
    if route is None or route.length_m - dist_m < 40: return None
    head = route.at(dist_m)[2]
    s = dist_m + STEP_M
    end = min(route.length_m, dist_m + LOOKAHEAD_M)
    while s < end:
        d = _angle(head, route.at(min(route.length_m, s + 25.0))[2])
        if abs(d) >= TURN_MIN_DEG:
            # acompanha a curva até o fim para medir o ângulo total (curvas feitas de vários pontos)
            tot, last, t = d, route.at(min(route.length_m, s + 25.0))[2], s + 25.0
            while t < min(route.length_m, s + 120.0):
                t += STEP_M; b = route.at(min(route.length_m, t))[2]
                step = _angle(last, b)
                if abs(step) < 4.0: break
                tot += step; last = b
            return {'dist_m': int(round(s - dist_m)), 'angle': int(round(tot)), 'dir': 'uturn' if abs(tot) > 150 else ('right' if tot > 0 else 'left')}
        s += STEP_M
    return None

def hu_messages(seen, now=None):
    """O que o HMI mandou ao Kombi e ao HUD (Set/Get/SetGet): lista de {dev, fkt, name, op, n, age, hex}, mais recentes primeiro."""
    now = time.time() if now is None else now
    out = []
    for (fb, inst, fkt), e in (seen or {}).items():
        if fb not in (KOMBI, HUD): continue
        g, name = _names().get((fb, fkt), ('Kombi' if fb == KOMBI else 'HUD', '0x%03x' % fkt))
        out.append({'dev': g, 'inst': inst, 'fkt': fkt, 'name': name, 'op': e['op'], 'n': e['n'], 'age': round(now - e['t'], 1), 'hex': bytes(e['data']).hex()})
    out.sort(key=lambda x: x['age'])
    return out

def warnings(v):
    """Luzes e alertas do cluster, calculados dos sinais. Cada item é (id, severidade): red, amber, info."""
    w = []
    moving = v.get('vehicle_speed', 0) > 3
    if not v.get('seatbelt_driver', 1) and (moving or v.get('terminal_state', 0) >= 69): w.append(('belt_driver', 'red'))
    if not v.get('seatbelt_passenger', 1) and moving: w.append(('belt_passenger', 'red'))
    if v.get('parking_brake'): w.append(('parking_brake', 'red'))
    if any(v.get(k) for k in ('door_driver', 'door_passenger', 'door_rear_driver', 'door_rear_passenger')): w.append(('door', 'red'))
    if v.get('trunk_open'): w.append(('trunk', 'red'))
    if v.get('hood_open'): w.append(('hood', 'red'))
    if v.get('coolant_temp', 90) >= 115: w.append(('coolant_hot', 'red'))
    elif v.get('coolant_temp', 90) < 40 and v.get('terminal_state', 0) >= 69: w.append(('coolant_cold', 'info'))
    if v.get('fuel_level', TANK_L) <= 7.0: w.append(('fuel_low', 'amber'))
    if min(v.get('tire_pressure_%s' % p, 2.4) for p in ('fl', 'fr', 'rl', 'rr')) < 1.8: w.append(('tire_low', 'amber'))
    if v.get('headlight_high'): w.append(('high_beam', 'info'))
    elif v.get('headlight_low'): w.append(('low_beam', 'info'))
    return w

def snapshot(can, gps, bridge=None):
    """Estado do cluster e do HUD: sinais do CAN, posição do GPS, próxima curva e mensagens do HMI para o Kombi/HUD."""
    v = {}
    for n in SIGNALS:
        try: v[n] = float(can.get_signal(n))
        except Exception: pass
    g = None
    if gps is not None:
        try:
            st = gps.state(); g = {'fix': st['fix'], 'speed_kmh': st['speed_kmh'], 'heading': st['heading'], 'mode': st['mode'], 'route': st.get('route')}
            route = getattr(gps, 'route', None)
            if route is not None:
                done = min(route.length_m, getattr(gps, 'route_dist', 0.0))
                g['remaining_m'] = int(round(route.length_m - done)); g['turn'] = next_turn(route, done)
        except Exception: g = None
    fuel = v.get('fuel_level', 0.0)
    return {'signals': v, 'gps': g, 'fuel_pct': round(max(0.0, min(1.0, fuel / TANK_L)) * 100.0, 1), 'range_km': int(max(0.0, fuel) / max(4.0, v.get('fuel_consumption', 7.5) or 7.5) * 100.0),
            'warnings': [{'id': i, 'level': l} for i, l in warnings(v)],
            'hu': hu_messages(getattr(bridge, 'seen', None)), 'hu_note': 'mensagens que o HMI enviou ao Kombi (0xE0) e ao HUD (0xE1) por MOST'}

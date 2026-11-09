"""Mapa do iDrive desenhado no host (src/glhost/map.c): posição do GPS virtual, zoom e blocos de mapa.

O HMI só precisa de uma imagem na superfície de mapa; quem entrega aqui é o glhost. Este serviço dá ao glhost o que ele não tem:
  * a posição e o zoom ("M p ...", "M z ..." pelo input.sock);
  * os blocos pedidos por <ctl>/map.sock: procura no cache e, se houver uma fonte ligada, baixa para o cache e avisa ("M t z x y").
Por padrão não há fonte de rede (`map_source` = "off"): nada sai desta máquina e só o que já estiver no cache aparece. Ligar a fonte manda a região do GPS
virtual ao servidor de blocos. Não é o motor de navegação da BMW: sem rotas, sem busca de endereço, sem dados NDS."""
import os, queue, socket, threading, time, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get('IDEMU_MAPCACHE') or os.path.join(os.environ.get('IDEMU_STATE_DIR') or HERE, 'mapcache')
SOURCES = {'osm': ('https://tile.openstreetmap.org/{z}/{x}/{y}.png', '(c) OpenStreetMap contributors')}
USER_AGENT = 'IDEmu/0.1 (BMW iDrive emulator, map view)'
RETRY_S = 60.0


class MapService:
    def __init__(self, ctl, gps, settings=None, *, input_endpoint=None):
        self.ctl, self.gps = ctl, gps
        s = settings or {}
        self.source = s.get('map_source', 'off')
        self.zoom = float(s.get('map_zoom', 16))
        self.headup = bool(s.get('map_headup', False))
        self.night = bool(s.get('map_night', False))
        self.stats = {'requested': 0, 'downloaded': 0, 'failed': 0, 'cached': 0}
        self.last_error = None
        self._stop = False
        self._q = queue.LifoQueue(256)
        self._pend, self._failed = set(), {}
        self._lock = threading.Lock()
        self.input_endpoint = input_endpoint or os.path.join(ctl, 'input.sock')
        self._family = socket.AF_INET if isinstance(self.input_endpoint, tuple) else socket.AF_UNIX
        self._out = socket.socket(self._family, socket.SOCK_DGRAM)
        self._in = None
        self._last_pos = None

    # ---- comandos para o glhost
    def _send(self, line):
        for _ in range(5):
            try:
                self._out.sendto(line.encode(), self.input_endpoint)
                return
            except BlockingIOError:
                time.sleep(0.02)
            except OSError as e:
                if e.errno != 55:          # ENOBUFS: fila do datagrama cheia, espera um pouco
                    return
                time.sleep(0.02)

    def _source(self):
        """(url, atribuição) da fonte atual; `source` também pode ser um modelo próprio com {z} {x} {y}."""
        if self.source in SOURCES:
            return SOURCES[self.source]
        if '{z}' in self.source and self.source.startswith(('http://', 'https://')):
            return (self.source, 'Map data: ' + self.source.split('/')[2])
        return (None, '')

    def push_state(self):
        """Reenvia tudo ao glhost (no início e depois de um boot rápido, que recria o glhost)."""
        self._last_pos = None
        self._send('M z %.2f' % self.zoom)
        self._send('M v %d' % (1 if self.headup else 0))
        self._send('M n %d' % (1 if self.night else 0))
        url, attr = self._source()
        self._send('M a ' + (attr if url else 'Map data off: enable it in IDEmu (Map tab)'))
        self._push_pos()

    def _push_pos(self):
        g = self.gps
        if g is None:
            return
        try:
            st = g.state()
            p = (round(float(st['lat']), 7), round(float(st['lon']), 7), round(float(st.get('heading') or 0), 1))
        except Exception:
            return
        if p != self._last_pos:
            self._last_pos = p
            self._send('M p %.7f %.7f %.1f' % p)

    def set(self, zoom=None, headup=None, night=None, source=None):
        if zoom is not None:
            self.zoom = max(2.0, min(19.0, float(zoom)))
        if headup is not None:
            self.headup = bool(headup)
        if night is not None:
            self.night = bool(night)
        if source is not None:
            self.source = str(source) or 'off'
            with self._lock:
                self._failed.clear()
            self._send('M r')
        self.push_state()

    def state(self):
        url, attr = self._source()
        return {'source': self.source, 'online': bool(url), 'zoom': self.zoom, 'headup': self.headup, 'night': self.night, 'attribution': attr,
                'sources': sorted(SOURCES), 'cache': CACHE, 'stats': dict(self.stats), 'error': self.last_error}

    # ---- blocos
    @staticmethod
    def tile_path(z, x, y):
        return os.path.join(CACHE, str(z), str(x), '%d.png' % y)

    def _request(self, z, x, y):
        self.stats['requested'] += 1
        if os.path.getsize(self.tile_path(z, x, y)) if os.path.exists(self.tile_path(z, x, y)) else 0:
            self.stats['cached'] += 1
            self._send('M t %d %d %d' % (z, x, y))
            return
        url, _ = self._source()
        if not url:
            return
        k = (z, x, y)
        now = time.time()
        with self._lock:
            if k in self._pend or now - self._failed.get(k, 0) < RETRY_S:
                return
            self._pend.add(k)
        try:
            self._q.put_nowait(k)
        except queue.Full:
            with self._lock:
                self._pend.discard(k)

    def _fetch(self, z, x, y):
        url, _ = self._source()
        if not url:
            return False
        req = urllib.request.Request(url.format(z=z, x=x, y=y), headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        if len(data) < 8:
            raise ValueError('bloco vazio')
        p = self.tile_path(z, x, y)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp%d' % threading.get_ident()
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, p)
        return True

    def _worker(self):
        while not self._stop:
            try:
                k = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if self._fetch(*k):
                    self.stats['downloaded'] += 1
                    self.last_error = None
                    self._send('M t %d %d %d' % k)
            except Exception as e:                # sem rede, 403, 429...: tenta de novo depois, sem insistir
                self.stats['failed'] += 1
                self.last_error = str(e)[:160]
                with self._lock:
                    self._failed[k] = time.time()
            finally:
                with self._lock:
                    self._pend.discard(k)

    def _listener(self):
        while not self._stop:
            try:
                b = self._in.recv(64)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                z, x, y = (int(v) for v in b.split())
            except ValueError:
                continue
            self._request(z, x, y)

    def _position_loop(self):
        n = 0
        while not self._stop:
            self._push_pos()
            n += 1
            if n % 25 == 1:                   # o glhost pode ter sido recriado (fallback de boot): refresca o estado de vez em quando
                self.push_state()
            time.sleep(0.2)

    def start(self):
        os.makedirs(CACHE, exist_ok=True)
        if self._family == socket.AF_INET:
            path = ('127.0.0.1', 0)
        else:
            path = os.path.join(self.ctl, 'map.sock')
            try:
                os.unlink(path)
            except OSError:
                pass
        self._in = socket.socket(self._family, socket.SOCK_DGRAM)
        self._in.bind(path)
        if self._family == socket.AF_INET:
            with open(os.path.join(self.ctl, 'map.port'), 'w', encoding='ascii') as f:
                print(self._in.getsockname()[1], file=f)
        self._in.settimeout(0.5)
        for fn, name in ((self._listener, 'map-req'), (self._position_loop, 'map-pos'), (self._worker, 'map-net1'), (self._worker, 'map-net2')):
            threading.Thread(target=fn, daemon=True, name=name).start()
        self.push_state()

    def stop(self):
        self._stop = True
        try:
            self._in and self._in.close()
        except OSError:
            pass
        self._out.close()


# ---- zoom do HMI (FBlock MapControl 0xDA): valores que aparecem na escala da tela. id | unidade | metros
SCALES_M = (50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000)
ZOOMS = (18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 5, 4)

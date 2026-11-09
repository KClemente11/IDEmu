"""Celular conectado ao iDrive pela rede Wi-Fi (sem Bluetooth, CarPlay ou Android Auto: o hardware emulado não tem rádio nem USB host).

O celular abre uma página servida pelo Mac e passa a ser:
  * a tela e o controle da head unit (imagem ao vivo, toque na tela, rotor, botões);
  * o GPS do carro: a posição do celular (navigator.geolocation) vira a posição do GPS virtual, que o HMI lê.

Segurança: o servidor local do IDEmu continua só em 127.0.0.1. O celular entra por um segundo servidor, ligado à rede local só enquanto você
deixar ligado, com PIN de 6 dígitos (bloqueio após erros) e uma lista fixa de rotas: nada de SSH, arquivos, coding ou logs.
A porta HTTPS usa um certificado autoassinado, que o celular precisa aceitar uma vez: sem HTTPS o navegador do celular não libera a localização."""
import hmac, http.cookies, json, os, secrets, socket, ssl, subprocess, tempfile, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, 'idemu', 'web', 'phone.html')
CERT_DIR = os.path.join(os.environ.get('IDEMU_STATE_DIR') or os.path.join(ROOT, 'idemu', 'data'), 'phone')
HTTP_PORT, HTTPS_PORT = 8766, 8767
COOKIE = 'idemu_phone'
MAX_FAILS, LOCK_S = 5, 60
MAX_BODY = 4096


def lan_ips():
    """Endereços IPv4 do Mac nas redes locais (o primeiro é o da rota padrão)."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('10.255.255.255', 1)); out.append(s.getsockname()[0]); s.close()
    except OSError: pass
    try:
        for a in socket.gethostbyname_ex(socket.gethostname())[2]:
            if a not in out and not a.startswith('127.'): out.append(a)
    except OSError: pass
    return [a for a in out if a and not a.startswith('127.') and not a.startswith('169.254.')]


def make_cert(ips):
    """Certificado autoassinado (RSA 2048, 1 ano) com os IPs da rede no SubjectAltName. Refeito quando os IPs mudam."""
    os.makedirs(CERT_DIR, exist_ok=True)
    crt, key, meta = (os.path.join(CERT_DIR, n) for n in ('cert.pem', 'key.pem', 'ips.json'))
    try:
        if os.path.isfile(crt) and os.path.isfile(key) and json.load(open(meta)) == sorted(ips): return crt, key
    except (OSError, ValueError): pass
    san = ','.join(['DNS:localhost', 'IP:127.0.0.1'] + ['IP:' + a for a in ips])
    cfg = ('[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n[dn]\nCN=IDEmu\n'
           '[v3]\nsubjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' % san)
    with tempfile.NamedTemporaryFile('w', suffix='.cnf', delete=False) as f: f.write(cfg); cp = f.name
    try:
        r = subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '365', '-keyout', key, '-out', crt, '-config', cp],
                           capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(cp)
    if r.returncode != 0: raise RuntimeError('não consegui criar o certificado HTTPS: ' + (r.stderr or '').strip()[-200:])
    os.chmod(key, 0o600); json.dump(sorted(ips), open(meta, 'w'))
    return crt, key


class PhoneLink(object):
    """Liga e desliga o servidor do celular. `app` é o `server.APP` (need_rt, need_gps)."""
    def __init__(self, app, ports=(HTTP_PORT, HTTPS_PORT)):
        self.app = app; self.lock = threading.Lock(); self.http_port, self.https_port = ports
        self.pin = ''; self.servers = []; self.sessions = {}; self.fails = {}; self.last_seen = 0.0; self.clients = {}
        self.running = False; self.https_ok = False; self.error = ''; self.gps_fixes = 0; self.last_gps = None

    # ---------- ciclo de vida ----------
    def start(self, pin=None):
        with self.lock:
            if self.running: return self.state()
            self.pin = pin or '%06d' % secrets.randbelow(1000000); self.sessions = {}; self.fails = {}; self.clients = {}
            self.error = ''; self.gps_fixes = 0; self.last_gps = None
            handler = self._handler()
            srv = ThreadingHTTPServer(('0.0.0.0', self.http_port), handler); srv.daemon_threads = True; self.http_port = srv.server_address[1]
            self.servers = [srv]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.https_ok = False
            try:
                crt, key = make_cert(lan_ips())
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(crt, key)
                hs = ThreadingHTTPServer(('0.0.0.0', self.https_port), handler); hs.daemon_threads = True; self.https_port = hs.server_address[1]
                hs.socket = ctx.wrap_socket(hs.socket, server_side=True)
                self.servers.append(hs); threading.Thread(target=hs.serve_forever, daemon=True).start(); self.https_ok = True
            except (OSError, RuntimeError, ssl.SSLError) as e:
                self.error = 'HTTPS indisponível (%s): a localização do celular não funciona, o controle sim' % e
            self.running = True
        return self.state()

    def stop(self):
        with self.lock:
            for s in self.servers:
                try: s.shutdown(); s.server_close()
                except OSError: pass
            self.servers = []; self.running = False; self.sessions = {}
        return self.state()

    def state(self):
        ips = lan_ips() if self.running else []
        now = time.time()
        return {'running': self.running, 'pin': self.pin if self.running else '', 'ips': ips, 'http_port': self.http_port, 'https_port': self.https_port,
                'https': self.https_ok, 'error': self.error,
                'urls': ['http://%s:%d/' % (a, self.http_port) for a in ips], 'urls_https': ['https://%s:%d/' % (a, self.https_port) for a in ips] if self.https_ok else [],
                'phones': sorted(ip for ip, t in self.clients.items() if now - t < 15), 'gps_fixes': self.gps_fixes, 'gps': self.last_gps}

    # ---------- autenticação ----------
    def _locked(self, ip):
        n, t = self.fails.get(ip, (0, 0))
        return n >= MAX_FAILS and time.time() - t < LOCK_S

    def login(self, ip, pin):
        if self._locked(ip): return None
        if hmac.compare_digest(str(pin or '').strip().encode(), self.pin.encode()):
            self.fails.pop(ip, None); tok = secrets.token_urlsafe(24); self.sessions[tok] = time.time(); return tok
        n, _ = self.fails.get(ip, (0, 0)); self.fails[ip] = (n + 1, time.time()); return None

    def authed(self, cookie_header):
        try: c = http.cookies.SimpleCookie(cookie_header or '')
        except http.cookies.CookieError: return False
        m = c.get(COOKIE)
        return bool(m and m.value in self.sessions)

    # ---------- ações ----------
    def do_input(self, d):
        rt = self.app.need_rt(); t = d.get('t')
        if t == 'rotor': rt.rotor(max(-20, min(20, int(d.get('delta', 0)))))
        elif t == 'key': rt.key(int(d['code']), 1 if int(d.get('val', 1)) else 0)
        elif t == 'tilt':
            code = {'up': 9, 'down': 10, 'left': 11, 'right': 12}.get(d.get('dir'))
            if not code: raise ValueError('direção inválida')
            rt.key(code, 1); time.sleep(0.08); rt.key(code, 0)
        elif t == 'touch':
            if not hasattr(rt, 'touch'): raise ValueError('esta head unit não aceita toque')
            w, h = self._disp(rt)
            x = max(0, min(w - 1, int(float(d['x']) * w))); y = max(0, min(h - 1, int(float(d['y']) * h)))
            rt.touch(x, y, bool(d.get('down')), bool(d.get('move')))
        else: raise ValueError('comando desconhecido')

    @staticmethod
    def _disp(rt):
        d = getattr(rt, 'disp', None)
        if d: return d
        try: w, h = (int(v) for v in rt.env['coding']['display'].split('_')[-1].split('x')); return w, h
        except (KeyError, ValueError, AttributeError): return 1440, 540

    def do_gps(self, d):
        g = self.app.need_gps()
        lat, lon = float(d['lat']), float(d['lon'])
        kw = {'lat': lat, 'lon': lon}
        if d.get('speed') is not None and float(d['speed']) >= 0: kw['speed_kmh'] = float(d['speed']) * 3.6        # m/s -> km/h
        if d.get('heading') is not None and float(d['heading']) == float(d['heading']): kw['heading'] = float(d['heading'])
        if d.get('alt') is not None: kw['alt'] = float(d['alt'])
        acc = d.get('accuracy')
        if acc is not None and float(acc) > 0: kw['hdop'] = round(max(0.8, min(20.0, float(acc) / 5.0)), 1)
        if g.mode != 'manual': g.set_mode('manual')
        g.set(fix=True, **kw)
        self.gps_fixes += 1; self.last_gps = {'lat': round(lat, 6), 'lon': round(lon, 6), 'speed_kmh': round(kw.get('speed_kmh', 0.0), 1), 't': time.time()}

    # ---------- HTTP ----------
    def _handler(self):
        link = self

        class H(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            server_version = 'IDEmuPhone'
            def log_message(self, *a): pass
            def _ip(self): return self.client_address[0]
            def _send(self, code, body=b'', ctype='application/json', extra=None):
                if isinstance(body, (dict, list)): body = json.dumps(body).encode()
                elif isinstance(body, str): body = body.encode()
                self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff'); self.send_header('Referrer-Policy', 'no-referrer')
                for k, v in (extra or {}).items(): self.send_header(k, v)
                self.end_headers(); self.wfile.write(body)
            def _body(self):
                n = int(self.headers.get('Content-Length') or 0)
                if n > MAX_BODY: raise ValueError('corpo grande demais')
                return json.loads(self.rfile.read(n) or b'{}') if n else {}
            def _cookie(self, tok): return {'Set-Cookie': '%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200' % (COOKIE, tok)}
            def do_GET(self):
                link.clients[self._ip()] = time.time()
                path, _, qs = self.path.partition('?'); q = dict(p.split('=', 1) for p in qs.split('&') if '=' in p)
                if path == '/':
                    if not link.authed(self.headers.get('Cookie')):
                        return self._send(401, open(PAGE, encoding='utf-8').read().replace('/*AUTH*/false', 'true'), 'text/html; charset=utf-8')
                    return self._send(200, open(PAGE, encoding='utf-8').read(), 'text/html; charset=utf-8')
                if not link.authed(self.headers.get('Cookie')): return self._send(401, {'error': 'PIN necessário'})
                try:
                    if path == '/p/state':
                        rt = link.app.rt
                        if not rt: return self._send(200, {'state': 'stopped'})
                        d = link._disp(rt); g = None
                        try: g = link.app.need_gps().state()
                        except Exception: pass
                        return self._send(200, {'state': rt.state, 'env': getattr(rt, 'id', ''), 'w': d[0], 'h': d[1], 'touch': hasattr(rt, 'touch'),
                                                'gps': {k: g[k] for k in ('lat', 'lon', 'speed_kmh', 'heading')} if g else None})
                    if path == '/p/screen.png':
                        rt = link.app.need_rt(); since = int(q.get('since', -1)); end = time.time() + 2.0
                        png, seq = rt.screen_png()
                        while seq == since and time.time() < end and rt.state in ('booting', 'running'):
                            time.sleep(0.05); png, seq = rt.screen_png()
                        if not png or seq == since: return self._send(204, b'', 'image/png', {'X-Frame-Seq': str(seq)})
                        return self._send(200, png, 'image/png', {'X-Frame-Seq': str(seq)})
                except Exception as e:
                    return self._send(409, {'error': str(e)})
                return self._send(404, {'error': 'não encontrado'})
            def do_POST(self):
                link.clients[self._ip()] = time.time()
                path = self.path.partition('?')[0]
                try: d = self._body()
                except (ValueError, json.JSONDecodeError) as e: return self._send(400, {'error': str(e)})
                if path == '/login':
                    if link._locked(self._ip()): return self._send(429, {'error': 'muitas tentativas: espere um minuto'})
                    tok = link.login(self._ip(), d.get('pin'))
                    if not tok: return self._send(403, {'error': 'PIN incorreto'})
                    return self._send(200, {'ok': True}, extra=self._cookie(tok))
                if not link.authed(self.headers.get('Cookie')): return self._send(401, {'error': 'PIN necessário'})
                try:
                    if path == '/p/input': link.do_input(d); return self._send(200, {'ok': True})
                    if path == '/p/gps': link.do_gps(d); return self._send(200, {'ok': True})
                except Exception as e:
                    return self._send(400, {'error': str(e)})
                return self._send(404, {'error': 'não encontrado'})
        return H

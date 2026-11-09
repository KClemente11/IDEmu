"""Celular conectado ao iDrive (idemu/phone.py): PIN, bloqueio, lista fixa de rotas, entrada e GPS. Usa portas efêmeras e um runtime falso."""
import http.client, json, os, ssl, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import phone, gps


class FakeRt(object):
    state = 'running'; id = 'teste'; disp = (1440, 540)
    def __init__(self): self.calls = []; self.seq = 1
    def rotor(self, d): self.calls.append(('rotor', d))
    def key(self, c, v): self.calls.append(('key', c, v))
    def touch(self, x, y, down, move=False): self.calls.append(('touch', x, y, down, move))
    def screen_png(self): return b'\x89PNG-fake', self.seq


class FakeApp(object):
    def __init__(self): self.rt = FakeRt(); self.g = gps.GpsSim()
    def need_rt(self): return self.rt
    def need_gps(self): return self.g


class Client(object):
    def __init__(self, port, https=False):
        self.port, self.https, self.cookie = port, https, None
    def req(self, method, path, body=None, raw=None):
        c = (http.client.HTTPSConnection('127.0.0.1', self.port, context=ssl._create_unverified_context(), timeout=10) if self.https
             else http.client.HTTPConnection('127.0.0.1', self.port, timeout=10))
        h = {'Content-Type': 'application/json'}
        if self.cookie: h['Cookie'] = self.cookie
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse(); b = r.read(); sc = r.getheader('Set-Cookie'); c.close()
        if sc: self.cookie = sc.split(';')[0]
        return r.status, b


class PhoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); phone.CERT_DIR = cls.tmp.name
        cls.app = FakeApp(); cls.link = phone.PhoneLink(cls.app, ports=(0, 0)); cls.st = cls.link.start(pin='123456')
    @classmethod
    def tearDownClass(cls): cls.link.stop(); cls.tmp.cleanup()
    def setUp(self):
        self.app.rt.calls.clear(); self.link.fails.clear(); self.c = Client(self.link.http_port)

    def login(self, c=None):
        c = c or self.c; sc, _ = c.req('POST', '/login', {'pin': '123456'}); self.assertEqual(sc, 200); return c

    def test_state_and_pin(self):
        self.assertTrue(self.st['running']); self.assertEqual(self.st['pin'], '123456'); self.assertTrue(self.st['https'])
        self.assertEqual(self.c.req('GET', '/p/state')[0], 401)
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'rotor', 'delta': 1})[0], 401)
        self.assertEqual(self.c.req('POST', '/login', {'pin': '000000'})[0], 403)
        self.login()
        sc, b = self.c.req('GET', '/p/state'); d = json.loads(b)
        self.assertEqual((sc, d['state'], d['w'], d['h'], d['touch']), (200, 'running', 1440, 540, True))

    def test_lockout_after_errors(self):
        for _ in range(phone.MAX_FAILS): self.assertEqual(self.c.req('POST', '/login', {'pin': '999999'})[0], 403)
        self.assertEqual(self.c.req('POST', '/login', {'pin': '123456'})[0], 429)      # certo, mas bloqueado
        self.link.fails.clear(); self.login()

    def test_login_page_and_app_page(self):
        sc, b = self.c.req('GET', '/'); self.assertEqual(sc, 401); self.assertTrue(b'const NEEDPIN = true' in b)
        self.login(); sc, b = self.c.req('GET', '/'); self.assertEqual(sc, 200); self.assertTrue(b'const NEEDPIN = /*AUTH*/false' in b)

    def test_only_whitelisted_routes(self):
        self.login()
        for p in ('/api/ssh/info', '/api/env', '/api/logs', '/../etc/passwd', '/p/arquivo', '/idemu/server.py'):
            self.assertEqual(self.c.req('GET', p)[0], 404, p)
        self.assertEqual(self.c.req('POST', '/api/input/key', {'code': 1})[0], 404)

    def test_input(self):
        self.login()
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'rotor', 'delta': 3})[0], 200)
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'rotor', 'delta': 999})[0], 200)      # limitado a 20
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'key', 'code': 8, 'val': 1})[0], 200)
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'touch', 'x': 0.5, 'y': 0.5, 'down': True})[0], 200)
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'touch', 'x': 9, 'y': -3, 'down': False})[0], 200)   # fora da tela: encosta na borda
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'tilt', 'dir': 'up'})[0], 200)
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'tilt', 'dir': 'xx'})[0], 400)
        self.assertEqual(self.c.req('POST', '/p/input', {'t': 'nada'})[0], 400)
        calls = self.app.rt.calls
        self.assertIn(('rotor', 3), calls); self.assertIn(('rotor', 20), calls); self.assertIn(('key', 8, 1), calls)
        self.assertIn(('touch', 720, 270, True, False), calls); self.assertIn(('touch', 1439, 0, False, False), calls)
        self.assertEqual([c for c in calls if c[0] == 'key' and c[1] == 9], [('key', 9, 1), ('key', 9, 0)])

    def test_screen_long_poll(self):
        self.login()
        sc, b = self.c.req('GET', '/p/screen.png?since=-1'); self.assertEqual((sc, b[:4]), (200, b'\x89PNG'))
        self.app.rt.seq = 5
        sc, _ = self.c.req('GET', '/p/screen.png?since=5'); self.assertEqual(sc, 204)       # sem quadro novo

    def test_gps_moves_virtual_gps(self):
        self.login()
        sc, _ = self.c.req('POST', '/p/gps', {'lat': -23.5505, 'lon': -46.6333, 'speed': 10, 'heading': 90, 'accuracy': 10})
        self.assertEqual(sc, 200); s = self.app.g.state()
        self.assertEqual((s['mode'], s['lat'], s['lon'], s['heading']), ('manual', -23.5505, -46.6333, 90.0)); self.assertTrue(s['fix'])
        self.assertEqual(self.app.g.speed_kmh, 36.0)
        self.assertEqual(self.c.req('POST', '/p/gps', {'lat': 200, 'lon': 0})[0], 400)       # latitude impossível
        self.assertEqual(self.c.req('POST', '/p/gps', {'lat': 'x', 'lon': 0})[0], 400)
        st = self.link.state(); self.assertEqual(st['gps_fixes'], 1); self.assertEqual(st['gps']['lat'], -23.5505)

    def test_body_limit(self):
        self.login()
        self.assertEqual(self.c.req('POST', '/p/input', raw=b'{"t":"rotor","pad":"' + b'a' * (phone.MAX_BODY + 10) + b'"}')[0], 400)

    def test_https_same_pin(self):
        c = Client(self.link.https_port, https=True)
        self.assertEqual(c.req('GET', '/p/state')[0], 401); self.login(c); self.assertEqual(c.req('GET', '/p/state')[0], 200)

    def test_stop_closes(self):
        link = phone.PhoneLink(self.app, ports=(0, 0)); link.start(pin='111111'); port = link.http_port
        self.assertEqual(Client(port).req('GET', '/p/state')[0], 401)
        link.stop(); self.assertFalse(link.state()['running'])
        with self.assertRaises(OSError): Client(port).req('GET', '/p/state')


class CertTest(unittest.TestCase):
    def test_cert_has_lan_ips_and_is_reused(self):
        with tempfile.TemporaryDirectory() as d:
            old, phone.CERT_DIR = phone.CERT_DIR, d
            try:
                crt, key = phone.make_cert(['192.168.1.20']); m1 = os.path.getmtime(crt)
                self.assertEqual(oct(os.stat(key).st_mode & 0o777), '0o600')
                self.assertEqual(phone.make_cert(['192.168.1.20']), (crt, key)); self.assertEqual(os.path.getmtime(crt), m1)   # reaproveita
                phone.make_cert(['10.0.0.9'])                                                                                    # IP mudou: refaz
                self.assertEqual(json.load(open(os.path.join(d, 'ips.json'))), ['10.0.0.9'])
            finally: phone.CERT_DIR = old


if __name__ == '__main__':
    unittest.main()

"""Serviço de mapa: pedidos de bloco, cache e fonte desligada, sem rede externa (servidor HTTP local)."""
import http.server, json, os, socket, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import mapsvc


class Gps:
    def state(self):
        return {'lat': -23.5, 'lon': -46.6, 'heading': 90.0}


class Tiles(http.server.BaseHTTPRequestHandler):
    hits = []
    fail = False

    def do_GET(self):
        Tiles.hits.append(self.path)
        if Tiles.fail:
            self.send_error(429)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'\x89PNG\r\n\x1a\n' + b'x' * 32)

    def log_message(self, *a):
        pass


class MapServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='map', dir='/tmp')
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, True))
        self.old = mapsvc.CACHE
        mapsvc.CACHE = os.path.join(self.tmp, 'cache')
        self.addCleanup(lambda: setattr(mapsvc, 'CACHE', self.old))
        self.ins = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.ins.bind(os.path.join(self.tmp, 'input.sock'))
        self.ins.settimeout(0.2)
        self.addCleanup(self.ins.close)
        Tiles.hits, Tiles.fail = [], False
        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Tiles)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.url = 'http://127.0.0.1:%d/{z}/{x}/{y}.png' % self.srv.server_address[1]

    def lines(self, want=None, t=3.0):
        out, end = [], time.time() + t
        while time.time() < end:
            try:
                out.append(self.ins.recv(200).decode())
            except socket.timeout:
                pass
            if want and any(want in l for l in out):
                break
        return out

    def svc(self, **kw):
        s = mapsvc.MapService(self.tmp, Gps(), kw)
        s.start()
        self.addCleanup(s.stop)
        return s

    def request(self, z, x, y):
        c = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        c.sendto(b'%d %d %d' % (z, x, y), os.path.join(self.tmp, 'map.sock'))
        c.close()

    def test_off_never_touches_the_network(self):
        s = self.svc()
        self.assertFalse(s.state()['online'])
        self.request(16, 1, 2)
        time.sleep(0.4)
        self.assertEqual(Tiles.hits, [])
        self.assertEqual(s.stats['downloaded'], 0)
        self.assertTrue(any('Map data off' in l for l in self.lines(t=0.3)))

    def test_download_goes_to_cache_and_notifies(self):
        s = self.svc(map_source=self.url)
        self.request(16, 1, 2)
        got = self.lines('M t 16 1 2')
        self.assertTrue(any(l == 'M t 16 1 2' for l in got), got)
        self.assertTrue(os.path.getsize(mapsvc.MapService.tile_path(16, 1, 2)) > 0)
        self.assertEqual(Tiles.hits, ['/16/1/2.png'])

    def test_cached_tile_is_not_downloaded_again(self):
        s = self.svc(map_source=self.url)
        p = mapsvc.MapService.tile_path(5, 6, 7)
        os.makedirs(os.path.dirname(p))
        open(p, 'wb').write(b'cached')
        self.request(5, 6, 7)
        self.assertTrue(any(l == 'M t 5 6 7' for l in self.lines('M t 5 6 7')))
        self.assertEqual(Tiles.hits, [])
        self.assertEqual(s.stats['cached'], 1)

    def test_failure_is_reported_and_not_retried_at_once(self):
        Tiles.fail = True
        s = self.svc(map_source=self.url)
        self.request(3, 3, 3)
        time.sleep(0.5)
        self.request(3, 3, 3)
        time.sleep(0.3)
        self.assertEqual(len(Tiles.hits), 1)
        self.assertEqual(s.stats['failed'], 1)
        self.assertIn('429', s.state()['error'])

    def test_zoom_is_clamped_and_sent(self):
        s = self.svc()
        s.set(zoom=99)
        self.assertEqual(s.zoom, 19.0)
        self.assertTrue(any(l == 'M z 19.00' for l in self.lines('M z 19.00')))

    def test_position_comes_from_the_gps(self):
        self.svc()
        self.assertTrue(any(l.startswith('M p -23.5000000 -46.6000000 90.0') for l in self.lines('M p ')))

    def test_custom_source_needs_a_template(self):
        s = self.svc(map_source='not a url')
        self.assertFalse(s.state()['online'])


if __name__ == '__main__':
    unittest.main()

import math
import os
import socket
import struct
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import gps                           # noqa: E402
from idemu.gps import GpsSim, GpsError, nmea_checksum, verify_nmea, parse_gpx, Route   # noqa: E402
from idemu.canbus import CanBus                 # noqa: E402

GPX = """<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><name>t</name><trkseg>
  <trkpt lat="-23.5500" lon="-46.6300"><ele>760</ele></trkpt>
  <trkpt lat="-23.5500" lon="-46.6200"></trkpt>
  <trkpt lat="-23.5400" lon="-46.6200"></trkpt>
 </trkseg></trk></gpx>"""


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def parse_fields(line):
    return line[1:line.index("*")].split(",")


def nmea_to_deg(v, hemi):
    deg = int(float(v) / 100)
    d = deg + (float(v) - deg * 100) / 60.0
    return -d if hemi in "SW" else d


class TestGeo(unittest.TestCase):
    def test_haversine_known(self):
        # 1 grau de latitude ~ 111.19 km
        self.assertAlmostEqual(gps.haversine_m(0, 0, 1, 0), 111195, delta=100)
        # São Paulo -> Rio ~ 360 km
        d = gps.haversine_m(-23.5505, -46.6333, -22.9068, -43.1729)
        self.assertAlmostEqual(d / 1000, 357, delta=6)

    def test_destination_inverse_of_haversine_bearing(self):
        for lat, lon, brg, dist in ((-23.55, -46.63, 33.0, 5000), (10, 170, 90, 200000), (60, 10, 250, 12345),
                                    (0, 0, 0, 1000), (-80, 20, 180, 50000)):
            la, lo = gps.destination(lat, lon, brg, dist)
            self.assertAlmostEqual(gps.haversine_m(lat, lon, la, lo), dist, delta=dist * 1e-6 + 1e-3)
            if dist < 1e5 and abs(lat) < 70:
                self.assertAlmostEqual(gps.bearing_deg(lat, lon, la, lo), brg % 360, delta=0.1)

    def test_destination_wraps_antimeridian(self):
        la, lo = gps.destination(0, 179.9, 90, 50000)
        self.assertTrue(-180 <= lo <= 180)
        self.assertLess(lo, 0)

    def test_bearing_cardinals(self):
        self.assertAlmostEqual(gps.bearing_deg(0, 0, 1, 0), 0, places=3)
        self.assertAlmostEqual(gps.bearing_deg(0, 0, 0, 1), 90, places=3)
        self.assertAlmostEqual(gps.bearing_deg(0, 0, -1, 0), 180, places=3)
        self.assertAlmostEqual(gps.bearing_deg(0, 0, 0, -1), 270, places=3)


class TestGpx(unittest.TestCase):
    def test_trkpt(self):
        pts = parse_gpx(GPX)
        self.assertEqual(len(pts), 3)
        self.assertEqual(pts[0], (-23.55, -46.63))

    def test_rtept_and_wpt_fallback(self):
        rte = '<gpx><rte><rtept lat="1" lon="2"/><rtept lat="1.1" lon="2.1"/></rte></gpx>'
        self.assertEqual(parse_gpx(rte), [(1.0, 2.0), (1.1, 2.1)])
        wpt = '<gpx><wpt lat="3" lon="4"/><wpt lat="3.5" lon="4"/></gpx>'
        self.assertEqual(len(parse_gpx(wpt)), 2)

    def test_errors(self):
        for bad in ("", "   ", "<gpx><trk></trk></gpx>", "<gpx><trkpt lat='1'/></gpx>", "nao eh xml", "<gpx><trkpt lat='a' lon='1'/></gpx>"):
            with self.assertRaises(GpsError):
                parse_gpx(bad)

    def test_route_length_and_at(self):
        r = Route("x", [(0, 0), (0, 0.01), (0.01, 0.01)])
        self.assertAlmostEqual(r.length_m, 2 * 1111.95, delta=3)
        lat, lon, brg = r.at(555.97)
        self.assertAlmostEqual(lon, 0.005, places=4)
        self.assertAlmostEqual(brg, 90, delta=0.1)
        lat, lon, brg = r.at(1111.95 + 100)
        self.assertAlmostEqual(brg, 0, delta=0.1)
        self.assertAlmostEqual(lon, 0.01, places=4)
        end = r.at(10 ** 9)
        self.assertAlmostEqual(end[0], 0.01, places=6)
        self.assertAlmostEqual(end[1], 0.01, places=6)

    def test_route_validation(self):
        with self.assertRaises(GpsError):
            Route("x", [])
        with self.assertRaises(GpsError):
            Route("x", [(0, 0)])
        with self.assertRaises(GpsError):
            Route("x", [(0, 0), (0, 0)])
        with self.assertRaises(GpsError):
            Route("x", [(0, 0), (91, 0)])
        with self.assertRaises(GpsError):
            Route("x", [(0, 0), (0, 181)])


class TestNmea(unittest.TestCase):
    def test_checksum_known(self):
        # exemplo clássico da especificação
        self.assertEqual(nmea_checksum("GPGLL,4916.45,N,12311.12,W,225444,A"), "31")
        self.assertTrue(verify_nmea("$GPGLL,4916.45,N,12311.12,W,225444,A*31"))
        self.assertFalse(verify_nmea("$GPGLL,4916.45,N,12311.12,W,225444,A*32"))
        self.assertFalse(verify_nmea("GPGLL"))

    def test_sentences_valid_with_fix(self):
        g = GpsSim(clock=lambda: 1730000000.0)        # 2024-10-27 03:33:20 UTC
        g.set(lat=-23.5505, lon=-46.6333, alt=760, sats=9, hdop=0.9)
        lines = g.step(0)
        kinds = [l[3:6] for l in lines]
        for k in ("GGA", "RMC", "GSA", "GSV", "VTG", "GLL"):
            self.assertIn(k, kinds)
        for l in lines:
            self.assertTrue(l.startswith("$GP") and l.endswith("\r\n"), l)
            self.assertTrue(verify_nmea(l), l)
            self.assertLessEqual(len(l), 82)
        gga = parse_fields([l for l in lines if "GGA" in l[:7]][0])
        self.assertEqual(gga[1], "033320.00")
        self.assertEqual(gga[6], "1")
        self.assertEqual(gga[7], "09")
        self.assertEqual(gga[8], "0.9")
        self.assertEqual(gga[9], "760.0")
        self.assertAlmostEqual(nmea_to_deg(gga[2], gga[3]), -23.5505, places=5)
        self.assertAlmostEqual(nmea_to_deg(gga[4], gga[5]), -46.6333, places=5)
        rmc = parse_fields([l for l in lines if "RMC" in l[:7]][0])
        self.assertEqual(rmc[2], "A")
        self.assertEqual(rmc[9], "271024")
        # GSV: números de sentenças coerentes
        gsv = [parse_fields(l) for l in lines if "GSV" in l[:7]]
        self.assertEqual([int(x[2]) for x in gsv], list(range(1, len(gsv) + 1)))
        self.assertTrue(all(int(x[1]) == len(gsv) for x in gsv))

    def test_no_fix_sentences(self):
        g = GpsSim(clock=lambda: 1730000000.0)
        g.set(fix=False)
        lines = g.step(0)
        for l in lines:
            self.assertTrue(verify_nmea(l), l)
        gga = parse_fields([l for l in lines if "GGA" in l[:7]][0])
        self.assertEqual(gga[6], "0")
        self.assertEqual(gga[2], "")
        rmc = parse_fields([l for l in lines if "RMC" in l[:7]][0])
        self.assertEqual(rmc[2], "V")
        gsa = parse_fields([l for l in lines if "GSA" in l[:7]][0])
        self.assertEqual(gsa[2], "1")
        self.assertFalse(g.state()["fix"])

    def test_speed_and_course_in_rmc_vtg(self):
        g = GpsSim(clock=lambda: 1730000000.0)
        g.set_mode("manual")
        g.set(speed_kmh=90, heading=45)
        lines = g.step(0)
        rmc = parse_fields([l for l in lines if "RMC" in l[:7]][0])
        self.assertAlmostEqual(float(rmc[7]), 90 / 1.852, places=2)
        self.assertAlmostEqual(float(rmc[8]), 45.0, places=1)
        vtg = parse_fields([l for l in lines if "VTG" in l[:7]][0])
        self.assertAlmostEqual(float(vtg[7]), 90.0, places=1)

    def test_southern_western_hemispheres_and_northeast(self):
        g = GpsSim(clock=lambda: 1730000000.0)
        g.jump(51.5, 0.12)
        gga = parse_fields([l for l in g.step(0) if "GGA" in l[:7]][0])
        self.assertEqual((gga[3], gga[5]), ("N", "E"))
        self.assertEqual(gga[2][:4], "5130")

    def test_state_format(self):
        g = GpsSim()
        g.step(0)
        st = g.state()
        for k in ("mode", "fix", "lat", "lon", "alt", "speed_kmh", "heading", "sats", "hdop", "route",
                  "sync_can_speed", "nmea_tail"):
            self.assertIn(k, st)
        self.assertTrue(st["nmea_tail"][0].startswith("$GP"))
        self.assertFalse(st["nmea_tail"][0].endswith("\n"))
        self.assertIsNone(st["route"])
        g.load_route("r", gpx=GPX)
        st = g.state()
        self.assertEqual(st["route"]["name"], "r")
        self.assertEqual(st["route"]["points"], 3)
        self.assertGreater(st["route"]["length_km"], 1.0)
        self.assertEqual(st["mode"], "route")


class TestModes(unittest.TestCase):
    def test_static_does_not_move(self):
        g = GpsSim()
        g.set(speed_kmh=100)
        lat, lon = g.lat, g.lon
        g.step(10)
        self.assertEqual((g.lat, g.lon), (lat, lon))
        self.assertEqual(g.state()["speed_kmh"], 0)

    def test_manual_moves_along_heading(self):
        g = GpsSim()
        g.set_mode("manual")
        g.set(lat=0, lon=0, heading=90, speed_kmh=36)
        g.step(100)                                   # 36 km/h = 10 m/s -> 1000 m para leste
        self.assertAlmostEqual(gps.haversine_m(0, 0, g.lat, g.lon), 1000, delta=1)
        self.assertAlmostEqual(g.lat, 0, places=6)
        self.assertGreater(g.lon, 0)

    def test_circle_keeps_radius_and_heading_tangent(self):
        g = GpsSim()
        g.set(lat=-23.55, lon=-46.63)
        g.set_mode("circle", radius_m=300, speed_kmh=54)           # 15 m/s
        c = (-23.55, -46.63)
        for _ in range(50):
            g.step(7.3)
            self.assertAlmostEqual(gps.haversine_m(c[0], c[1], g.lat, g.lon), 300, delta=0.5)
        # rumo tangente: perpendicular ao raio
        radial = gps.bearing_deg(c[0], c[1], g.lat, g.lon)
        self.assertAlmostEqual((g.heading - radial) % 360, 90, delta=1.0)
        # dá uma volta em 2*pi*r/v = 125.7 s
        g2 = GpsSim()
        g2.set(lat=0, lon=0)
        g2.set_mode("circle", radius_m=300, speed_kmh=54)
        p0 = (g2.lat, g2.lon)
        g2.step(2 * math.pi * 300 / 15)
        self.assertLess(gps.haversine_m(p0[0], p0[1], g2.lat, g2.lon), 1.0)

    def test_route_progress_heading_and_loop(self):
        g = GpsSim()
        g.load_route("r", points=[[0, 0], [0, 0.01], [0.01, 0.01]], speed_kmh=36, loop=True)
        total = g.route.length_m
        g.step(50)                                     # 500 m
        self.assertAlmostEqual(g.state()["route"]["progress"], 500 / total, places=3)
        self.assertAlmostEqual(g.heading, 90, delta=0.1)
        g.step(80)                                     # 1300 m: já no 2o trecho (rumo norte)
        self.assertAlmostEqual(g.heading, 0, delta=0.1)
        g.step(1000)                                   # dá voltas
        self.assertLess(g.route_dist, total)
        self.assertEqual(g.mode, "route")

    def test_route_no_loop_stops_at_end(self):
        g = GpsSim()
        g.load_route("r", points=[[0, 0], [0, 0.001]], speed_kmh=36, loop=False)
        g.step(1000)
        self.assertAlmostEqual(g.lon, 0.001, places=6)
        self.assertEqual(g.state()["speed_kmh"], 0)
        self.assertAlmostEqual(g.state()["route"]["progress"], 1.0)

    def test_route_from_gpx_text(self):
        g = GpsSim()
        g.load_route("gpx", gpx=GPX, speed_kmh=60)
        self.assertEqual(len(g.route.points), 3)
        self.assertAlmostEqual(g.lat, -23.55, places=6)

    def test_route_errors(self):
        g = GpsSim()
        for kw in ({"points": []}, {"points": [[0, 0]]}, {"gpx": "<gpx/>"}, {}, {"points": [[0, 0], ["x", 1]]},
                   {"points": [[0, 0], [0, 1]], "gpx": GPX}, {"points": [[0, 0], [0, 1]], "speed_kmh": -5}):
            with self.assertRaises(GpsError, msg=str(kw)):
                g.load_route("x", **kw)
        with self.assertRaises(GpsError):
            g.set_mode("route")                         # sem rota
        with self.assertRaises(GpsError):
            g.set_mode("voar")
        self.assertEqual(g.mode, "static")

    def test_set_validation(self):
        g = GpsSim()
        for kw in ({"lat": 91, "lon": 0}, {"lat": 0, "lon": 200}, {"speed_kmh": -1}, {"foo": 1},
                   {"hdop": "x"}, {"radius_m": 0}):
            with self.assertRaises(GpsError, msg=str(kw)):
                g.set(**kw)
        g.set(lat=10.5)                                 # só lat -> mantém lon
        self.assertEqual(g.lat, 10.5)
        with self.assertRaises(GpsError):
            g.jump(100, 0)

    def test_jump_resets_route_to_manual(self):
        g = GpsSim()
        g.load_route("r", points=[[0, 0], [0, 1]])
        g.jump(10, 10)
        self.assertEqual(g.mode, "manual")
        self.assertEqual((g.lat, g.lon), (10, 10))


class TestCanSync(unittest.TestCase):
    def test_from_can_speed(self):
        can = CanBus()
        g = GpsSim(can=can)
        g.load_route("r", points=[[0, 0], [0, 0.1]], speed_kmh=10)
        g.set(sync_can_speed=True)
        can.set_signal("vehicle_speed", 72)             # 20 m/s
        g.step(10)
        self.assertAlmostEqual(g.route_dist, 200, delta=0.5)
        self.assertEqual(g.state()["speed_kmh"], 72)
        can.set_signal("vehicle_speed", 0)
        g.step(10)
        self.assertAlmostEqual(g.route_dist, 200, delta=0.5)

    def test_without_sync_uses_configured_speed(self):
        can = CanBus()
        can.set_signal("vehicle_speed", 100)
        g = GpsSim(can=can)
        g.load_route("r", points=[[0, 0], [0, 0.1]], speed_kmh=36)
        g.step(10)
        self.assertAlmostEqual(g.route_dist, 100, delta=0.5)

    def test_to_can_speed(self):
        can = CanBus()
        g = GpsSim(can=can)
        g.set_mode("circle", radius_m=100, speed_kmh=45)
        g.set(sync_can_speed=True, sync_dir="to_can")
        g.step(1)
        self.assertEqual(can.get_signal("vehicle_speed"), 45)


class TestUbx(unittest.TestCase):
    def setUp(self):
        self.g = GpsSim(clock=lambda: 1730000000.0)
        self.frames = []
        self.g.on_ubx(self.frames.append)
        self.g.set(lat=-23.5505, lon=-46.6333, alt=760, sats=9)
        self.g.step(0)

    def test_checksums_and_lengths(self):
        self.assertEqual(len(self.frames), 3)
        expect = {(1, 7): 92, (1, 2): 28, (1, 6): 52}
        for f in self.frames:
            self.assertTrue(gps.verify_ubx(f))
            self.assertEqual(f[:2], b"\xb5\x62")
            self.assertEqual(expect[(f[2], f[3])], struct.unpack("<H", f[4:6])[0])
        bad = bytearray(self.frames[0])
        bad[10] ^= 0xFF
        self.assertFalse(gps.verify_ubx(bytes(bad)))

    def test_checksum_matches_reference_algorithm(self):
        f = self.frames[1]
        ck_a = ck_b = 0
        for b in f[2:-2]:
            ck_a = (ck_a + b) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF
        self.assertEqual((f[-2], f[-1]), (ck_a, ck_b))

    def test_pvt_fields(self):
        pvt = [f for f in self.frames if f[3] == 7][0][6:-2]
        (itow, year, month, day, hour, minute, sec, valid) = struct.unpack("<IHBBBBBB", pvt[:12])
        self.assertEqual((year, month, day, hour, minute, sec), (2024, 10, 27, 3, 33, 20))
        fix, flags, _, nsv = struct.unpack("<BBBB", pvt[20:24])
        self.assertEqual((fix, nsv), (3, 9))
        lon, lat, h, hmsl = struct.unpack("<iiii", pvt[24:40])
        self.assertAlmostEqual(lon / 1e7, -46.6333, places=6)
        self.assertAlmostEqual(lat / 1e7, -23.5505, places=6)
        self.assertEqual(h, 760000)

    def test_posllh_fields_and_nofix(self):
        ll = [f for f in self.frames if f[3] == 2][0][6:-2]
        itow, lon, lat, h, hmsl, hacc, vacc = struct.unpack("<IiiiiII", ll)
        self.assertAlmostEqual(lat / 1e7, -23.5505, places=6)
        self.frames[:] = []
        self.g.set(fix=False)
        self.g.step(0)
        pvt = [f for f in self.frames if f[3] == 7][0][6:-2]
        self.assertEqual(pvt[20], 0)
        for f in self.frames:
            self.assertTrue(gps.verify_ubx(f))

    def test_sol_ecef_magnitude(self):
        sol = [f for f in self.frames if f[3] == 6][0][6:-2]
        x, y, z = struct.unpack("<iii", sol[12:24])
        r = math.sqrt(x * x + y * y + z * z) / 100.0
        self.assertAlmostEqual(r, 6.37e6, delta=3e4)


class TestRunningAndTcp(unittest.TestCase):
    def test_thread_emits_at_rate(self):
        g = GpsSim(rate_hz=10)
        got = []
        g.on_nmea(got.append)
        g.start()
        try:
            time.sleep(1.05)
        finally:
            g.stop()
        gga = [l for l in got if l[3:6] == "GGA"]
        self.assertTrue(8 <= len(gga) <= 13, len(gga))
        self.assertTrue(all(verify_nmea(l) for l in got))

    def test_tcp_stream(self):
        g = GpsSim(tcp_port=0, rate_hz=10)
        g.start()
        try:
            s = socket.create_connection(("127.0.0.1", g.tcp_port), timeout=3)
            s.settimeout(0.3)
            buf = b""
            end = time.time() + 3
            while buf.count(b"$GPGGA") < 2 and time.time() < end:
                try:
                    buf += s.recv(65536)
                except socket.timeout:
                    pass
            s.close()
        finally:
            g.stop()
        lines = buf.decode().split("\r\n")
        good = [l for l in lines if l.startswith("$GP") and "*" in l]
        self.assertTrue(len(good) >= 8)
        self.assertTrue(all(verify_nmea(l) for l in good[:-1]))
        self.assertGreaterEqual(buf.count(b"$GPGGA"), 2)

    def test_stop_closes_port(self):
        g = GpsSim(tcp_port=0)
        g.start()
        port = g.tcp_port
        g.stop()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.5)

    def test_bad_callback_ignored(self):
        g = GpsSim()
        g.on_nmea(lambda l: 1 / 0)
        ok = []
        g.on_nmea(ok.append)
        g.step(0)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()

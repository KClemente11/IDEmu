import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import canbus                       # noqa: E402
from idemu.canbus import CanBus, Signal, pack_raw, unpack_raw, parse_candump_line   # noqa: E402


def wait_for(cond, timeout=3.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class TestBitPacking(unittest.TestCase):
    def test_intel_roundtrip_all_positions(self):
        for length in (1, 3, 8, 11, 12, 16, 17, 32):
            for start in range(0, 64 - length + 1, 3):
                for raw in (0, 1, (1 << length) - 1, (1 << length) // 3):
                    buf = bytearray(8)
                    pack_raw(buf, start, length, "intel", raw)
                    self.assertEqual(unpack_raw(buf, start, length, "intel"), raw, (start, length, raw))

    def test_intel_known_bytes(self):
        buf = bytearray(8)
        pack_raw(buf, 0, 16, "intel", 0x1234)
        self.assertEqual(bytes(buf[:2]), b"\x34\x12")
        buf = bytearray(8)
        pack_raw(buf, 4, 8, "intel", 0xAB)          # cruza byte: nibble baixo do 1o, alto do 2o
        self.assertEqual(bytes(buf[:2]), b"\xb0\x0a")

    def test_motorola_known_and_roundtrip(self):
        buf = bytearray(8)
        pack_raw(buf, 7, 16, "motorola", 0x1234)   # DBC: start_bit=7 (MSB do byte 0), big endian
        self.assertEqual(bytes(buf[:2]), b"\x12\x34")
        for length in (1, 4, 12, 16, 24):
            for start in (7, 15, 3, 23, 39):
                for raw in (0, 1, (1 << length) - 1, 0x5A5A5A & ((1 << length) - 1)):
                    buf = bytearray(8)
                    try:
                        pack_raw(buf, start, length, "motorola", raw)
                    except IndexError:
                        continue                    # não cabe em 8 bytes
                    self.assertEqual(unpack_raw(buf, start, length, "motorola"), raw)

    def test_pack_does_not_touch_neighbours(self):
        buf = bytearray(b"\xff" * 8)
        pack_raw(buf, 12, 4, "intel", 0)
        self.assertEqual(bytes(buf), b"\xff\x0f" + b"\xff" * 6)

    def test_signal_scaling_signed_and_clamp(self):
        s = Signal({"name": "x", "can_id": 1, "start_bit": 0, "length": 16, "factor": 0.1, "signed": True,
                    "min": -720, "max": 720, "kind": "number"})
        buf = bytearray(8)
        s.pack(buf, -123.4)
        self.assertAlmostEqual(s.unpack(bytes(buf)), -123.4, places=5)
        s.pack(buf, 10 ** 6)                       # satura em +32767 raw
        self.assertAlmostEqual(s.unpack(bytes(buf)), 3276.7, places=3)
        s2 = Signal({"name": "t", "can_id": 1, "start_bit": 0, "length": 8, "factor": 0.5, "offset": -40,
                     "min": -40, "max": 60})
        b2 = bytearray(2)
        s2.pack(b2, 22)
        self.assertEqual(b2[0], 124)               # (22+40)/0.5
        self.assertAlmostEqual(s2.unpack(b2), 22)

    def test_coerce(self):
        s = Signal({"name": "g", "can_id": 1, "start_bit": 0, "length": 4, "kind": "enum",
                    "enum": {"0": "P", "3": "D"}})
        self.assertEqual(s.coerce("D"), 3)
        self.assertEqual(s.coerce(0), 0)
        with self.assertRaises(ValueError):
            s.coerce(1)
        b = Signal({"name": "b", "can_id": 1, "start_bit": 0, "length": 1, "kind": "bool"})
        self.assertEqual(b.coerce("on"), 1)
        self.assertEqual(b.coerce(False), 0)
        with self.assertRaises(ValueError):
            b.coerce("talvez")


class TestSignalDatabase(unittest.TestCase):
    def setUp(self):
        self.bus = CanBus()

    def test_required_coverage(self):
        names = set(self.bus.signal_names())
        for n in ("vehicle_speed", "engine_rpm", "gear_position", "terminal_state", "outside_temp",
                  "coolant_temp", "fuel_level", "odometer", "headlight_low", "headlight_high", "turn_left",
                  "turn_right", "parking_brake", "door_driver", "seatbelt_driver", "steering_angle",
                  "clock_hour", "clock_year", "tire_pressure_fl", "fuel_consumption", "driving_mode"):
            self.assertIn(n, names)

    def test_every_signal_has_metadata(self):
        with open(canbus.DEFAULT_SIGNALS, encoding="utf-8") as f:
            db = json.load(f)
        for s in db["signals"]:
            for k in ("name", "label", "group", "unit", "can_id", "start_bit", "length", "byte_order", "factor",
                      "offset", "min", "max", "step", "kind", "cycle_ms", "default", "source", "confidence"):
                self.assertIn(k, s, "%s sem %s" % (s["name"], k))
            self.assertIn(s["confidence"], ("alta", "média", "baixa", "definido-pelo-IDEmu"))

    def test_no_bit_overlap_within_frame(self):
        used = {}
        for name in self.bus.signal_names():
            sg = self.bus._signals[name]
            for pos in canbus._positions(sg.start_bit, sg.length, sg.order):
                key = (sg.can_id, pos)
                self.assertNotIn(key, used, "%s sobrepõe %s" % (name, used.get(key)))
                used[key] = name

    def test_all_signals_roundtrip_through_frame(self):
        # default de cada sinal -> quadro -> valor decodificado (dentro da resolução)
        for name in self.bus.signal_names():
            sg = self.bus._signals[name]
            v = self.bus.get_signal(name)
            data = self.bus.frame_bytes(sg.can_id)
            got = sg.unpack(data)
            tol = abs(sg.factor) * 0.51 + 1e-9
            self.assertAlmostEqual(got, v, delta=tol, msg=name)

    def test_set_get_and_frame_bytes(self):
        self.bus.set_signal("vehicle_speed", 100)
        d = self.bus.frame_bytes(0x1B4)
        self.assertEqual(d[1] >> 4, 0xD)           # nibble fixo do layout
        self.assertAlmostEqual(self.bus._signals["vehicle_speed"].unpack(d), 100, delta=0.06)
        self.bus.set_signal("engine_rpm", 3000)
        d = self.bus.frame_bytes(0x0AA)
        self.assertEqual(d[4] | (d[5] << 8), 12000)      # rpm*4 little-endian
        self.bus.set_signal("terminal_state", 85)
        self.assertEqual(self.bus.frame_bytes(0x130)[0], 0x55)
        self.bus.set_signal("door_driver", 1)
        self.bus.set_signal("trunk_open", 1)
        d = self.bus.frame_bytes(0x2FC)
        self.assertEqual((d[0], d[1], d[2]), (0x81, 0x01, 0x01))
        self.bus.set_signal("outside_temp", 8.5)
        self.assertEqual(self.bus.frame_bytes(0x2CA)[0], 97)
        self.bus.set_signal("parking_brake", 1)
        self.assertEqual(self.bus.frame_bytes(0x1B4)[5], 0x32)
        self.bus.set_signal("coolant_temp", 91)
        self.assertEqual(self.bus.frame_bytes(0x1D0)[0], 139)

    def test_set_errors(self):
        with self.assertRaises(KeyError):
            self.bus.set_signal("nao_existe", 1)
        with self.assertRaises(ValueError):
            self.bus.set_signal("gear_position", 9)
        with self.assertRaises(ValueError):
            self.bus.set_signal("vehicle_speed", "abc")
        self.assertEqual(self.bus.set_signal("vehicle_speed", 9999), 300)        # satura em max

    def test_snapshot_format(self):
        snap = self.bus.snapshot()
        self.assertIn("groups", snap)
        self.assertIn("running", snap)
        found = None
        for g in snap["groups"]:
            self.assertIn("name", g)
            for s in g["signals"]:
                for k in ("name", "label", "unit", "min", "max", "value", "can_id", "cycle_ms", "step", "kind", "enum"):
                    self.assertIn(k, s)
                if s["name"] == "gear_position":
                    found = s
        self.assertEqual(found["kind"], "enum")
        self.assertEqual(found["enum"]["3"], "D")
        json.dumps(snap)                              # serializável

    def test_clock_auto_and_manual(self):
        a = self.bus.get_signal("clock_year")
        self.bus._sim_step(time.monotonic(), 0.05)
        self.assertEqual(self.bus.get_signal("clock_year"), time.localtime().tm_year)
        self.bus.set_signal("clock_hour", 7)
        self.bus._sim_step(time.monotonic(), 0.05)
        self.assertEqual(self.bus.get_signal("clock_hour"), 7)
        self.bus.set_signal("clock_hour", None)
        self.assertEqual(self.bus.get_signal("clock_hour"), time.localtime().tm_hour)
        d = self.bus.frame_bytes(0x2F8)
        self.assertEqual(d[4] & 0x0F, 0x0F)
        self.assertEqual(d[4] >> 4, time.localtime().tm_mon)


class TestCyclic(unittest.TestCase):
    def test_cycle_rates_and_callback(self):
        bus = CanBus()
        got = []
        lock = threading.Lock()

        def cb(ts, cid, data, ext, name, direction):
            with lock:
                got.append((ts, cid, data, ext, name, direction))
        bus.on_frame(cb)
        bus.start()
        try:
            time.sleep(1.5)
        finally:
            bus.stop()
        with lock:
            frames = list(got)
        by = {}
        for f in frames:
            by.setdefault(f[1], []).append(f)
        # 0x1B4 a cada 20 ms -> ~75 em 1,5 s ; 0x130 a cada 100 ms -> ~15
        self.assertTrue(55 <= len(by[0x1B4]) <= 80, len(by[0x1B4]))
        self.assertTrue(11 <= len(by[0x130]) <= 17, len(by[0x130]))
        self.assertTrue(110 <= len(by[0x0AA]) <= 160, len(by[0x0AA]))
        self.assertTrue(all(f[5] == "tx" for f in frames))
        self.assertEqual(by[0x130][0][4], "terminal_status")
        # sem drift: espaçamento médio ~ período
        ts = [f[0] for f in by[0x1B4]]
        mean = (ts[-1] - ts[0]) / (len(ts) - 1)
        self.assertAlmostEqual(mean, 0.020, delta=0.002)

    def test_signal_change_appears_in_frames(self):
        bus = CanBus()
        bus.start()
        try:
            bus.set_signal("engine_rpm", 2000)
            time.sleep(0.2)
            fr = bus.frames_since(0, 5000)["frames"]
        finally:
            bus.stop()
        rpm_frames = [f for f in fr if f["id"] == "0AA"]
        last = bytes.fromhex(rpm_frames[-1]["data"])
        self.assertEqual((last[4] | last[5] << 8) / 4, 2000)

    def test_stop_and_restart(self):
        bus = CanBus()
        bus.start()
        bus.stop()
        n = bus.frames_since(0)["seq"]
        time.sleep(0.2)
        self.assertEqual(bus.frames_since(0)["seq"], n)
        bus.start()
        self.assertTrue(wait_for(lambda: bus.frames_since(0)["seq"] > n))
        bus.stop()

    def test_bad_callback_does_not_break(self):
        bus = CanBus()
        bus.on_frame(lambda *a: 1 / 0)
        ok = []
        bus.on_frame(lambda *a: ok.append(1))
        bus.start()
        time.sleep(0.2)
        bus.stop()
        self.assertTrue(ok)


class TestFramesApi(unittest.TestCase):
    def test_inject_and_frames_since(self):
        bus = CanBus()
        seen = []
        bus.on_frame(lambda ts, i, d, e, n, dr: seen.append((i, d, e, n, dr)))
        bus.inject(0x1A0, bytes.fromhex("0011223344556677"))
        bus.inject(0x18DAF110, b"\x01\x02", ext=True)
        self.assertEqual(seen[0], (0x1A0, bytes.fromhex("0011223344556677"), False, None, "tx"))
        self.assertEqual(seen[1][2], True)
        r = bus.frames_since(0)
        self.assertEqual(r["seq"], 2)
        self.assertEqual(r["frames"][0]["id"], "1A0")
        self.assertEqual(r["frames"][0]["dlc"], 8)
        self.assertEqual(r["frames"][0]["data"], "0011223344556677")
        self.assertEqual(r["frames"][1]["id"], "18DAF110")
        self.assertEqual(bus.frames_since(2), {"seq": 2, "frames": []})
        r = bus.frames_since(0, limit=1)
        self.assertEqual((r["seq"], len(r["frames"])), (1, 1))
        r2 = bus.frames_since(r["seq"])
        self.assertEqual(r2["frames"][0]["seq"], 2)
        for k in ("seq", "t", "id", "dlc", "data", "dir", "name"):
            self.assertIn(k, r["frames"][0])

    def test_inject_validation(self):
        bus = CanBus()
        with self.assertRaises(ValueError):
            bus.inject(0x800, b"")
        with self.assertRaises(ValueError):
            bus.inject(0x100, b"\x00" * 9)
        bus.inject(0x130, "45 40")                    # string hex aceita

    def test_ring_buffer_limit(self):
        bus = CanBus()
        for i in range(6000):
            bus.inject(0x100, b"\x00")
        r = bus.frames_since(0, limit=10000)
        self.assertEqual(len(r["frames"]), 5000)
        self.assertEqual(r["frames"][0]["seq"], 1001)
        self.assertEqual(r["seq"], 6000)


class TestScenarios(unittest.TestCase):
    def test_list_and_ids(self):
        bus = CanBus()
        sc = bus.scenarios()
        ids = [s["id"] for s in sc["scenarios"]]
        for i in ("parado_motor_desligado", "partida", "cidade", "rodovia", "estacionando"):
            self.assertIn(i, ids)
        self.assertIsNone(sc["active"])
        for s in sc["scenarios"]:
            self.assertTrue(s["name"] and s["desc"])

    def test_interpolation(self):
        kf = [[0, 0], [10, 100]]
        self.assertEqual(CanBus._interp(kf, 5, False), 50)
        self.assertEqual(CanBus._interp(kf, -1, False), 0)
        self.assertEqual(CanBus._interp(kf, 20, False), 100)
        self.assertEqual(CanBus._interp([[0, 1], [5, 2], [9, 3]], 6, True), 2)

    def test_scenario_values_follow_timeline(self):
        bus = CanBus()
        bus.run_scenario("rodovia")
        self.assertEqual(bus.scenarios()["active"], "rodovia")
        bus._scenario_step(20.0)
        self.assertEqual(bus.get_signal("vehicle_speed"), 118)
        self.assertGreater(bus.get_signal("engine_rpm"), 1500)          # drivetrain derivado
        bus._scenario_step(10.0)
        self.assertAlmostEqual(bus.get_signal("vehicle_speed"), 114, delta=1)
        bus.run_scenario(None)
        self.assertIsNone(bus.scenarios()["active"])
        with self.assertRaises(KeyError):
            bus.run_scenario("nao_existe")

    def test_highway_speed_range(self):
        bus = CanBus()
        bus.run_scenario("rodovia")
        vals = []
        for t in range(0, 90):
            bus._scenario_step(float(t))
            vals.append(bus.get_signal("vehicle_speed"))
        self.assertTrue(all(108 <= v <= 121 for v in vals), (min(vals), max(vals)))

    def test_partida_sequence_and_end(self):
        bus = CanBus()
        bus.run_scenario("partida")
        seen = set()
        for t in (0, 1.2, 3, 5, 7, 12):
            bus._scenario_step(t)
            seen.add(bus.get_signal("terminal_state"))
        self.assertEqual(seen, {0, 65, 69, 85})
        bus._scenario_step(5.0)
        self.assertEqual(bus.get_signal("terminal_state"), 85)
        self.assertEqual(bus.get_signal("engine_rpm"), 250)

    def test_reverse_in_estacionando(self):
        bus = CanBus()
        bus.run_scenario("estacionando")
        bus._scenario_step(10)
        self.assertEqual(bus.get_signal("gear_position"), 1)             # R
        self.assertLess(bus.get_signal("vehicle_speed"), 6)

    def test_non_loop_scenario_ends(self):
        bus = CanBus()
        bus.run_scenario("partida")
        bus._active_t0 -= 100
        bus._sim_step(time.monotonic(), 0.05)
        self.assertIsNone(bus.scenarios()["active"])
        self.assertEqual(bus.get_signal("terminal_state"), 69)

    def test_loop_scenario_wraps(self):
        bus = CanBus()
        bus.run_scenario("cidade")
        bus._active_t0 -= 125
        bus._sim_step(time.monotonic(), 0.05)
        self.assertEqual(bus.scenarios()["active"], "cidade")

    def test_scenario_thread_runs(self):
        bus = CanBus()
        bus.start()
        try:
            bus.run_scenario("rodovia")
            self.assertTrue(wait_for(lambda: bus.get_signal("vehicle_speed") > 100))
        finally:
            bus.stop()

    def test_odometer_integrates(self):
        bus = CanBus()
        bus.set_signal("vehicle_speed", 100)
        o0 = bus.get_signal("odometer")
        bus._sim_step(time.monotonic(), 36.0)         # 36 s a 100 km/h = 1 km
        self.assertAlmostEqual(bus.get_signal("odometer") - o0, 1.0, places=2)


class TestRecordReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_candump_parse(self):
        self.assertEqual(parse_candump_line("(1234567890.123456) can0 1A0#0011223344556677"),
                         (1234567890.123456, 0x1A0, bytes.fromhex("0011223344556677"), False))
        self.assertEqual(parse_candump_line("(1.5) can0 18DAF110#0102")[3], True)
        self.assertEqual(parse_candump_line("(1.5) can0 123#")[2], b"")
        self.assertIsNone(parse_candump_line("lixo"))

    def test_record_file_format(self):
        bus = CanBus(rec_dir=self.tmp)
        path = bus.record(True)
        bus.inject(0x1A0, bytes.fromhex("0011223344556677"))
        bus.inject(0x18DAF110, b"\x01", ext=True)
        self.assertEqual(bus.record(True), path)         # idempotente
        self.assertEqual(bus.record(False), path)
        self.assertIsNone(bus.record(False))
        with open(path) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 2)
        import re
        self.assertRegex(lines[0], r"^\(\d+\.\d{6}\) can0 1A0#0011223344556677$")
        self.assertRegex(lines[1], r"^\(\d+\.\d{6}\) can0 18DAF110#01$")
        rec = bus.recordings()
        self.assertEqual([r["file"] for r in rec], [os.path.basename(path)])
        self.assertGreater(rec[0]["size"], 0)

    def test_replay_respects_timing(self):
        p = os.path.join(self.tmp, "x.log")
        with open(p, "w") as f:
            f.write("(100.000000) can0 100#01\n(100.300000) can0 101#02\n(100.600000) can0 102#03\n")
        bus = CanBus(rec_dir=self.tmp)
        got = []
        bus.on_frame(lambda ts, i, d, e, n, dr: got.append((time.monotonic(), i, d)))
        bus.replay("x.log")
        self.assertTrue(wait_for(lambda: len(got) == 3, 3))
        self.assertEqual([g[1] for g in got], [0x100, 0x101, 0x102])
        self.assertAlmostEqual(got[1][0] - got[0][0], 0.3, delta=0.06)
        self.assertAlmostEqual(got[2][0] - got[0][0], 0.6, delta=0.08)
        self.assertTrue(wait_for(lambda: not bus._replaying))

    def test_replay_loop_and_stop(self):
        p = os.path.join(self.tmp, "y.log")
        with open(p, "w") as f:
            f.write("(1.0) can0 100#01\n(1.05) can0 101#02\n")
        bus = CanBus(rec_dir=self.tmp)
        got = []
        bus.on_frame(lambda ts, i, d, e, n, dr: got.append(i))
        bus.replay(p, loop=True)
        self.assertTrue(wait_for(lambda: len(got) >= 6, 3))
        bus.replay(None)
        self.assertTrue(wait_for(lambda: not bus._replaying))
        n = len(got)
        time.sleep(0.2)
        self.assertEqual(len(got), n)

    def test_replay_errors(self):
        bus = CanBus(rec_dir=self.tmp)
        with self.assertRaises(FileNotFoundError):
            bus.replay("nao_existe.log")
        with self.assertRaises(ValueError):
            bus.replay("../x.log")
        open(os.path.join(self.tmp, "vazio.log"), "w").close()
        with self.assertRaises(ValueError):
            bus.replay("vazio.log")

    def test_record_then_replay_roundtrip(self):
        bus = CanBus(rec_dir=self.tmp)
        bus.start()
        try:
            path = bus.record(True)
            time.sleep(0.4)
            bus.record(False)
            with open(path) as f:
                n = len([l for l in f if l.strip()])
            self.assertGreater(n, 20)
            got = []
            bus.on_frame(lambda *a: got.append(a))
            bus.replay(os.path.basename(path))
            self.assertTrue(wait_for(lambda: len(got) >= n, 3))
        finally:
            bus.stop()


class TestTcpServer(unittest.TestCase):
    def setUp(self):
        self.bus = CanBus(tcp_port=0)
        self.bus.start()
        self.port = self.bus.tcp_port

    def tearDown(self):
        self.bus.stop()

    def connect(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        return s

    def readlines(self, s, n, timeout=3):
        buf = b""
        end = time.time() + timeout
        s.settimeout(0.3)
        while buf.count(b"\n") < n and time.time() < end:
            try:
                d = s.recv(4096)
            except socket.timeout:
                continue
            if not d:
                break
            buf += d
        return buf.decode().splitlines()

    def test_receives_tx_frames(self):
        s = self.connect()
        try:
            lines = self.readlines(s, 10)
            self.assertGreaterEqual(len(lines), 10)
            import re
            for l in lines[:10]:
                self.assertRegex(l, r"^[0-9A-F]{3}#[0-9A-F]*$")
        finally:
            s.close()

    def test_client_frame_is_injected_as_rx(self):
        got = []
        self.bus.on_frame(lambda ts, i, d, e, n, dr: got.append((i, d, e, dr)) if dr == "rx" else None)
        s = self.connect()
        try:
            s.sendall(b"123#DEADBEEF\n18DAF110#0102\n")
            self.assertTrue(wait_for(lambda: len(got) == 2))
        finally:
            s.close()
        self.assertEqual(got[0], (0x123, bytes.fromhex("DEADBEEF"), False, "rx"))
        self.assertEqual(got[1], (0x18DAF110, b"\x01\x02", True, "rx"))

    def test_rx_frames_not_echoed_to_clients(self):
        a, b = self.connect(), self.connect()
        try:
            a.sendall(b"7AB#AA\n")
            time.sleep(0.4)
            lines = self.readlines(b, 5, 1.0)
            self.assertFalse(any(l.startswith("7AB#") for l in lines))
        finally:
            a.close()
            b.close()

    def test_set_command(self):
        s = self.connect()
        try:
            s.sendall(b"set vehicle_speed 80\n")
            self.assertTrue(wait_for(lambda: self.bus.get_signal("vehicle_speed") == 80))
            s.sendall(b"set gear_position D\nget gear_position\n")
            self.assertTrue(wait_for(lambda: self.bus.get_signal("gear_position") == 3))
            s.sendall(b"set nope 1\n")
            time.sleep(0.2)
            out = []
            end = time.time() + 2
            buf = b""
            s.settimeout(0.3)
            while time.time() < end and b"err" not in buf:
                try:
                    buf += s.recv(65536)
                except socket.timeout:
                    pass
            self.assertIn(b"err", buf)
            self.assertIn(b"ok vehicle_speed=80", buf)
        finally:
            s.close()

    def test_stop_closes_clients_and_port(self):
        s = self.connect()
        self.bus.stop()
        s.settimeout(2)
        try:
            while s.recv(65536):
                pass
        except (socket.timeout, OSError):
            pass
        s.close()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=0.5)


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_set_and_read(self):
        bus = CanBus()
        bus.start()
        errs = []

        def worker(k):
            try:
                for i in range(300):
                    bus.set_signal("engine_rpm", (i * 13 + k) % 7000)
                    bus.snapshot()
                    bus.frames_since(0, 50)
                    bus.inject(0x100 + k, b"\x01")
            except Exception as e:           # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        bus.stop()
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()

"""Testes do V850 virtual: enlace UART <-> modelo, com um 'guest falso' que fala o protocolo do ioipc-idemu.so."""
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import v850  # noqa: E402


def frame(typ, data):
    return b'\xa5\x5a' + bytes([typ]) + struct.pack('<H', len(data)) + data


def ipc_msg(chan, payload, seq=0, flags=0):
    return struct.pack('<H', (len(payload) << 4) | (seq & 15)) + bytes([chan, flags]) + payload


class FakeGuest(object):
    """Lado 'guest' da UART: servidor unix como o do QEMU."""
    def __init__(self, path):
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(1)
        self.conn = None
        self.buf = b''

    def accept(self):
        self.srv.settimeout(5)
        self.conn, _ = self.srv.accept()
        self.conn.settimeout(3)

    def send(self, typ, data):
        self.conn.sendall(frame(typ, data))

    def recv_frame(self):
        while True:
            i = self.buf.find(b'\xa5\x5a')
            if i >= 0 and len(self.buf) >= i + 5:
                n = self.buf[i + 3] | (self.buf[i + 4] << 8)
                if len(self.buf) >= i + 5 + n:
                    typ, data = self.buf[i + 2], self.buf[i + 5:i + 5 + n]
                    self.buf = self.buf[i + 5 + n:]
                    body, crc = data[:-2], struct.unpack('<H', data[-2:])[0]      # todo quadro host->guest termina com soma de 16 bits
                    assert crc == sum(body) & 0xffff, 'soma do quadro invalida'
                    return typ, body
            self.buf += self.conn.recv(4096)


class V850Tests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='v850t')
        self.path = os.path.join(self.dir, 'u.sock')
        self.guest = FakeGuest(self.path)
        self.link = v850.V850Link(self.path, os.path.join(self.dir, 'v850.log'))
        self.link.start()
        self.guest.accept()

    def tearDown(self):
        self.link.stop()
        self.guest.srv.close()

    def wait(self, cond, t=3.0):
        end = time.time() + t
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_flowcontrol_reply(self):
        fc = bytes([0x10, 2, 0, 0, 1, 0, 26, 1, 1, 0])
        self.guest.send(v850.TX, ipc_msg(0, fc))
        typ, data = self.guest.recv_frame()
        self.assertEqual(typ, v850.RX)
        ln = (data[0] | (data[1] << 8)) >> 4
        self.assertEqual(data[2], 0)
        self.assertEqual(data[4:4 + ln], bytes([0x10, 2, 0, 0, 1, 0, 26, 0, 1, 0]))

    def test_watchdog_decode_and_stats(self):
        self.guest.send(v850.TX, ipc_msg(26, bytes([2, 1, 0x11, 0, 0x40, 0x1f, 0, 0])))
        reg = bytes([5, 1, 6, 0, 0x16, 0xe0, 0x0b, 0, 1, 0, 0, 0, 0xfc, 3, 0, 0]) + b'SignalHandler\x00'
        self.guest.send(v850.TX, ipc_msg(26, reg))
        for i in range(5):
            self.guest.send(v850.TX, ipc_msg(26, bytes([1, 0x9f, 0x10, 0]) + struct.pack('<I', i)))
        m = self.link.model
        self.assertTrue(self.wait(lambda: m.heartbeats == 5))
        snap = self.link.snapshot()
        self.assertEqual(snap['model']['watchdog']['cycle_ms'], 8000)
        self.assertIn('SignalHandler', snap['model']['watchdog']['probes'])
        self.assertEqual(snap['channels']['26']['from_guest'], 7)
        self.assertTrue(snap['recent'])

    def test_garbage_and_split_frames(self):
        data = frame(v850.TX, ipc_msg(26, bytes([1, 0, 0, 0, 7, 0, 0, 0])))
        self.guest.conn.sendall(b'\x00\xa5\x11' + data[:3])
        time.sleep(0.1)
        self.guest.conn.sendall(data[3:])
        self.assertTrue(self.wait(lambda: self.link.model.heartbeats == 1))

    def test_send_header(self):
        self.link.send(25, b'\x01\x02\x03')
        typ, data = self.guest.recv_frame()
        self.assertEqual(typ, v850.RX)
        self.assertEqual(data[0] | (data[1] << 8), (3 << 4) | 0)
        self.assertEqual(data[2], 25)
        self.assertEqual(data[4:], b'\x01\x02\x03')
        self.link.send(25, b'x')
        _, d2 = self.guest.recv_frame()
        self.assertEqual(d2[0] & 15, 1)
        self.assertNotEqual(data[3] & 0x80, d2[3] & 0x80)       # bit 7 alterna a cada mensagem

    def test_tcp_bridge(self):
        """Pontes TCP do guest: abrir/dados/fechar por conexão; porta 5555 = SIPC, 5556 = DSI."""
        self.guest.send(v850.SIPC_OPEN, bytes([0, 0x15, 0xb3]))
        self.guest.send(v850.SIPC_OPEN, bytes([1, 0x15, 0xb4]))
        self.assertTrue(self.wait(lambda: self.link.sipc.connected and self.link.dsi.connected))
        self.guest.send(v850.SIPC_DATA, bytes([0]) + b'\x04\x00\x00\x00abcd')
        self.guest.send(v850.SIPC_DATA, bytes([1]) + b'xyz')
        self.assertTrue(self.wait(lambda: self.link.sipc.stats['bytes_from_guest'] == 8 and self.link.dsi.stats['bytes_from_guest'] == 3))
        self.link.sipc.send(b'\x01\x02')
        typ, data = self.guest.recv_frame()
        self.assertEqual((typ, data), (v850.SIPC_OUT, b'\x00\x01\x02'))
        self.link.dsi.send(b'Q')
        typ, data = self.guest.recv_frame()
        self.assertEqual((typ, data), (v850.SIPC_OUT, b'\x01Q'))
        self.guest.send(v850.SIPC_CLOSE, bytes([0]))
        self.assertTrue(self.wait(lambda: not self.link.sipc.connected))
        self.assertTrue(self.link.dsi.connected)

    def test_servicebroker_commands(self):
        self.link.sb_list()
        self.assertEqual(self.guest.recv_frame(), (v850.SB_LIST, b''))
        self.link.sb_register('MOSTSubSystemServer.DSYSMOSTServer', 5556, 1, 2, 0)
        typ, data = self.guest.recv_frame()
        self.assertEqual(typ, v850.SB_REGISTER)
        self.assertEqual(data[:10], bytes([0x15, 0xb4, 0, 1, 0, 2, 0, 0, 0, 0]))
        self.assertTrue(data.endswith(b'DSYSMOSTServer\x00'))

    def _bridge_hdr(self, msgid, payload=b'', total=None):
        h = bytearray(20)
        h[0] = 1
        struct.pack_into('<H', h, 2, 0x04f1); h[4], h[5] = 4, 5
        struct.pack_into('<H', h, 6, msgid)
        struct.pack_into('<H', h, 8, total if total is not None else 20 + len(payload))
        struct.pack_into('<H', h, 0x10, 0xffff)
        return bytes(h) + payload

    def _recv_bridge(self):
        typ, data = self.guest.recv_frame()
        self.assertEqual(typ, v850.RX)
        self.assertEqual(data[2], 25)
        n = (data[0] | (data[1] << 8)) >> 4
        return data[4:4 + n]

    def test_bridge_bringup_and_notification_ack(self):
        """Ponte DSI do canal 25: hello -> registerMOSTClient -> controlador + FBlocks -> ack de Notification."""
        from idemu import most
        self.guest.send(v850.TX, ipc_msg(25, self._bridge_hdr(0, b'', total=0)))
        m = self._recv_bridge()
        self.assertEqual((m[6] | (m[7] << 8)), 5)                                   # registerMOSTClient
        self.guest.send(v850.TX, ipc_msg(25, self._bridge_hdr(0x8000, struct.pack('<IH', 7, 0x2007))))
        m = self._recv_bridge()
        self.assertEqual((m[6] | (m[7] << 8)), 3)                                   # RegisterDevCtrls
        self.assertEqual(m[20:], struct.pack('<IHIH', 7, 0, 1, 0x0200))
        m = self._recv_bridge()
        self.assertEqual((m[6] | (m[7] << 8)), 2)                                   # RegisterDevices
        self.assertEqual(struct.unpack_from('<IHI', m, 20), (7, 0, len(most.MostBridge.CORE_DEVICES) + len(most.MostBridge.NAV_DEVICES)))
        notif = most.MostMessage(0x2007, 0x2001, 0x40, 1, 1, most.MostMessage.OP_SET, bytes([1, 0x20, 0x01, 0x0c, 0x2b]))
        self.guest.send(v850.TX, ipc_msg(25, self._bridge_hdr(0x8001, struct.pack('<I', 0) + notif.pack())))
        m = self._recv_bridge()
        self.assertEqual((m[6] | (m[7] << 8)), 4)                                   # requestProcessMessage (Status)
        r = most.MostMessage.parse(m, 24)
        self.assertEqual((r.dst, r.src, r.fblock, r.func, r.op), (0x2001, 0x2007, 0x40, 1, most.MostMessage.OP_STATUS))
        self.assertEqual(self.link.bridge.subs[(0x40, 1)], {0x0c2b: 0x2001})
        self.assertEqual(self.link.bridge.publish(0x40, 0x0c2b, b'\x05'), 1)

    def test_most_message_codec(self):
        from idemu import most
        raw = bytes.fromhex('020000000000000002200120440101000001000000050000000120010d4e')
        m = most.MostMessage.parse(b'\0\0\0\0' + raw, 4)
        self.assertEqual((m.dst, m.src, m.fblock, m.inst, m.func, m.op, m.data.hex()), (0x2002, 0x2001, 0x44, 1, 1, 0, '0120010d4e'))
        self.assertEqual(m.pack(), raw)

    def test_most_tx_queue_coalesces_status(self):
        from idemu import most
        class Link(object):
            def __init__(self):
                self.sent = []
                self.gate = threading.Event()
            def log(self, *a): pass
            def send(self, chan, frame):
                self.gate.wait(2)
                self.sent.append(frame)
        link = Link()
        b = most.MostBridge(link)
        b.subs[(0xCD, 3)] = {0x20b: 0x100}
        os.environ['IDEMU_MOST_RATE'] = '1000'
        try:
            for i in range(50):
                b.publish(0xCD, 0x20b, bytes((i,)), 3)
            time.sleep(0.05)
            link.gate.set()
            deadline = time.time() + 2
            while (b._pending or len(link.sent) < 2) and time.time() < deadline:
                time.sleep(0.01)
        finally:
            del os.environ['IDEMU_MOST_RATE']
        self.assertLess(len(link.sent), 5)                # 50 Status viraram no máximo o que estava em voo + o mais recente
        self.assertEqual(link.sent[-1][-1], 49)

    def test_notification_retry_without_value_is_not_acked_every_time(self):
        from idemu import most
        class Link(object):
            def log(self, *a): pass
            def send(self, chan, frame): pass
        b = most.MostBridge(Link())
        sent = []
        b.send_most = sent.append
        notif = most.MostMessage(0x100, 0x200, 0x52, 0, 1, most.MostMessage.OP_SET, bytes((1, 1, 0, 0x0C, 0xEC)))
        for _ in range(5):
            b.on_most(notif)
        self.assertEqual(len(sent), 1)                    # 0x52/0:0xCEC não tem valor: só o primeiro ack
        b._acked[(0x52, 0, 0xCEC)] -= most.MostBridge.RETRY_ACK_S
        b.on_most(notif)
        self.assertEqual(len(sent), 2)

    def test_nav_position_payload_layout(self):
        from idemu import most
        class Gps(object):
            def state(self):
                return {'fix': True, 'lat': -23.5505, 'lon': -46.6333, 'alt': 760.0, 'heading': 90.0, 'speed_kmh': 50.0, 'sats': 9, 'hdop': 0.9}
        car = most.MostCar(None)
        car.gps = Gps()
        d = car.status_for(0xCD, 3, 0x20b)
        self.assertEqual(len(d), 15)                      # seletor u8 (0 = todos os campos) | u8 == 0 | u16 | s32 lat | s32 lon | u8 | s16
        self.assertEqual(d[:2], b'\0\0')
        self.assertEqual(struct.unpack_from('>ii', d, 4), (round(-23.5505 / most.MostCar.LATLON_LSB), round(-46.6333 / most.MostCar.LATLON_LSB)))
        self.assertEqual(d[12], 64)                       # rumo 90 graus em 360/256
        self.assertEqual(struct.unpack('>II', car.status_for(0xCD, 3, 0x202)), (0x80000000 + round(-46.6333 * 3600000), 0x80000000 + round(-23.5505 * 3600000)))
        self.assertEqual(car.status_for(0xCD, 3, 0x203)[0], 64)
        self.assertEqual(car.status_for(0x52, 0, 0x23c), b'\x02')

    def test_car_feed_average_payload(self):
        """Dados do carro: Status de CBordcomputerAverage (0x509) com velocidade/consumo médios do CAN virtual."""
        from idemu import most
        class FakeCan(object):
            vals = {'vehicle_speed': 80.0, 'fuel_consumption': 7.5}
            def get_signal(self, n): return self.vals.get(n)
        car = self.link.bridge.car
        car.can = FakeCan()
        car.avg_speed, car.avg_cons = 33.3, 55.5
        data = car.status_for(0xE0, 0, 0x509)
        self.assertEqual(data, struct.pack('>HHHHHBB', 0, 333, 333, 555, 555, 1, 1))
        self.assertIsNone(car.status_for(0xE0, 0, 0x777))
        self.link.bridge.subs[(0xE0, 0)] = {0x509: 0x2000}
        self.link.bridge.device_id = 0x2001
        self.assertEqual(car.publish_all(), 1)
        m = most.MostMessage.parse(self._recv_bridge(), 24)
        self.assertEqual((m.dst, m.src, m.fblock, m.inst, m.func, m.op, m.data), (0x2000, 0x2001, 0xE0, 0, 0x509, most.MostMessage.OP_STATUS, data))
        self.assertEqual(car.publish_all(), 0)                     # nada mudou: não reenvia
        car.avg_speed = 40.0
        self.assertEqual(car.publish_all(), 1)                     # mudou: reenvia

    def test_car_feed_vehicle_payloads(self):
        """Vehicle (0x05/0): pneus, câmbio, marcha à ré, velocidade e terminal vindos do CAN virtual."""
        class FakeCan(object):
            vals = {'vehicle_speed': 50.0, 'gear_position': 1, 'terminal_state': 69, 'key_present': 1,
                    'tire_pressure_fl': 2.4, 'tire_pressure_fr': 2.5, 'tire_pressure_rl': 2.6, 'tire_pressure_rr': 2.7}
            def get_signal(self, n): return self.vals.get(n)
        car = self.link.bridge.car
        car.can = FakeCan()
        self.assertEqual(car.status_for(0x05, 0, 0x621), struct.pack('>H', 5000))
        self.assertEqual(car.status_for(0x05, 0, 0x228), b'\x01')
        self.assertEqual(car.status_for(0x05, 0, 0x22c), b'\x01')
        self.assertEqual(car.status_for(0x05, 0, 0x21f), bytes((12, 1, 0)))     # 1o byte 6..13 = estado do terminal lido pelo CDevCarClamp (12 = KL 15)
        self.assertTrue(all(b <= 15 for b in car.status_for(0x05, 0, 0x21f)))     # o HMI rejeita > 15
        self.assertEqual(car.status_for(0x05, 0, 0x224), struct.pack('>HBBBB', 1, 1, 1, 1, 1))
        self.assertEqual(car.status_for(0x05, 0, 0xc02), struct.pack('>HHHH', 240, 250, 260, 270))
        FakeCan.vals['gear_position'] = 3
        self.assertEqual(car.status_for(0x05, 0, 0x22c), b'\x00')
        self.assertIsNone(car.status_for(0x05, 0, 0x777))
        self.assertEqual(car.status_for(0x05, 0, 0xc01), bytes((0, 0, 0xa0, 0, 0)))   # b2 = codigo de RDC ativo (CDevCarTpmStatusImpl)
        self.assertIsNone(car.status_for(0xE0, 0, 0x200))        # evento: um payload aceito pelo HMI viraria uma mensagem CC falsa (derruba o HMI)
        self.assertIsNone(car.status_for(0xE0, 0, 0x303))
        self.assertEqual(car.status_for(0xD1, 2, 0xc10), bytes((0, 0, 0, 0x10)))   # chave no carro (bKeyInCar=1 no HMI)
        FakeCan.vals['key_present'] = 0
        self.assertEqual(car.status_for(0xD1, 2, 0xc10), bytes(4))
        FakeCan.vals['key_present'] = 1

    def test_car_feed_sport_displays(self):
        """Vehicle 0xC7B/0xC7A (exibição esportiva): torque/potência em % (<= 100) e códigos de fundo de escala."""
        class FakeCan(object):
            vals = {'engine_torque_pct': 73.4, 'engine_power_pct': 150, 'sport_torque_scale': 9, 'sport_power_scale': 5}
            def get_signal(self, n): return self.vals.get(n)
        car = self.link.bridge.car
        car.can = FakeCan()
        self.assertEqual(car.status_for(0x05, 0, 0xc7b), bytes((73, 100)))       # > 100 seria inválido no HMI: limitado
        self.assertEqual(car.status_for(0x05, 0, 0xc7a), struct.pack('>BBBBHH', 9, 5, 0, 0, 0, 0))
        car.can = None                                                           # sem CAN: barras em 0, escalas padrão
        self.assertEqual(car.status_for(0x05, 0, 0xc7b), bytes((0, 0)))
        self.assertEqual(car.status_for(0x05, 0, 0xc7a)[:2], bytes((9, 5)))


class SnapshotState(unittest.TestCase):
    """O que o boot rápido guarda do V850 virtual: depois de restaurar, o enlace continua sem repetir o registro no `most`."""
    def test_export_import_roundtrip(self):
        a = v850.V850Link('/nao/existe')
        a.seq, a.tog = 7, 1
        a.conns = {1: 5555}
        a.sipc.conns = {1: bytearray()}
        a._rxbuf = b'\xa5\x5a\x01'
        a.model.heartbeats = 9
        br = a.bridge
        br.hello = {'id': 1}
        br.CLIENT, br.device_id = 3, 0x2345
        br.subs = {(0x52, 0): {0x23c: 0x2002}}
        br.car._sent = {(0x52, 0, 0x23c): b'\x02'}
        br._acked = {(0x52, 0, 0x237): 1.0}
        br.car.avg_cons = 7.5
        import json
        state = json.loads(json.dumps(a.export_state()))          # precisa ser JSON puro
        b = v850.V850Link('/nao/existe')
        b.import_state(state)
        self.assertEqual((b.seq, b.tog, b.conns, b._rxbuf), (7, 1, {1: 5555}, b'\xa5\x5a\x01'))
        self.assertEqual(sorted(b.sipc.conns), [1])
        self.assertEqual(b.model.heartbeats, 9)
        bb = b.bridge
        self.assertIsNotNone(bb.hello)
        self.assertEqual((bb.CLIENT, bb.device_id, bb.subs, bb.car._sent), (3, 0x2345, {(0x52, 0): {0x23c: 0x2002}}, {(0x52, 0, 0x23c): b'\x02'}))
        self.assertIn((0x52, 0, 0x237), bb._acked)
        self.assertEqual(bb.car.avg_cons, 7.5)

    def test_hold_stops_the_pump_and_keeps_frames(self):
        sent = []
        link = v850.V850Link('/nao/existe')
        link.send = lambda chan, frame, flags=0: sent.append(frame)
        br = link.bridge
        br.hold(True)
        br._enqueue(b'um')
        br._enqueue(b'dois')
        time.sleep(0.3)
        self.assertEqual(sent, [])
        self.assertEqual(br.export_state()['pending'], [b'um'.hex(), b'dois'.hex()])
        br.hold(False)
        end = time.time() + 2
        while len(sent) < 2 and time.time() < end:
            time.sleep(0.02)
        self.assertEqual(sent, [b'um', b'dois'])


if __name__ == '__main__':
    unittest.main()

"""V850 virtual — o microcontrolador de energia/CAN da head unit, visto pelo io-ipc.

O guest roda o io-ipc e o decodificador "hp" ORIGINAIS do SWFL; só o transporte (SPI+DMA no hardware real)
foi trocado por `ioipc-idemu.so`, que leva os quadros por uma UART virtual até aqui.  Esta classe é a ponta
oposta: recebe as mensagens já codificadas pelo io-ipc, entrega aos "serviços" do V850 emulado e devolve as
respostas no mesmo formato.

Formato da mensagem io-ipc (decodificador hp, sem CRC):
    byte0-1  LE16: bits 0..3 = nº de sequência, bits 4..15 = tamanho do payload
    byte2    canal lógico
    byte3    flags (bit7 alterna a cada mensagem, 0x40 = cabeçalho de 8 bytes c/ CRC, 0x20 = segmentada)
    payload

Quadro na UART (ver src/v850/ioipc_idemu.c):  A5 5A <tipo> <len:2> <dados>
"""
import collections
import os
import socket
import struct
import threading
import time

HELLO, TX, RX, DEBUG = 0, 1, 2, 0x10
SIPC_OPEN, SIPC_DATA, SIPC_OUT, SIPC_CLOSE = 0x20, 0x21, 0x22, 0x23    # pontes TCP do guest (ver idemu/most.py)
SB_LIST, SB_REGISTER = 0x24, 0x25                                      # servicebroker do guest (DSI)


class V850Link(object):
    LOG_MAX = 16 << 20

    def __init__(self, uart_sock, log_path=None, model=None):
        self.uart_sock = uart_sock
        self.log_path = log_path
        self.model = model or V850Model(self)
        self.sock = None
        self.alive = False
        self.t0 = time.time()
        self.seq = 0
        self.tog = 0
        self.lock = threading.Lock()
        self.txlock = threading.Lock()                   # numeração das mensagens io-ipc (seq/bit alternante)
        self.stats = {'rx_msgs': 0, 'tx_msgs': 0, 'bytes_from_guest': 0, 'connected': False}
        self.traffic = collections.deque(maxlen=300)     # últimas mensagens (para a interface / depuração)
        self.chan = {}                                   # canal -> {'from_guest': n, 'to_guest': n}
        self._logf = open(log_path, 'w', buffering=1) if log_path else None
        self._log_bytes = 0
        self._rxbuf = b''
        from . import most
        self.sipc = most.MostSipc(self)
        self.dsi = most.MostDsi(self)
        self.bridge = most.MostBridge(self)
        self.conns = {}                                  # conn -> porta do guest (5555 SIPC, 5556 DSI)

    # --- log --------------------------------------------------------------
    def log(self, txt):
        line = '%8.2f %s' % (time.time() - self.t0, txt)
        if self._logf:
            self._logf.write(line + '\n')
            self._log_bytes += len(line) + 1
            if self._log_bytes > self.LOG_MAX:          # o log chegava a centenas de MB: guarda só o trecho mais recente
                self._logf.close()
                try:
                    os.replace(self.log_path, self.log_path + '.1')
                except OSError:
                    pass
                self._logf = open(self.log_path, 'w', buffering=1)
                self._log_bytes = 0

    def note(self, direction, chan, payload, quiet=False):
        c = self.chan.setdefault(chan, {'from_guest': 0, 'to_guest': 0})
        c[direction] += 1
        self.traffic.append({'t': round(time.time() - self.t0, 2), 'dir': direction, 'chan': chan, 'len': len(payload),
                             'hex': bytes(payload[:48]).hex()})
        if not quiet:
            self.log('%s canal %d: %s' % ('<-' if direction == 'from_guest' else '->', chan, bytes(payload[:80]).hex()))

    def snapshot(self):
        """Estado para a API/interface."""
        d = dict(self.stats)
        d['channels'] = {str(k): dict(v) for k, v in sorted(self.chan.items())}
        d['model'] = self.model.snapshot() if hasattr(self.model, 'snapshot') else {}
        d['recent'] = list(self.traffic)[-40:]
        d['sipc'] = self.sipc.snapshot()
        d['dsi'] = self.dsi.snapshot()
        d['bridge'] = self.bridge.snapshot()
        d['firmware'] = _firmware_summary()
        return d

    # --- snapshot (boot rápido) ----------------------------------------------
    def export_state(self):
        """O que o guest assume que o V850 lembra: numeração das mensagens, conexões tuneladas e tudo que o `most` já registrou."""
        return {'seq': self.seq, 'tog': self.tog, 'conns': {str(k): v for k, v in self.conns.items()}, 'rxbuf': self._rxbuf.hex(),
                'sipc': sorted(self.sipc.conns), 'dsi': sorted(self.dsi.conns),
                'model': {'heartbeats': self.model.heartbeats, 'wd_cycle_ms': self.model.wd_cycle_ms, 'wd_probes': self.model.wd_probes},
                'bridge': self.bridge.export_state()}

    def import_state(self, d):
        self.seq, self.tog = d['seq'], d['tog']
        self.conns = {int(k): v for k, v in d['conns'].items()}
        self._rxbuf = bytes.fromhex(d.get('rxbuf', ''))
        self.sipc.conns = {c: bytearray() for c in d['sipc']}
        self.dsi.conns = {c: bytearray() for c in d['dsi']}
        m = d['model']
        self.model.heartbeats, self.model.wd_cycle_ms, self.model.wd_probes = m['heartbeats'], m['wd_cycle_ms'], m['wd_probes']
        self.bridge.import_state(d['bridge'])

    # --- ciclo de vida -----------------------------------------------------
    def start(self):
        self.alive = True
        threading.Thread(target=self._run, daemon=True, name='v850-link').start()

    def stop(self):
        self.alive = False
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

    def _connect(self):
        t_end = time.time() + 120
        while self.alive and time.time() < t_end:
            s = socket.socket(socket.AF_INET if isinstance(self.uart_sock, tuple) else socket.AF_UNIX)
            try:
                if isinstance(self.uart_sock, tuple):
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.connect(self.uart_sock)
                return s
            except OSError:
                s.close()
                time.sleep(0.5)
        return None

    def _run(self):
        self.sock = self._connect()
        if not self.sock:
            self.log('sem conexão com a UART do V850')
            return
        self.stats['connected'] = True
        buf = self._rxbuf
        while self.alive:
            try:
                d = self.sock.recv(4096)
            except Exception:
                break
            if not d:
                break
            self.stats['bytes_from_guest'] += len(d)
            buf += d
            while True:
                i = buf.find(b'\xa5\x5a')
                if i < 0:
                    buf = buf[-1:] if buf.endswith(b'\xa5') else b''
                    break
                if len(buf) < i + 5:
                    buf = buf[i:]
                    break
                typ = buf[i + 2]
                n = buf[i + 3] | (buf[i + 4] << 8)
                if len(buf) < i + 5 + n:
                    buf = buf[i:]
                    break
                payload = buf[i + 5:i + 5 + n]
                buf = buf[i + 5 + n:]
                try:
                    self._frame(typ, payload)
                except Exception as e:  # nunca derrubar o enlace por causa do modelo
                    self.log('ERRO no modelo: %r' % (e,))
            self._rxbuf = buf
        self.stats['connected'] = False

    # --- quadros ------------------------------------------------------------
    def _frame(self, typ, p):
        if typ == DEBUG:
            self.log('guest: ' + p.decode('latin1', 'replace'))
            if b'escutando 127.0.0.1:5556' in p:          # a ponte DSI subiu: publica o papel no servicebroker antes do `most` procurá-lo
                self.dsi.register()
        elif typ == HELLO:
            self.log('hello: tchannel %d bytes' % len(p))
            self.model.on_hello(p)
        elif typ == SIPC_OPEN and len(p) >= 3:
            self.conns[p[0]] = (p[1] << 8) | p[2]
            self._peer(p[0]).on_open(p[0])
        elif typ == SIPC_DATA and len(p) >= 1:
            self._peer(p[0]).on_data(p[0], p[1:])
        elif typ == SIPC_CLOSE and len(p) >= 1:
            self._peer(p[0]).on_close(p[0])
            self.conns.pop(p[0], None)
        elif typ == TX:
            self.stats['tx_msgs'] += 1
            if len(p) < 4:
                self.log('TX curto: %s' % p.hex())
                return
            h = p[0] | (p[1] << 8)
            ln, seq, chan, fl = h >> 4, h & 15, p[2], p[3]
            hl = 8 if fl & 0x40 else 4
            self.model.on_message(chan, p[hl:hl + ln], fl, seq)

    def _write(self, typ, data):
        # soma de 16 bits no fim de todo quadro host->guest: o UART do guest perde bytes sob carga (um quadro chegava truncado, com o cabecalho do quadro seguinte
        # no meio, e o lixo ia parar no `most`, que abortava com ASSERTION em CHBByteStream.cpp:180); o guest confere, descarta e ressincroniza.
        data = bytes(data); data += struct.pack('<H', sum(data) & 0xffff)
        h = b'\xa5\x5a' + bytes([typ]) + struct.pack('<H', len(data))
        with self.lock:
            try:
                self.sock.sendall(h + data)
            except Exception as e:
                self.log('falha ao escrever: %r' % (e,))

    def _peer(self, conn):
        return self.dsi if self.conns.get(conn) == 5556 else self.sipc

    def conn_write(self, conn, data):
        """Bytes para uma conexão TCP aceita no guest."""
        data = bytes(data)
        for i in range(0, len(data), 0x800):
            self._write(SIPC_OUT, bytes([conn]) + data[i:i + 0x800])

    def conn_close(self, conn):
        self._write(SIPC_CLOSE, bytes([conn]))

    def sb_list(self):
        self._write(SB_LIST, b'')

    def sb_register(self, name, port, major, minor, a=0):
        """Registra a interface TCP `name` no servicebroker do guest (SBRegisterInterfaceTCP)."""
        self._write(SB_REGISTER, struct.pack('>HHHI', port, major, minor, a) + name.encode() + b'\0')

    def send(self, chan, payload, flags=0):
        """Envia uma mensagem io-ipc ao guest (canal lógico `chan`)."""
        payload = bytes(payload)
        # numeração (seq/bit alternante) E escrita no mesmo lock: senão duas threads (envio MOST + respostas de outros canais) podem gravar fora da ordem
        # em que receberam o número e o io-ipc do guest vê quadros fora de sequência (o `most` morria de forma aleatória ~1 min depois do boot).
        with self.txlock:
            hdr = struct.pack('<H', (len(payload) << 4) | (self.seq & 15)) + bytes([chan, (self.tog << 7) | flags])
            self.seq = (self.seq + 1) & 15
            self.tog ^= 1
            self.stats['rx_msgs'] += 1
            self.note('to_guest', chan, payload)
            self._write(RX, hdr + payload)


_FW = []


def _firmware_summary():
    """Identificação do firmware real do IOC (V850/RH850) que a PSdZData traz: lida uma vez de idemu/data/v850_firmware.json."""
    if not _FW:
        from . import v850fw
        _FW.append(v850fw.summary())
    return _FW[0]


class V850Model(object):
    """Comportamento do V850 emulado, canal a canal (numeração do io-ipc em modo O5, como no starter.cfg):
       0  controle de fluxo do io-ipc           (tratado aqui)
       1  watchdog do próprio io-ipc            (sem uso observado)
       5  interface `ipc5` do dev-spi (variante do starter.cfg com o bit 25 do VariantCode zerado; canais 1..20 do `ipc-plugin.so`) — não usada aqui
       7  dev-navsens (sensores brutos)          (o cliente usa /dev/ipc/ipc7; não roda no IDEmu)
       25 ponte MOST/DSI do subsistema `most`   (modelado: MostBridge)
       26 watchdog5-omap / CSI_NBT              (config 0x02, registro 0x05, batimento 0x01)
       27 touchComDevice                         (/dev/ipc/ipc27, "test DSI communication to V850"; o firmware tem `IpcTouch_O5`; não modelado)
       28 —                                      (sem cliente conhecido)
    Os nomes de canal do firmware real (IpcSGW, IpcDGW, IpcOnOff, IpcAmpControl...) estão em docs/V850_FIRMWARE.md; a correspondência
    nome <-> número só foi confirmada para os acima (o firmware registra os nomes numa tabela sem os números).
    """

    WD_NAMES = {0x01: 'heartbeat', 0x02: 'config', 0x05: 'register'}

    def __init__(self, link):
        self.link = link
        self.heartbeats = 0
        self.wd_cycle_ms = None
        self.wd_probes = []

    def snapshot(self):
        return {'watchdog': {'heartbeats': self.heartbeats, 'cycle_ms': self.wd_cycle_ms, 'probes': self.wd_probes[-8:]}}

    def on_hello(self, tchannel_bytes):
        pass

    def on_message(self, chan, payload, flags, seq):
        lk = self.link
        if chan == 0 and payload[:1] == b'\x10':
            lk.note('from_guest', 0, payload, quiet=True)
            # controle de fluxo do io-ipc: [0x10][n][ {canal, créditos, flag, 0} * n ]  (flag 1 = pode enviar)
            n = payload[1]
            ents = [payload[2 + 4 * i:6 + 4 * i] for i in range(n)]
            lk.send(0, bytes([0x10, n]) + b''.join(bytes([e[0], 0, 1, 0]) for e in ents if len(e) == 4))
            return
        if chan == 25:
            lk.bridge.on_message(payload)
            lk.note('from_guest', chan, payload, quiet=True)
            return
        if chan == 26 and payload[:1] == b'\x01':      # batimento do watchdog (~2,5 Hz): só conta
            self.heartbeats += 1
            lk.note('from_guest', chan, payload, quiet=self.heartbeats > 3)
            return
        if chan == 26 and payload[:1] == b'\x02' and len(payload) >= 8:
            self.wd_cycle_ms = payload[4] | (payload[5] << 8)
        if chan == 26 and payload[:1] == b'\x05':
            self.wd_probes.append(payload[16:].split(b'\x00')[0].decode('latin1', 'replace'))
        lk.note('from_guest', chan, payload)


def main(argv):
    """Modo de desenvolvimento: roda só o V850 virtual, reconectando à UART do QEMU sem precisar reiniciar o guest.
       python3 -m idemu.v850 <ser4.sock> [log]
       Comandos na entrada padrão:  list | m25 <id> [hex] | reg <nome> <porta> <maior> <menor> [a] | close <conn> | send <conn> <hex> | quit"""
    import sys
    sock = argv[0]
    log = argv[1] if len(argv) > 1 else None
    link = V850Link(sock, log)
    link.start()
    sigs = {'vehicle_speed': 0.0, 'fuel_consumption': 7.5}
    if os.environ.get('IDEMU_DEV_CAR'):               # dados do carro de teste (sem CAN real): `sig <nome> <valor>` altera
        class _Can(object):
            def get_signal(self, n): return sigs.get(n)
        link.bridge.car.attach_can(_Can())
    print('V850 virtual em', sock, flush=True)
    try:
        for line in sys.stdin:
            w = line.split()
            if not w:
                continue
            if w[0] == 'list':
                link.sb_list()
            elif w[0] == 'reg' and len(w) >= 5:
                link.sb_register(w[1], int(w[2]), int(w[3]), int(w[4]), int(w[5]) if len(w) > 5 else 0)
            elif w[0] == 'm25' and len(w) >= 2:                  # m25 <id-hex> [payload-hex]  (mensagem na ponte DSI do canal 25)
                link.bridge.send(int(w[1], 16), bytes.fromhex(''.join(w[2:])))
            elif w[0] == 'dev' and len(w) >= 2:                   # dev <fb-hex>:<inst-dec> ...  (registra dispositivos MOST)
                link.bridge.register_devices([(int(x.split(':')[0], 16), int(x.split(':')[1])) for x in w[1:]])
            elif w[0] == 'pub' and len(w) >= 4:                   # pub <fb-hex>:<inst> <fkt-hex> <dados-hex>  (Status de uma propriedade)
                fb, inst = w[1].split(':')
                print('pub ->', link.bridge.publish(int(fb, 16), int(w[2], 16), bytes.fromhex(''.join(w[3:])), int(inst)), flush=True)
            elif w[0] == 'sig' and len(w) == 3:
                sigs[w[1]] = float(w[2])
            elif w[0] == 'subs':                                  # subs: assinaturas (Notification) recebidas por FBlock
                for k, v in sorted(link.bridge.subs.items()):
                    print('%02X:%d' % k, ' '.join('%03x' % f for f in sorted(v)), flush=True)
            elif w[0] == 'close':
                link.conn_close(int(w[1]))
            elif w[0] == 'send':
                link.conn_write(int(w[1]), bytes.fromhex(w[2]))
            elif w[0] == 'quit':
                break
    except KeyboardInterrupt:
        pass
    link.stop()


if __name__ == '__main__':
    import sys
    main(sys.argv[1:])

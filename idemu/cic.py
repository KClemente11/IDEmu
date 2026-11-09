"""iDrive 4 (CIC High, Harman "BMW L6", SH7785 + QNX 6.3.2) no IDEmu.

A imagem (IFS de boot com os patches, flash NOR de 128 MB com IFS2 e EFS_RO) é montada uma vez em <IDEmu>/cic a partir do pacote
swfl_000003a6 (e do 417) e é compartilhada entre os ambientes. O QEMU (placa `cic`, bin/qemu-system-sh4) grava a tela composta em
frame.rgb (CIC_FRAME) e recebe rotor/teclas por um socket (CIC_INPUT). Detalhes em docs/IDRIVE4.md.
"""
import glob, importlib.util, json, os, shutil, socket, subprocess, threading, time
from . import runtime
from .catalog import CIC_VERSION as VERSION, CIC_PACKAGES as PKGS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'cic')
QEMU = os.path.join(ROOT, 'bin', 'qemu-system-sh4')
DEV_QEMU = os.path.expanduser('~/id4-qemu/build/qemu-system-sh4')     # compilado por src/cic/build.sh
IMAGES = ('ifs.bin', 'flash.img', 'efs.ifs', 'build.json')


def _cicrun():
    """tools/cic/run.py como módulo (montagem das imagens e linha de comando do QEMU)."""
    spec = importlib.util.spec_from_file_location('cicrun', os.path.join(ROOT, 'tools', 'cic', 'run.py'))
    m = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'cic'))
    spec.loader.exec_module(m)
    return m


def find_pkg(psdz=None):
    """Caminho do swfl_000003a6 (o 417 tem de estar na mesma pasta): PSdZData configurada ou ~/Downloads/System files/ID4."""
    dirs = []
    if psdz:
        dirs += [os.path.join(psdz, 'swe', 'swfl'), os.path.join(psdz, 'psdzdata', 'swe', 'swfl'), psdz]
    dirs += [os.path.expanduser('~/Downloads/System files/ID4')]
    for d in dirs:
        ok = all(os.path.isfile(os.path.join(d, 'swfl_%s.bin.%s' % (p, VERSION))) for p in PKGS)
        if ok:
            return os.path.join(d, 'swfl_%s.bin.%s' % (PKGS[0], VERSION))
    return None


def image_ready():
    return all(os.path.isfile(os.path.join(OUT, n)) for n in IMAGES) and os.path.isfile(QEMU)


def build(psdz=None, log=print, progress=lambda p, s: None):
    pkg = find_pkg(psdz)
    if not pkg:
        raise RuntimeError('pacotes do iDrive 4 não encontrados (swfl_000003a6 e swfl_00000417 versão %s) na PSdZData nem em '
                           '~/Downloads/System files/ID4' % VERSION)
    os.makedirs(OUT, exist_ok=True)
    if os.path.isfile(DEV_QEMU) and (not os.path.isfile(QEMU) or os.path.getmtime(DEV_QEMU) > os.path.getmtime(QEMU)):
        shutil.copy2(DEV_QEMU, QEMU)
        log('QEMU atualizado a partir de %s' % DEV_QEMU)
    if not os.path.isfile(QEMU):
        raise RuntimeError('bin/qemu-system-sh4 não existe: rode src/cic/build.sh')
    progress(5, 'Lendo o pacote %s' % os.path.basename(pkg))
    old = {k: os.environ.get(k) for k in ('CIC_NOECURESET',)}
    os.environ['CIC_NOECURESET'] = '1'           # se o Root pedir reset ele segue vivo (o HMI não some da tela)
    steps = {'EFS_RO (FFS3 original + conteúdo do HD)': (10, 'Montando o EFS_RO (dados do HMI)'), 'IFS de boot': (70, 'Montando o IFS de boot'),
             'flash NOR de 128 MB': (85, 'Gravando a flash NOR')}
    def lg(s):
        log(s)
        if s in steps: progress(*steps[s])
    try:
        _cicrun().prepare(OUT, pkg, log=lg)
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    json.dump({'pkg': pkg, 'version': VERSION, 'built': time.time()}, open(os.path.join(OUT, 'build.json'), 'w'))
    progress(100, 'Pronto')


# marcos do boot no slog (ser0) -> (porcentagem, texto)
MARKS = [('Starting CicHighEceUsaRoot', 10, 'Iniciando o aplicativo principal (Root)'),
         ('Starting CicHighEceUsaSecond', 25, 'Montando o IFS2 e iniciando os serviços'),
         ('PApplicationWrapper::HMIApps', 45, 'Iniciando o HMI'),
         ('MtpHmi::Registration complete', 65, 'Carregando a interface'),
         ('PHMIWrapper::HMIReady', 90, 'Interface pronta')]


class CicRuntime(runtime.Runtime):
    kind = 'cic'; disp = (1280, 480)

    def __init__(self, env_dir, env):
        runtime.Runtime.__init__(self, env_dir, env)
        self.ctl = self.run; self._sock = None; self.zbe = None

    def snapshot_info(self): return {'valid': False, 'size': 0, 'enabled': False}
    def drop_snapshot(self): pass

    def start(self, cold=False):
        if self.state in ('booting', 'running'): return
        if os.path.isfile(DEV_QEMU) and (not os.path.isfile(QEMU) or os.path.getmtime(DEV_QEMU) > os.path.getmtime(QEMU)):
            shutil.copy2(DEV_QEMU, QEMU)               # QEMU recompilado por src/cic/build.sh
        if not image_ready(): raise RuntimeError('imagem do iDrive 4 não montada: compile o ambiente')
        import sys
        sys.path.insert(0, os.path.join(ROOT, 'tools', 'cic'))
        import hmiinput
        hmiinput.patch_flash_file(os.path.join(OUT, 'flash.img'))      # entrada do controlador (imagens montadas antes dela)
        if self.zbe: self.zbe.close(); self.zbe = None
        shutil.rmtree(self.run, ignore_errors=True); os.makedirs(self.run); os.makedirs(self.logd, exist_ok=True)
        # flash gravável desta execução (clone APFS, instantâneo): o snapshot=on gravava num qcow2 temporário e às vezes travava o QEMU
        # numa gravação da flash (vCPU parado em blk_pwrite)
        fl = os.path.join(self.run, 'flash.img')
        if subprocess.call(['cp', '-c', os.path.join(OUT, 'flash.img'), fl], stderr=subprocess.DEVNULL) != 0:
            shutil.copyfile(os.path.join(OUT, 'flash.img'), fl)
        self.state = 'booting'; self.err = None; self.t0 = time.time(); self.marks = {}; self.step = 'Iniciando o QEMU'; self.pct = 2
        self._fm = None; self._lastseq = None; self.fps_t = []; self.boot_kind = 'cold'; self.stop_ev.clear()
        threading.Thread(target=self._boot_thread, daemon=True).start()

    def _links(self):
        for name, target in (('console.log', 'ser1.log'), ('qemu.log', 'qemu.out'), ('renderer.log', 'ser0.txt')):
            p = os.path.join(self.logd, name)
            try:
                if os.path.lexists(p): os.unlink(p)
                os.symlink(os.path.join(self.run, target), p)
            except OSError:
                pass

    def _boot_thread(self):
        try:
            cmd = _cicrun().qemu_cmd(OUT, run=self.run, qemu=QEMU, debug_log='', flash=os.path.join(self.run, 'flash.img'))
            env = dict(os.environ, CIC_FRAME=self.frame_path, CIC_NORESET='1', CIC_INPUT=os.path.join(self.run, 'input.sock'),
                       CIC_OUTPUT=os.path.join(self.run, 'output.sock'))
            self.zbe = VirtualZBE(self.run, self.send_cmd)
            env.pop('CIC_DISPLAY', None)
            out = open(os.path.join(self.run, 'qemu.out'), 'wb')
            self.q = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env)
            self._links()
            slog = os.path.join(self.run, 'ser0.txt'); seen = set(); end = time.time() + 420
            while not self.stop_ev.is_set():
                if self.q.poll() is not None: raise RuntimeError('o QEMU terminou (%s); veja o log do QEMU' % self.q.returncode)
                if self.state == 'booting':
                    txt = b''
                    for fn in (slog, os.path.join(self.run, 'ser1.log')):
                        try:
                            with open(fn, 'rb') as f: txt += f.read()
                        except OSError:
                            pass
                    for key, pct, step in MARKS:
                        if key not in seen and key.encode() in txt:
                            seen.add(key); self.pct = pct; self.step = step; self._mark(key.split('::')[-1])
                    if 'PHMIWrapper::HMIReady' in seen and self.frame_seq() > 0:
                        self.state = 'running'; self.pct = 100; self.step = ''; self._mark('running')
                        self.zbe.register()                 # anuncia o controlador ao HMI (FBlock 0xE5)
                    elif time.time() > end:
                        raise RuntimeError('o HMI não ficou pronto em 7 minutos; veja os logs')
                    elif not seen:
                        self.step = 'Iniciando o QNX'; self.pct = min(9, 2 + int(time.time() - self.t0))
                else:
                    self.frame_seq()
                time.sleep(0.25)
        except Exception as e:
            if not self.stop_ev.is_set():
                self.err = str(e); self.state = 'error'; self._kill_children()

    def status(self):
        s = runtime.Runtime.status(self); s['kind'] = self.kind; s['disp'] = list(self.disp)
        return s

    # ---------- entrada: controlador iDrive virtual ----------
    def send_cmd(self, line):
        with self._cmd_lock:
            if self._sock is None:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                self._sock.sendto(line.encode(), os.path.join(self.run, 'input.sock'))
            except OSError:
                pass

    def key(self, code, val):
        if self.zbe: self.zbe.key(int(code), bool(val))
    def rotor(self, delta):
        if delta and self.zbe: self.zbe.rotate(int(delta))
    def touch(self, x, y, down, move=False):
        pass                                       # o CIC não tem tela de toque


class VirtualZBE:
    """Controlador iDrive (ZBE) virtual: fala com o HMI como o FBlock MOST CentralControlSystem (0xE5, instância 1 = ZGW_01).

    Os telegramas MTP vão para o QEMU (input.sock, "t <hex>") e o patch do HmiMain (tools/cic/hmiinput.py) os entrega como se viessem do
    Root; o que o HMI manda ao 0xE5 volta pelo output.sock ("x <hex>"). Formato do telegrama MOST: [0..1] tamanho, [2]=2, [3]=0, [4..5]
    endereço de origem, [6] FBlock, [7] instância, [8..9] FktID, [10] OpType (0x0C = Status), [11]=1, dados. Funções (docs/IDRIVE4.md):
      0xC10 RotaryEncoder        01 1D cnt pos_hi pos_lo 1E 00   (pos = posição absoluta; o HMI gira pela diferença)
      0xC20 PushButton           01 1D cnt estado dir campo bits (estado 1 = apertado, 0 = solto)
                                   campo 0x1E + bits 1 = aperto do controlador; campo 0x1D + dir (1 cima, 2 direita, 4 baixo, 8 esquerda) = inclinação;
                                   campo 0 + bits = teclas (1 MENU, 2 BACK, 4 OPTION, 8 RADIO, 16 CD, 32 NAV, 64 TEL)
      0xC30 RotaryEncoderConfig  01 1D nn 00 (resposta ao Set do HMI, nn = o contador que ele mandou; só então o rotor é aceito)
    cnt é o contador de mensagens do controlador (o HMI ignora repetição), comum a rotor e botões."""
    REGISTRY = '000c0701000100000102e501'          # registry changed: FBlock E5.01 no endereço 0x0102 (ZGW)
    # códigos de tecla do app -> (campo, dir, bits)
    KEYS = {1: (0, 0, 1), 2: (0, 0, 2), 3: (0, 0, 4), 4: (0, 0, 16), 5: (0, 0, 8), 6: (0, 0, 64), 7: (0, 0, 32), 8: (0x1e, 0, 1),
            9: (0x1d, 1, 0), 10: (0x1d, 4, 0), 11: (0x1d, 8, 0), 12: (0x1d, 2, 0)}

    def __init__(self, run_dir, send, log=lambda s: None):
        self.send_cmd = send; self.log = log; self.cnt = 0; self.pos = 0x1000; self.lock = threading.Lock()
        self.out = os.path.join(run_dir, 'output.sock'); self.registered = False; self.configured = False
        try: os.unlink(self.out)
        except OSError: pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM); self.sock.bind(self.out); self.sock.settimeout(0.5)
        self.stop = threading.Event()
        threading.Thread(target=self._rx, daemon=True).start()

    def close(self):
        self.stop.set()
        try: self.sock.close()
        except OSError: pass

    def _tel(self, fkt, data):
        b = bytes([0, 12 + len(data), 2, 0, 0x01, 0x02, 0xe5, 0x01, fkt >> 8, fkt & 0xff, 0x0c, 0x01]) + bytes(data)
        self.send_cmd('t ' + b.hex())

    def _next(self):
        self.cnt = (self.cnt + 1) & 0xff
        if self.cnt == 0xff: self.cnt = 0
        return self.cnt

    def register(self):
        if not self.registered:
            self.registered = True; self.send_cmd('t ' + self.REGISTRY)

    def _rx(self):
        while not self.stop.is_set():
            try:
                d = self.sock.recv(4096).decode(errors='ignore')
            except socket.timeout:
                continue
            except OSError:
                return
            if not d.startswith('x '): continue
            try: h = bytes.fromhex(d[2:].strip())
            except ValueError: continue
            if len(h) < 12: continue
            fkt, op, data = h[8] << 8 | h[9], h[10], h[12:]
            if fkt == 0x001 and op == 0 and len(data) >= 5:          # Notification.Set (controle, DeviceID, FktIDs): manda o status atual
                fkts = [data[i] << 8 | data[i + 1] for i in range(3, len(data) - 1, 2)]
                if 0xc10 in fkts:                                     # o 1º status do rotor faz o HMI mandar o RotaryEncoderConfig.Set
                    with self.lock:
                        self._tel(0xc10, [1, 0x1d, self._next(), self.pos >> 8, self.pos & 0xff, 0x1e, 0])
            if fkt == 0xc30 and op == 0 and len(data) >= 3:          # RotaryEncoderConfig.Set: confirma com o mesmo contador
                with self.lock:
                    self._tel(0xc30, [1, 0x1d, data[2], 0])
                    self._tel(0xc10, [1, 0x1d, self._next(), self.pos >> 8, self.pos & 0xff, 0x1e, 0])   # posição de referência
                if not self.configured: self.log('controlador iDrive configurado pelo HMI')
                self.configured = True

    def rotate(self, delta):
        with self.lock:
            for _ in range(min(abs(delta), 20)):       # um passo por mensagem (o HMI anda um item por diferença)
                self.pos = (self.pos + (1 if delta > 0 else -1)) & 0xffff
                self._tel(0xc10, [1, 0x1d, self._next(), self.pos >> 8, self.pos & 0xff, 0x1e, 0])

    def key(self, code, down):
        k = self.KEYS.get(code)
        if not k: return
        field, direction, bits = k
        with self.lock:
            self._tel(0xc20, [1, 0x1d, self._next(), 1 if down else 0, direction if down else 0, field, bits])

"""iDrive 8 (MGU22): monta a imagem a partir da PSdZData e roda QEMU `virt` + mguhost. Detalhes em docs/OUTRAS_GERACOES.md."""
import glob, json, mmap, os, shutil, socket, struct, subprocess, sys, threading, time, uuid
from pathlib import Path
if sys.platform != 'win32':
    import _posixshmem
from . import runtime, coding8
from .catalog import STATE_DIR, NATIVE_BIN
from .initramfs import validate_cpio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools', 'mgu')
OUT = os.path.join(STATE_DIR if sys.platform == 'win32' else ROOT, 'mgu22')
MB = 12288
USBFAKE = ('libusb-1.0.so.0', 'libudev.so.1')
GUEST_BASE = 0x40000000; INITRD_AT = 0x240000000
SHM = '/idemu_ram'
GUEST_FILES = ('libcod.so.0', 'coding.tab', 'libEGL.so.1', 'libGLESv2.so.2', 'idemuwl', 'idemuinput', 'idemuusb', 'libusb-1.0.so.0', 'libudev.so.1', 'libidemuhmi.so')
BUILD_STEPS = [('kernel e raiz', 10, 'Lendo o kernel e o sistema'), ('IVI e EXT', 25, 'Lendo o contêiner IVI com o HMI'), ('cpio', 55, 'Preparando os arquivos'),
               ('dados da marca', 75, 'Lendo os dados da marca e do carro'), ('juntando', 90, 'Juntando a imagem')]
_image_check_lock = threading.Lock()
_image_check = (None, False)

def image_ready():
    global _image_check
    if not (os.path.isfile(OUT + '/Image') and all(os.path.isfile(f'{OUT}/guest/{f}') for f in GUEST_FILES)):
        return False
    path = os.path.join(OUT, 'base.cpio')
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    except OSError: return False
    # Status polls reuse this result until the shared archive changes.
    with _image_check_lock:
        if _image_check[0] != key:
            try: validate_cpio(path, expected_archives=6); valid = True
            except (OSError, ValueError): valid = False
            _image_check = (key, valid)
        return _image_check[1]

def build(psdz=None, log=print, progress=lambda p, s: None):
    """Monta mgu22/ com tools/mgu/build_image.py. A imagem é compartilhada por todos os ambientes iDrive 8."""
    prefix = [sys.executable, '--run-tool'] if getattr(sys, 'frozen', False) else [sys.executable, '-u', '-I']
    cmd = prefix + [TOOLS + '/build_image.py'] + ([psdz] if psdz else []) + ['--output-dir', OUT]
    if sys.platform == 'win32':
        guest = os.path.join(ROOT, 'idemu', 'guest8')
        if not os.path.isdir(guest): guest = os.path.join(NATIVE_BIN, 'guest8')
        cmd += ['--guest-dir', guest] if os.path.isdir(guest) else ['--build-guest']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in p.stdout:
        line = line.rstrip(); log(line); tail = (tail + [line])[-5:]
        for key, pct, step in BUILD_STEPS:
            if line.startswith(key): progress(pct, step)
    if p.wait() != 0: raise RuntimeError('falha ao montar a imagem do iDrive 8: ' + ' / '.join(tail)[-300:])

def find_angle():
    env = os.environ.get('IDEMU_ANGLE')
    if sys.platform == 'win32':
        candidates = [env] if env else [NATIVE_BIN, os.path.join(NATIVE_BIN, 'angle')]
        if not env:
            for root in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
                if not root: continue
                candidates += [os.path.join(root, p) for p in (
                    'NVIDIA Corporation/NVIDIA App/CEF', 'LGHUB', 'Oculus/Support/oculus-client',
                    'Steam/bin/cef/cef.win64')]
        for directory in candidates:
            if directory and all(os.path.isfile(os.path.join(directory, n)) for n in ('libEGL.dll', 'libGLESv2.dll')):
                return os.path.abspath(directory)
        raise RuntimeError('Windows ANGLE not found. Set IDEMU_ANGLE to a folder containing x64 libEGL.dll and libGLESv2.dll.')
    if env: return env
    pats = ['/Applications/*/Contents/Frameworks/Chromium Embedded Framework.framework/Versions/A/Libraries',
            '/Applications/*/Contents/Frameworks/*Framework.framework/Versions/*/Libraries', '/Applications/*/Contents/Frameworks']
    for pat in pats:
        for d in sorted(glob.glob(pat)):
            if os.path.exists(d + '/libGLESv2.dylib') and os.path.exists(d + '/libEGL.dylib'):
                arch = subprocess.run(['lipo', '-archs', d + '/libGLESv2.dylib'], capture_output=True, text=True).stdout
                if 'arm64' in arch: return d
    raise RuntimeError('ANGLE não encontrado: instale um app baseado em Chromium ou defina IDEMU_ANGLE com a pasta de libEGL.dylib e libGLESv2.dylib')

def _cpio(items):
    out = bytearray()
    def ent(name, mode, data, ino):
        nm = name.encode() + b'\0'
        h = '070701' + ''.join('%08X' % v for v in (ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(nm), 0))
        b = h.encode() + nm; b += b'\0' * ((4 - len(b) % 4) % 4)
        out.extend(b); out.extend(data); out.extend(b'\0' * ((4 - len(data) % 4) % 4))
    for i, (n, m, d) in enumerate(items, 1): ent(n, m, d, i)
    ent('TRAILER!!!', 0, b'', len(items) + 1)
    return bytes(out)

def _prepare_ram(dtb_out, coding_tab=None, shm_name=SHM, check=None):
    """Cria a RAM do guest (objeto POSIX compartilhado) já com o initramfs dentro e grava a árvore de dispositivos."""
    items = [('idemu', 0o40755, b''), ('idemu.sh', 0o100755, Path(TOOLS, 'guest_boot.sh').read_bytes())]
    for f in GUEST_FILES:
        if f in USBFAKE: continue
        items.append(('idemu/' + f, 0o100755, coding_tab.encode() if f == 'coding.tab' and coding_tab else Path(OUT, 'guest', f).read_bytes()))   # coding.tab do ambiente (idemu/coding8.py)
    items.append(('idemu/usbfake', 0o40755, b''))   # libusb e libudev falsas, só para o devicemanager
    for f in USBFAKE: items.append(('idemu/usbfake/' + f, 0o100755, Path(OUT, 'guest', f).read_bytes()))
    ov = _cpio(items)
    pos = INITRD_AT - GUEST_BASE
    end_offset = ((pos + os.path.getsize(OUT + '/base.cpio') + 3) & ~3) + len(ov)
    d = Path(TOOLS, 'virt_mgu22.dtb').read_bytes()
    end = GUEST_BASE + end_offset
    ph = struct.pack('>II', 0xdeadbeef, 0xfeedf00d)
    if pos < 0 or end_offset > MB << 20 or ph not in d: raise RuntimeError('initramfs não cabe na RAM do guest')
    fd = None; m = None
    native = sys.platform == 'win32'
    try:
        if check: check()
        if native:
            m = mmap.mmap(-1, MB << 20, tagname=shm_name, access=mmap.ACCESS_WRITE)
        else:
            try: _posixshmem.shm_unlink(shm_name)
            except OSError: pass
            fd = _posixshmem.shm_open(shm_name, os.O_CREAT | os.O_RDWR | os.O_EXCL, 0o600)
            os.ftruncate(fd, MB << 20)
            m = mmap.mmap(fd, MB << 20, mmap.MAP_SHARED)
        with open(OUT + '/base.cpio', 'rb') as f:
            while True:
                if check: check()
                b = f.read(1 << 24)
                if not b: break
                m[pos:pos + len(b)] = b; pos += len(b)
        pos = (pos + 3) & ~3
        m[pos:pos + len(ov)] = ov
        Path(dtb_out).write_bytes(d.replace(ph, struct.pack('>II', end >> 32, end & 0xffffffff)))
        if native:
            result, m = m, None  # Keep it alive until QEMU and the renderer have exited.
            return result
    finally:
        if m is not None: m.close()
        if fd is not None: os.close(fd)


def windows_qemu_command(dtb, name, serial, args):
    return [os.path.join(NATIVE_BIN, 'qemu-system-aarch64.exe'),
            '-M', 'virt,gic-version=3,memory-backend=m0', '-accel', 'tcg,thread=multi',
            '-cpu', 'cortex-a76', '-m', str(MB), '-smp', '4', '-display', 'none', '-monitor', 'none', '-nic', 'none',
            '-serial', f'tcp:{serial[0]}:{serial[1]},server=on,wait=off,nodelay=on',
            '-object', f'memory-backend-idemu,id=m0,size={MB}M,mapping-name={name},share=on',
            '-dtb', dtb, '-kernel', os.path.join(OUT, 'Image'), '-append', args]

class MguRuntime(runtime.Runtime):
    kind = 'mgu22'; disp = (2880, 960)
    def __init__(self, env_dir, env, debug=False):
        runtime.Runtime.__init__(self, env_dir, env)
        self.debug = debug; self.ctl = self.run; self.console_in = os.path.join(self.run, 'console.in'); self._keep = None; self._sock = None
        self._ram = None; self._serial = None; self._serial_thread = None
        self._boot_worker = None
        self._shm_name = SHM; self._input_endpoint = None
    def start(self, cold=False):
        if self._boot_worker and self._boot_worker.is_alive():
            raise RuntimeError('The previous iDrive 8 boot is still active; stop it before restarting.')
        if not image_ready(): raise RuntimeError('imagem do iDrive 8 não montada')
        try: validate_cpio(os.path.join(OUT, 'base.cpio'), expected_archives=6)
        except ValueError as error:
            raise RuntimeError('The iDrive 8 image is incomplete or corrupted. Rebuild this environment before starting. ' + str(error)) from error
        for d in (self.run, self.logd): os.makedirs(d, exist_ok=True)
        for f in ('frame.rgb', 'input.sock', 'console.in'):
            try: os.unlink(os.path.join(self.run, f))
            except OSError: pass
        self._shm_name = 'Local\\IDEmu-MGU8-' + uuid.uuid4().hex if self.native else SHM
        self._exits = (0, 0, b''); self._png = (None, None); self.fps_t.clear()
        self._climate_set = False; self._t_clock = 0; self.state = 'booting'; self.err = None; self.t0 = time.time(); self.boot_kind = 'cold'; self.stop_ev.clear(); self.marks = {}; self._fm = None; self._lastseq = None
        self.step = 'Preparando a memória do sistema'; self.pct = 5
        self._boot_worker = threading.Thread(target=self._boot_thread, daemon=True)
        self._boot_worker.start()
    def stop(self):
        runtime.Runtime.stop(self)
        worker = self._boot_worker
        if worker and worker is not threading.current_thread(): worker.join(5)
    def _check_stopped(self):
        if self.stop_ev.is_set(): raise runtime.BootStopped()
    def _car_state(self):
        """Relógio e clima viriam de outras centrais: manda a hora do Mac e a temperatura inicial."""
        now = time.time()
        if now - getattr(self, '_t_clock', 0) >= 15:
            self._t_clock = now; t = time.localtime(now)
            self.send_cmd('T %d %d %d %d %d %d' % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_wday))
        if not getattr(self, '_climate_set', False):
            self._climate_set = True; self.send_cmd('c 215 215 1')
    def hmi_exits(self):
        """Quantas vezes o HMI caiu nesta execução (o guest o reinicia sozinho)."""
        try:                                   # lê só o que o console.log ganhou desde a última consulta (o status é pedido 4 vezes por segundo)
            p = os.path.join(self.logd, 'console.log'); off, n, tail = getattr(self, '_exits', (0, 0, b''))
            if os.path.getsize(p) < off: off, n, tail = 0, 0, b''
            with open(p, 'rb') as f: f.seek(off); d = tail + f.read(); off = f.tell()
            n += d.count(b'IDEMU-HMI-EXIT'); self._exits = (off, n, d[-15:] if not d.endswith(b'IDEMU-HMI-EXIT') else b'')
            return n
        except OSError: return 0
    def _mark(self, name): self.marks[name] = round(time.time() - self.t0, 1)
    def _boot_thread(self):
        try:
            angle = find_angle()
            dtb = os.path.join(self.run, 'boot.dtb')
            try: tab = coding8.build_tab(self.env)       # codificação alterada pelo usuário (None = a de fábrica)
            except Exception as e: tab = None; print('codificação do iDrive 8:', e)
            self.coding_rows = len(tab.splitlines()) if tab else 0
            memory = _prepare_ram(dtb, tab, self._shm_name, self._check_stopped)
            with self._life:
                if self.stop_ev.is_set():
                    if memory is not None: memory.close()
                    raise runtime.BootStopped()
                self._ram = memory
            self._mark('ram')
            self.step = 'Iniciando o renderizador'; self.pct = 10
            hl = open(os.path.join(self.logd, 'renderer.log'), 'wb')
            if self.native:
                serial, self._input_endpoint = runtime._loopback_endpoints(2)
                renderer = [os.path.join(NATIVE_BIN, 'mguhost.exe'), self._shm_name, str(MB), self.run, angle, str(self._input_endpoint[1])]
            else:
                renderer = [OUT + '/guest/mguhost', SHM, str(MB), self.run, angle]
            self._spawn('gl', renderer, stdout=hl, stderr=hl)
            time.sleep(0.5)
            if not self.native:
                os.mkfifo(self.console_in); self._keep = os.open(self.console_in, os.O_RDWR)
            ser = os.path.join(self.logd, 'console.log')
            args = 'console=ttyAMA0 loglevel=3 rdinit=/idemu.sh rootfstype=ramfs selinux=0 enforcing=0 panic=0 log_buf_len=2M' + (' idemu.debug' if self.debug else '') + (' idemu.dlt' if os.environ.get('IDEMU_MGU_DLT') else '') + (' idemu.usb' if os.environ.get('IDEMU_MGU_USB') else '') + ' idemu.time=%d' % time.time()
            cmd = ['qemu-system-aarch64', '-M', 'virt,gic-version=3,memory-backend=m0', '-accel', 'hvf', '-cpu', 'host', '-m', str(MB), '-smp', '4', '-nographic', '-serial', 'mon:stdio',
                   '-object', f'memory-backend-shm,id=m0,size={MB}M', '-dtb', dtb, '-kernel', OUT + '/Image', '-append', args]
            env = dict(os.environ, DYLD_INSERT_LIBRARIES=OUT + '/guest/qemushm.dylib', IDEMU_SHM_NAME=SHM)
            if self.native:
                qlog = open(os.path.join(self.logd, 'qemu.log'), 'wb')
                self._spawn('q', windows_qemu_command(dtb, self._shm_name, serial, args), stdout=qlog, stderr=subprocess.STDOUT)
                connection = runtime._connect(serial, 30, self._check_native_startup)
                with self._life:
                    if self.stop_ev.is_set(): connection.close(); raise runtime.BootStopped()
                    self._serial = connection
                    self._serial_thread = threading.Thread(target=self._pump_serial, args=(connection, ser), daemon=True)
                    self._serial_thread.start()
            else:
                sl = open(ser, 'wb')
                self._spawn('q', cmd, stdin=self._keep, stdout=sl, stderr=subprocess.STDOUT, env=env)
            self.step = 'Iniciando o sistema do carro'; self.pct = 15
            time.sleep(2)
            if not self.native: _posixshmem.shm_unlink(SHM)
            timeout = 1800 if self.native else 300
            end = time.time() + timeout
            while not self.stop_ev.is_set():
                if self.q.poll() is not None: raise RuntimeError('o QEMU terminou (%s); veja logs/console.log' % self.q.returncode)
                if self.gl.poll() is not None: raise RuntimeError('o renderizador terminou (%s); veja logs/renderer.log' % self.gl.returncode)
                if self.state == 'booting':
                    self._check_guest_boot()
                    el = time.time() - self.t0
                    self.pct = min(95, 15 + int(el * 1.6)); self.step = 'Iniciando o HMI do iDrive 8'
                    if self.frame_seq() >= 2:
                        self._mark('running'); self.state = 'running'; self.pct = 100; self.step = ''
                    elif time.time() > end: raise RuntimeError('HMI produced no frame within %d minutes; see logs/console.log' % (timeout // 60))
                else:
                    self.frame_seq(); self._car_state()
                time.sleep(0.25)
        except Exception as e:
            if not self.stop_ev.is_set(): self.err = str(e); self.state = 'error'; self._kill_children()
    def _check_native_startup(self):
        if self.stop_ev.is_set(): raise runtime.BootStopped()
        self._check_startup(self.q, 'QEMU', 'qemu.log')
        self._check_startup(self.gl, 'renderer', 'renderer.log')
    def _check_guest_boot(self):
        try:
            with open(os.path.join(self.logd, 'console.log'), 'rb') as log:
                log.seek(max(0, os.fstat(log.fileno()).st_size - 16384))
                tail = log.read()
        except OSError: return
        for marker in (b'Initramfs unpacking failed:', b'Kernel panic - not syncing:'):
            if marker in tail:
                line = next(line for line in tail.splitlines() if marker in line)
                raise RuntimeError('Guest boot failed: ' + line.decode('utf-8', 'replace') + '; see logs/console.log')
    def _pump_serial(self, connection, path):
        try:
            with open(path, 'wb', buffering=0) as log:
                while not self.stop_ev.is_set():
                    data = connection.recv(65536)
                    if not data: break
                    log.write(data)
        except OSError:
            pass
    def _kill_children(self):
        runtime.Runtime._kill_children(self)
        connection, self._serial = self._serial, None
        if connection:
            try: connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            connection.close()
        thread, self._serial_thread = self._serial_thread, None
        if thread and thread is not threading.current_thread(): thread.join(2)
        memory, self._ram = self._ram, None
        if memory is not None: memory.close()
        if self._sock is not None: self._sock.close(); self._sock = None
        if self._keep is not None:
            try: os.close(self._keep)
            except OSError: pass
            self._keep = None
        if sys.platform != 'win32':
            try: _posixshmem.shm_unlink(SHM)
            except OSError: pass
    def status(self):
        s = runtime.Runtime.status(self); s['kind'] = self.kind; s['disp'] = list(self.disp); s['hmi_exits'] = self.hmi_exits()
        return s
    def snapshot_info(self): return {'valid': False, 'size': 0, 'enabled': False}
    def drop_snapshot(self): pass
    # ---------- entrada ----------
    def send_cmd(self, line):
        with self._cmd_lock:
            if self._sock is None:
                import socket
                self._sock = socket.socket(socket.AF_INET if self.native else socket.AF_UNIX, socket.SOCK_DGRAM)
            self._sock.sendto(line.encode(), self._input_endpoint if self.native else os.path.join(self.run, 'input.sock'))
    def key(self, code, val): self.send_cmd('k %d %d 0 1' % (code, 1 if val else 0))
    def rotor(self, delta):
        if delta: self.send_cmd('r %d' % delta)
    def touch(self, x, y, down, move=False):
        if move: self.send_cmd('m %d %d' % (x, y)); return
        if down: self._t_down = time.time(); self.send_cmd('d %d %d' % (x, y)); return
        wait = getattr(self, '_t_down', 0) + 0.09 - time.time()   # um toque rápido demais o HMI ignora
        if wait > 0: time.sleep(wait)
        self.send_cmd('u')

    def guest(self, cmd):
        """Comando no console do guest (depuração); a saída vai para logs/console.log."""
        if self.native:
            with self._cmd_lock:
                if self._serial is None: raise RuntimeError('Guest console is not connected')
                self._serial.sendall((cmd + '\n').encode())
            return
        with open(self.console_in, 'w') as f: f.write(cmd + '\n')

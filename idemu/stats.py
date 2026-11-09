"""Estatísticas avançadas do ambiente em execução (o "gerenciador de tarefas" da VM).

Um amostrador em segundo plano mede, a cada segundo, o QEMU (a VM) e o renderizador (glhost):
CPU, RAM residente, quadros por segundo e tempo de quadro, GPU do Mac e o espaço em disco do ambiente.
Só usa `ps`, `ioreg`, `sysctl` e o cabeçalho do quadro compartilhado: nada é injetado na VM.
"""
import os, re, sys, time, shutil, threading, subprocess, collections

INTERVAL = 1.0
HISTORY = 900            # 15 minutos a 1 amostra/s
STORAGE_EVERY = 15.0

def _run(cmd, timeout=3):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception: return ''

def _cputime(s):
    """'M:SS.cc' ou 'H:MM:SS' do ps -> segundos."""
    try:
        parts = [float(x) for x in s.strip().split(':')]
    except ValueError: return None
    t = 0.0
    for p in parts: t = t * 60 + p
    return t

def ps_info(pids):
    """{pid: (cpu_seconds, rss_kb, vsz_kb)} num único `ps`."""
    pids = [p for p in pids if p]
    if not pids: return {}
    out = _run(['ps', '-o', 'pid=,time=,rss=,vsz=', '-p', ','.join(str(p) for p in pids)])
    res = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 4:
            t = _cputime(f[1])
            if t is not None: res[int(f[0])] = (t, int(f[2]), int(f[3]))
    return res

def gpu_info():
    """Uso da GPU do sistema (não por processo: o macOS não expõe isso sem privilégios)."""
    if sys.platform != 'darwin': return {}
    out = _run(['ioreg', '-r', '-d', '1', '-w0', '-c', 'IOAccelerator'])
    d = {}
    for k, key in (('Device Utilization %', 'dev'), ('Renderer Utilization %', 'render'), ('Tiler Utilization %', 'tiler'),
                   ('In use system memory', 'mem'), ('Alloc system memory', 'alloc')):
        m = re.search(r'"%s"=(\d+)' % re.escape(k), out)
        if m: d[key] = int(m.group(1))
    return d

def gpu_name():
    if sys.platform != 'darwin': return None
    out = _run(['ioreg', '-r', '-d', '1', '-w0', '-c', 'IOAccelerator'])
    m = re.search(r'"model" = "([^"]+)"', out)
    return m.group(1) if m else None

def dir_size(path):
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for n in files:
            try: total += os.lstat(os.path.join(root, n)).st_size
            except OSError: pass
    return total

def percentile(sorted_vals, p):
    if not sorted_vals: return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[i]

IDLE_S = 20.0           # s sem pedidos de /api/stats até a amostragem (100 Hz + ps/ioreg por segundo) dormir

class Sampler:
    def __init__(self, app, env_dir_fn):
        self.app, self.env_dir = app, env_dir_fn
        self.hist = collections.deque(maxlen=HISTORY)
        self.frames = collections.deque(maxlen=2000)         # instantes (s) em que o renderizador entregou um quadro
        self.lock = threading.Lock()
        self.run_key = None; self.last = None
        self.static = {'host_ram_mb': self._host_ram() // (1 << 20), 'cores': os.cpu_count() or 1, 'gpu': None, 'guest_ram_mb': 2048}
        self.storage = {}; self.storage_t = {}
        self._stop = threading.Event(); self.seen = 0.0          # última consulta de /api/stats: sem ninguém olhando, a amostragem para
        threading.Thread(target=self._fast, daemon=True).start()
        threading.Thread(target=self._slow, daemon=True).start()
        threading.Thread(target=lambda: self.static.__setitem__('gpu', gpu_name()), daemon=True).start()

    @staticmethod
    def _host_ram():
        if sys.platform.startswith('linux'):
            return os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        try: return int(_run(['sysctl', '-n', 'hw.memsize']).strip() or 0)
        except ValueError: return 0

    def stop(self): self._stop.set()

    # ---- amostragem de quadros (100 Hz, só lê o cabeçalho do quadro) ----
    def _fast(self):
        last_seq = None; last_t = None
        while not self._stop.is_set():
            if time.time() - self.seen > IDLE_S: last_seq = last_t = None; time.sleep(0.5); continue
            rt = self.app.rt
            if rt is not None and rt.state in ('booting', 'running'):
                try: seq = rt.frame_seq()
                except Exception: seq = None
                now = time.time()
                if seq is not None:
                    if last_seq is not None and seq > last_seq and last_t is not None:
                        n = min(seq - last_seq, 30)          # vários quadros entre duas leituras: divide o intervalo igualmente
                        step = (now - last_t) / n
                        with self.lock:
                            for i in range(n): self.frames.append(last_t + step * (i + 1))
                    last_seq, last_t = seq, now
            else: last_seq = last_t = None
            time.sleep(0.01)

    # ---- amostragem de processo, memória e GPU (1 Hz) ----
    def _slow(self):
        prev = {}
        while not self._stop.is_set():
            t0 = time.time()
            if t0 - self.seen > IDLE_S: prev.clear(); time.sleep(1.0); continue
            try: self._sample(prev)
            except Exception: pass
            time.sleep(max(0.05, INTERVAL - (time.time() - t0)))

    def _sample(self, prev):
        rt = self.app.rt
        if rt is None or rt.state not in ('booting', 'running') or rt.q is None:
            self.last = None; prev.clear(); return
        key = (rt.id, rt.t0)
        if key != self.run_key:
            with self.lock: self.hist.clear(); self.frames.clear()
            self.run_key = key; prev.clear()
            self.static['guest_ram_mb'] = self._guest_ram(rt.q.pid)
        now = time.time()
        pids = {'qemu': rt.q.pid, 'gl': rt.gl.pid if rt.gl else None}
        info = ps_info(list(pids.values()))
        s = {'t': round(now, 2), 'up': round(now - rt.t0, 1) if rt.t0 else 0, 'state': rt.state}
        for name, pid in pids.items():
            row = info.get(pid)
            if not row: s['cpu_' + name] = None; s['rss_' + name] = None; continue
            cpu, rss, vsz = row
            p = prev.get(pid)
            s['cpu_' + name] = round(100 * (cpu - p[0]) / max(now - p[1], 1e-3), 1) if p else 0.0
            s['rss_' + name] = round(rss / 1024.0, 1)
            if name == 'qemu': s['vsz_qemu'] = round(vsz / 1024.0)
            prev[pid] = (cpu, now)
        with self.lock:
            fr = [t for t in self.frames if t > now - 1.0]
        iv = sorted((b - a) * 1000.0 for a, b in zip(fr, fr[1:]))
        s['fps'] = len(fr)
        s['ft_avg'] = round(sum(iv) / len(iv), 2) if iv else 0.0
        s['ft_p95'] = round(percentile(iv, .95), 2) if iv else 0.0
        s['ft_max'] = round(iv[-1], 2) if iv else 0.0
        g = gpu_info()
        s['gpu'] = g.get('dev'); s['gpu_render'] = g.get('render'); s['gpu_tiler'] = g.get('tiler')
        s['gpu_mem_mb'] = round(g['mem'] / 1048576.0, 1) if 'mem' in g else None
        with self.lock: self.hist.append(s)
        self.last = s

    @staticmethod
    def _guest_ram(pid):
        m = re.search(r'\s-m\s+(\d+)', _run(['ps', '-o', 'command=', '-p', str(pid)]))
        return int(m.group(1)) if m else 2048

    # ---- armazenamento do ambiente ----
    def storage_of(self, eid):
        now = time.time()
        if eid in self.storage and now - self.storage_t.get(eid, 0) < STORAGE_EVERY: return self.storage[eid]
        d = self.env_dir(eid)
        parts = []; total = 0
        known = {'images': 'Imagens do sistema', 'snapshot': 'Boot rápido (estado salvo)', 'logs': 'Logs', 'coding_backups': 'Backups de coding', 'ssh': 'Chaves SSH'}
        seen = set()
        for sub, label in known.items():
            p = os.path.join(d, sub)
            if os.path.isdir(p):
                b = dir_size(p); parts.append({'id': sub, 'label': label, 'bytes': b}); total += b; seen.add(sub)
        other = 0
        for n in os.listdir(d):
            if n in seen: continue
            p = os.path.join(d, n)
            other += dir_size(p) if os.path.isdir(p) else os.path.getsize(p)
        if other: parts.append({'id': 'other', 'label': 'Outros', 'bytes': other}); total += other
        run = os.path.join('/tmp/idemu-%d' % os.getuid(), eid)
        rb = dir_size(run) if os.path.isdir(run) else 0
        if rb: parts.append({'id': 'run', 'label': 'Temporários da execução', 'bytes': rb}); total += rb
        du = shutil.disk_usage(d)
        res = {'total': total, 'parts': parts, 'disk_free': du.free, 'disk_total': du.total}
        self.storage[eid] = res; self.storage_t[eid] = now
        return res

    # ---- API ----
    def snapshot(self, eid, since=0.0):
        self.seen = time.time()
        rt = self.app.rt
        running = rt is not None and rt.state in ('booting', 'running')
        with self.lock: samples = [s for s in self.hist if s['t'] > since]
        eid = eid or (rt.id if rt else None)
        out = {'running': running, 'env': rt.id if rt else None, 'state': rt.state if rt else 'stopped', 'interval': INTERVAL, 'now': round(time.time(), 2),
               'static': dict(self.static, qemu_pid=rt.q.pid if running and rt.q else None, gl_pid=rt.gl.pid if running and rt.gl else None, boot_kind=getattr(rt, 'boot_kind', None) if running else None),
               'samples': samples}
        if eid:
            try: out['storage'] = self.storage_of(eid); out['storage_env'] = eid
            except OSError: out['storage'] = None
        return out

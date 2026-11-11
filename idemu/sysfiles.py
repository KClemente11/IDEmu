"""Arquivos do sistema do iDrive, descompactados: extrai o conteúdo dos pacotes SWFL (ou da imagem já montada) para uma pasta comum,
que a interface navega e o Finder abre.

Por geração:
  iDrive 5/6 (NBT Evo)  os três SWFL do ambiente (sistema, marca, HMI), bloco a bloco: <pasta>/os, /brand, /hmi (caminhos como na head unit: fs/sda0/...)
  iDrive 7 (MGU)        os 18 pacotes HAR + o kernel, como na montagem da imagem: a raiz Linux do RSE/HU em <pasta>/root e o kernel em <pasta>/kernel
  iDrive 8 (MGU22)      a raiz montada (mgu22/base.cpio: sistema, IVI, EXT e os dados SWFK), em <pasta>/root
  iDrive 4 (CIC)        o IFS de boot (QNX imagefs) em <pasta>/IFS e o EFS_RO (FFS3 + tar.gz do HD) em <pasta>/EFS_RO

A pasta fica no ambiente (iDrive 5/6) ou junto da imagem compartilhada da geração (mgu7/, mgu22/, cic/). Os caminhos pedidos pela API são sempre
relativos a ela e conferidos (nada de .. nem de seguir links simbólicos para fora)."""
import mimetypes, os, posixpath, shutil, stat, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_jobs = {}            # pasta -> {'state', 'pct', 'step', 'error', 'files', 'bytes'}
_lock = threading.Lock()
TEXT_EXT = {'.txt', '.cfg', '.conf', '.ini', '.xml', '.json', '.sh', '.log', '.csv', '.properties', '.md', '.lst', '.mnf', '.manifest', '.policy', '.rules',
            '.service', '.target', '.socket', '.desktop', '.py', '.lua', '.js', '.qml', '.css', '.html', '.htm', '.yaml', '.yml', '.odx-f', '.odx-d', '.fdl', ''}


def base_dir(env, env_dir):
    k = env.get('kind')
    if k in ('mgu7', 'mgu22', 'cic'):
        from .catalog import STATE_DIR
        return os.path.join(STATE_DIR, k, 'system_files')
    return os.path.join(env_dir, 'system_files')

def forget(eid):
    pass                                   # a pasta do iDrive 5/6 some com o ambiente; as das outras gerações são compartilhadas


def _du(path):
    n = b = 0
    for dp, dn, fn in os.walk(path):
        for f in fn:
            try: b += os.lstat(os.path.join(dp, f)).st_size; n += 1
            except OSError: pass
    return n, b

def status(env, env_dir):
    d = base_dir(env, env_dir)
    j = _jobs.get(d)
    if j and j['state'] == 'extracting': return dict(j, path=d)
    done = os.path.isfile(os.path.join(d, '.idemu-done'))
    out = {'state': 'ready' if done else ('error' if j and j['state'] == 'error' else 'none'), 'pct': 100 if done else 0, 'step': '',
           'error': j and j.get('error'), 'path': d, 'files': 0, 'bytes': 0, 'source': source_label(env)}
    if done:
        try:
            with open(os.path.join(d, '.idemu-done')) as f: n, b = f.read().split()[:2]; out.update(files=int(n), bytes=int(b))
        except (OSError, ValueError): pass
    return out

def source_label(env):
    k = env.get('kind')
    if k == 'mgu7': return 'Pacotes HAR do iDrive 7 (18 + kernel)'
    if k == 'mgu22': return 'Raiz montada do iDrive 8 (sistema, IVI, EXT e dados SWFK)'
    if k == 'cic': return 'IFS de boot e EFS_RO do iDrive 4'
    return 'Os três SWFL do ambiente (sistema, marca e HMI)'


# ------------------------------------------------------------------------------------------------ caminhos seguros
def _inside(base, p):
    base = os.path.normcase(os.path.realpath(base)); rp = os.path.normcase(os.path.realpath(p))
    try: return os.path.commonpath((base, rp)) == base
    except ValueError: return False

def resolve(base, rel):
    """Caminho dentro da pasta extraída; recusa .., caminhos absolutos e links que saiam dela."""
    rel = (rel or '').replace('\\', '/').strip('/')
    if any(c in ('..',) for c in rel.split('/')): raise ValueError('caminho inválido')
    p = os.path.join(base, rel) if rel else base
    if not _inside(base, os.path.dirname(p) if os.path.islink(p) else p): raise ValueError('caminho fora da pasta do sistema')
    return p

def _safe_dest(base, rel):
    rel = posixpath.normpath('/' + rel.replace('\\', '/')).lstrip('/')
    if not rel or rel.startswith('..'): return None
    dst = os.path.join(base, rel)
    par = os.path.dirname(dst)
    if not _inside(base, par): return None
    os.makedirs(par, exist_ok=True)
    return dst


# ------------------------------------------------------------------------------------------------ extração
def start_extract(env, env_dir):
    d = base_dir(env, env_dir)
    with _lock:
        j = _jobs.get(d)
        if j and j['state'] == 'extracting': return status(env, env_dir)
        _jobs[d] = {'state': 'extracting', 'pct': 0, 'step': 'Preparando', 'error': None, 'files': 0, 'bytes': 0, 'source': source_label(env)}
    env = dict(env)
    threading.Thread(target=_run, args=(env, env_dir, d), daemon=True).start()
    return status(env, env_dir)

def _run(env, env_dir, d):
    j = _jobs[d]
    def prog(p, s=None):
        j['pct'] = max(0, min(99, int(p)))
        if s: j['step'] = s
    tmp = d + '.tmp'
    try:
        shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
        k = env.get('kind')
        if k == 'mgu7': _extract_mgu7(tmp, prog)
        elif k == 'mgu22': _extract_mgu22(tmp, prog)
        elif k == 'cic': _extract_cic(tmp, prog)
        else: _extract_nbt(env, tmp, prog)
        prog(99, 'Contando os arquivos')
        n, b = _du(tmp)
        with open(os.path.join(tmp, '.idemu-done'), 'w') as f: f.write('%d %d %d\n' % (n, b, int(time.time())))
        shutil.rmtree(d, ignore_errors=True); os.replace(tmp, d)
        j.update(state='ready', pct=100, step='Pronto', files=n, bytes=b)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        j.update(state='error', error=str(e), step='')

def _extract_nbt(env, out, prog):
    from . import swfl
    sw = env.get('swfl') or {}
    roles = [r for r in ('os', 'brand', 'hmi') if sw.get(r)]
    if not roles: raise ValueError('o ambiente não tem arquivos SWFL')
    for i, r in enumerate(roles):
        if not os.path.isfile(sw[r]): raise ValueError('arquivo SWFL não encontrado: %s' % sw[r])
        label = {'os': 'Extraindo o sistema (os)', 'brand': 'Extraindo os dados da marca (brand)', 'hmi': 'Extraindo a interface (hmi)'}[r]
        prog(100 * i / len(roles), label)
        swfl.extract(sw[r], os.path.join(out, r), lambda tp, n, m: True, progress=lambda f, i=i: prog(100 * (i + f) / len(roles)))

def _extract_mgu7(out, prog):
    from . import catalog, mgu7
    psdz = catalog.effective_psdz('mgu7')
    pkgs = mgu7.required_packages(psdz)
    har = mgu7.tool_cmd('har.py')
    root = os.path.join(out, 'root'); os.makedirs(root)
    for i, f in enumerate(pkgs):
        kern = os.path.basename(f).startswith('swfl_' + mgu7.KERNEL_PKG)
        prog(100 * i / len(pkgs), 'Extraindo %s' % os.path.basename(f))
        r = subprocess.run(har + [f, os.path.join(out, 'kernel') if kern else root], capture_output=True, text=True)
        if r.returncode: raise RuntimeError('falha ao extrair %s: %s' % (os.path.basename(f), (r.stderr or r.stdout)[-200:]))

def _extract_mgu22(out, prog):
    """Lê o cpio "newc" sem compressão que a montagem do iDrive 8 grava (mgu22/base.cpio)."""
    from . import mgu
    src = os.path.join(mgu.OUT, 'base.cpio')
    if not os.path.isfile(src): raise ValueError('a imagem do iDrive 8 ainda não foi montada: compile o ambiente primeiro')
    root = os.path.join(out, 'root'); os.makedirs(root)
    total = float(os.path.getsize(src)); links = []
    prog(0, 'Lendo a raiz do iDrive 8')
    with open(src, 'rb') as f:
        while True:
            h = f.read(110)
            if len(h) < 110 or h[:6] not in (b'070701', b'070702'): break
            fld = [int(h[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
            mode, fsize, nsize = fld[1], fld[6], fld[11]
            name = f.read(nsize)[:-1].decode('utf-8', 'replace'); f.read((4 - (110 + nsize) % 4) % 4)
            if name == 'TRAILER!!!':                                   # vários cpio concatenados (raiz, IVI, EXT, SWFK): pula o enchimento até o próximo
                pos = f.tell(); look = f.read(8192); i = look.find(b'07070')
                if i < 0: break
                f.seek(pos + i); continue
            dst = _safe_dest(root, name) if name not in ('.', '') else None
            t = mode & 0o170000
            if t == 0o040000:
                if dst: os.makedirs(dst, exist_ok=True)
                f.seek(fsize, 1)
            elif t == 0o120000:
                tgt = f.read(fsize).decode('utf-8', 'replace')
                if dst: links.append((dst, tgt))
            elif t == 0o100000 and dst:
                with open(dst, 'wb') as o:
                    rem = fsize
                    while rem:
                        b = f.read(min(rem, 1 << 22))
                        if not b: raise ValueError('base.cpio truncado')
                        o.write(b); rem -= len(b)
                try: os.chmod(dst, (mode & 0o777) | 0o600)
                except OSError: pass
            else: f.seek(fsize, 1)
            f.read((4 - fsize % 4) % 4)
            prog(100 * f.tell() / total, 'Gravando os arquivos do iDrive 8')
    for dst, tgt in links:
        try:
            if os.path.lexists(dst): os.unlink(dst)
            os.symlink(tgt, dst)
        except OSError: pass

def _extract_cic(out, prog):
    from . import cic, catalog
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'cic'))
    import ifsx, efs
    ifs = os.path.join(cic.OUT, 'ifs.bin')
    if os.path.isfile(ifs):
        prog(5, 'Lendo o IFS de boot')
        d = open(ifs, 'rb').read(); img = ifsx.decompress(d, ifsx.parse_header(d)); base = os.path.join(out, 'IFS'); os.makedirs(base)
        _write_tree(base, ((nm, t, a, b, mode, img) for t, nm, mode, a, b in ifsx.walk(img)))
    pkg = cic.find_pkg(catalog.effective_psdz('cic'))
    if pkg:
        prog(25, 'Lendo o EFS_RO (dados do HMI, pode levar 1 minuto)')
        base = os.path.join(out, 'EFS_RO'); os.makedirs(base)
        for p, kind, data, mode in efs.entries(pkg, mapas=True, voz=True):
            dst = _safe_dest(base, p)
            if not dst: continue
            if kind == 'D': os.makedirs(dst, exist_ok=True)
            elif kind == 'L':
                try: os.symlink(data if isinstance(data, str) else data.decode('latin1'), dst)
                except OSError: pass
            elif kind == 'F':
                with open(dst, 'wb') as o: o.write(data)
    if not os.listdir(out): raise ValueError('a imagem do iDrive 4 ainda não foi montada: compile o ambiente primeiro')

def _write_tree(base, items):
    for nm, t, a, b, mode, img in items:
        dst = _safe_dest(base, nm)
        if not dst: continue
        if t == 'D': os.makedirs(dst, exist_ok=True)
        elif t == 'F':
            with open(dst, 'wb') as o: o.write(img[a:a + b])
        elif t == 'L':
            try: os.symlink(a, dst)
            except OSError: pass


# ------------------------------------------------------------------------------------------------ navegação
def _need(env, env_dir):
    d = base_dir(env, env_dir)
    if not os.path.isfile(os.path.join(d, '.idemu-done')): raise ValueError('os arquivos ainda não foram extraídos')
    return d

def listdir(env, env_dir, rel):
    from .server import ApiError
    try: d = _need(env, env_dir)
    except ValueError as e: raise ApiError(str(e), 409)
    try: p = resolve(d, rel)
    except ValueError as e: raise ApiError(str(e), 400)
    if not os.path.isdir(p) or os.path.islink(p): raise ApiError('não é uma pasta', 400)
    ents = []
    for n in sorted(os.listdir(p), key=lambda x: (not os.path.isdir(os.path.join(p, x)) or os.path.islink(os.path.join(p, x)), x.lower())):
        if n == '.idemu-done': continue
        q = os.path.join(p, n)
        try: st = os.lstat(q)
        except OSError: continue
        e = {'name': n, 'dir': stat.S_ISDIR(st.st_mode), 'size': st.st_size, 'mode': '%o' % (st.st_mode & 0o7777)}
        if stat.S_ISLNK(st.st_mode): e['link'] = os.readlink(q)
        ents.append(e)
    r = os.path.relpath(p, d); r = '' if r == '.' else r
    return {'path': r, 'parent': (os.path.dirname(r) if r else None), 'root': d, 'entries': ents, 'status': status(env, env_dir)}

def read(env, env_dir, rel, limit=64 << 20):
    from .server import ApiError
    try:
        d = _need(env, env_dir); p = resolve(d, rel)
    except ValueError as e: raise ApiError(str(e), 400)
    if os.path.islink(p) or not os.path.isfile(p): raise ApiError('arquivo não encontrado', 404)
    if not _inside(d, p): raise ApiError('caminho fora da pasta do sistema', 400)
    sz = os.path.getsize(p)
    if sz > limit: raise ApiError('arquivo grande demais para abrir aqui (%d MB): use "Mostrar no Finder"' % (sz >> 20), 413)
    ext = os.path.splitext(p)[1].lower()
    ctype = mimetypes.guess_type(p)[0] or ('text/plain; charset=utf-8' if ext in TEXT_EXT else 'application/octet-stream')
    if ctype.startswith('text/html') or 'xml' in ctype or 'javascript' in ctype or ctype.startswith('image/svg'): ctype = 'text/plain; charset=utf-8'   # nada do firmware roda no navegador
    with open(p, 'rb') as f: body = f.read()
    return body, ctype, os.path.basename(p)

def reveal(env, env_dir, rel):
    from .server import ApiError
    from .catalog import WSL
    try:
        d = _need(env, env_dir); p = resolve(d, rel)
    except ValueError as e: raise ApiError(str(e), 400)
    folder = p if os.path.isdir(p) else os.path.dirname(p)
    try:
        if sys.platform == 'win32':
            os.startfile(folder)
        elif WSL:
            win_path = subprocess.check_output(['wslpath', '-w', folder], text=True).strip()
            subprocess.Popen(['explorer.exe', win_path])
        else:
            subprocess.run(['open', '-R', p] if os.path.isfile(p) else ['open', p], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise ApiError('Could not open the system files folder: %s' % e, 500)
    return {'ok': True}

def remove(env, env_dir):
    d = base_dir(env, env_dir)
    j = _jobs.get(d)
    if j and j['state'] == 'extracting':
        from .server import ApiError
        raise ApiError('aguarde a extração terminar')
    shutil.rmtree(d, ignore_errors=True); _jobs.pop(d, None)
    return status(env, env_dir)

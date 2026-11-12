"""Overlay do ambiente (iDrive 5/6): arquivos do usuário gravados nas imagens a cada build, por cima do conteúdo dos SWFL.

O guest carrega sda.img/sdb.img na RAM (devb-ram) e nunca grava de volta: o que muda em execução some ao parar. O overlay é o
caminho persistente: fica em <env>/overlay/ (fora de work/ e images/, que o build apaga/reescreve) e entra em toda recompilação.

  overlay/sda/<caminho>   ->  /fs/sda0/repository/istep/<caminho>  (= /bin /lib /etc /opt /var no guest)
                              ex.: overlay/sda/var/opt/hmi/data/ID5/plugins/x.so  ->  /var/opt/hmi/data/ID5/plugins/x.so
  overlay/sdb/<caminho>   ->  /fs/sdb0/ro/<caminho>  (= /opt/hmi/ID5/data/ro, dados do HMI, montado somente leitura)
  overlay/delete.txt      um caminho do guest por linha (# comenta) a omitir da imagem; uma pasta omite tudo o que está nela

Sem a pasta overlay/ (ou vazia) o build sai idêntico ao de antes. Só biblioteca padrão."""
import os
import posixpath
import sys
import subprocess

DIRNAME = 'overlay'
ISTEP_GUEST = 'fs/sda0/repository/istep/'
SDB_GUEST = 'fs/sdb0/ro/'
RO = 'opt/hmi/ID5/data/ro/'
RO_ALIASES = (RO, 'opt/hmi/data/ro/')
QNX4_NAME_MAX = 48

README = """IDEmu overlay - files written into the disk images on every build (iDrive 5/6)

The emulated head unit loads its disks into RAM, so changes made while it runs are lost when it stops.
Files here are added on top of the SWFL content every time you (re)build the environment.

  sda/<path>   -> /<path> in the guest (/bin /lib /etc /opt /var live on sda)
                  example: sda/var/opt/hmi/data/ID5/plugins/my.so -> /var/opt/hmi/data/ID5/plugins/my.so
  sdb/<path>   -> /opt/hmi/ID5/data/ro/<path> (HMI data, mounted read-only in the guest)
  delete.txt   one guest path per line to leave out of the image (# starts a comment)

After changing anything here: Rebuild the environment, then start it with a full (cold) boot.
Limits: QNX4 file names (sda) up to 48 characters; sda content must fit the 480 MB RAM disk.
ELF files and scripts starting with #! become executable (755); everything else is 644.
"""


def root(env_dir):
    return os.path.join(env_dir, DIRNAME)


def ensure(env_dir):
    """Cria overlay/{sda,sdb} e o README (não mexe no que já existe). Devolve a pasta."""
    r = root(env_dir)
    for sub in ('sda', 'sdb'):
        os.makedirs(os.path.join(r, sub), exist_ok=True)
    rd = os.path.join(r, 'README.txt')
    if not os.path.exists(rd):
        with open(rd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(README)
    return r


def _skip_name(n):
    return n.startswith('._') or n in ('.DS_Store', 'Thumbs.db', 'desktop.ini')


def files(env_dir, which):
    """[(caminho relativo com '/', caminho no host)] de overlay/<which>, em ordem."""
    base = os.path.join(root(env_dir), which)
    out = []
    if not os.path.isdir(base):
        return out
    for dp, dn, fn in os.walk(base):
        dn[:] = sorted(d for d in dn if not _skip_name(d))
        for n in sorted(fn):
            if _skip_name(n):
                continue
            p = os.path.join(dp, n)
            if os.path.isfile(p):
                out.append((os.path.relpath(p, base).replace(os.sep, '/'), p))
    return out


def exec_mode(path):
    """755 para ELF ou script (#!), senão 644 – igual ao sda; independe do bit x do host (no Windows todo arquivo 'é' executável)."""
    try:
        with open(path, 'rb') as f:
            m = f.read(4)
    except OSError:
        m = b''
    return 0o100755 if (m == b'\x7fELF' or m[:2] == b'#!') else 0o100644


def guest_target(path):
    """Caminho do guest -> ('sda'|'sdb', relativo). Aceita /var/..., /fs/sda0/repository/istep/..., /opt/hmi/ID5/data/ro/..., /fs/sdb0/ro/..."""
    p = posixpath.normpath('/' + path.strip().replace('\\', '/')).lstrip('/')
    if p in ('', '.'):
        return None
    for pre in (SDB_GUEST,) + RO_ALIASES:
        if (p + '/').startswith(pre):
            return 'sdb', p[len(pre):].strip('/')
    if (p + '/').startswith(ISTEP_GUEST):
        p = p[len(ISTEP_GUEST):].strip('/')
    return 'sda', p


def deletions(env_dir):
    """{'sda': [rel...], 'sdb': [rel...]} lidos de overlay/delete.txt."""
    out = {'sda': [], 'sdb': []}
    p = os.path.join(root(env_dir), 'delete.txt')
    if not os.path.isfile(p):
        return out
    with open(p, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.split('#', 1)[0].strip()
            t = guest_target(ln) if ln else None
            if t and t[1]:
                out[t[0]].append(t[1])
    return out


def _under(rel, prefix):
    return rel == prefix or rel.startswith(prefix.rstrip('/') + '/')


def apply_sda(tree, env_dir, log=print):
    """Aplica delete.txt e overlay/sda ao mapa relpath -> arquivo do host que vira o sda.img. Devolve um resumo para o manifesto."""
    info = {'sda': [], 'deleted': []}
    for d in deletions(env_dir)['sda']:
        gone = [r for r in tree if _under(r, d)]
        for r in gone:
            del tree[r]
        info['deleted'].append({'path': '/' + d, 'files': len(gone)})
        log('overlay: omitido /%s (%d arquivo(s))' % (d, len(gone)))
    for rel, p in files(env_dir, 'sda'):
        if any(_under(rel, a.rstrip('/')) for a in RO_ALIASES):
            log('AVISO overlay: sda/%s fica sob /opt/hmi/ID5/data/ro, que vem do sdb no guest; ponha em overlay/sdb/ - ignorado' % rel)
            continue
        if len(os.path.basename(rel)) > QNX4_NAME_MAX:
            log('AVISO overlay: nome com mais de %d caracteres não cabe no QNX4: %s - ignorado' % (QNX4_NAME_MAX, rel))
            continue
        replaced = rel in tree
        tree[rel] = p
        info['sda'].append(rel)
        log('overlay: %s /%s' % ('substitui' if replaced else 'adiciona', rel))
    return info


def apply_sdb(ro, env_dir, mkq6, log=print):
    """Aplica delete.txt e overlay/sdb à árvore mkq6 da pasta ro/ do sdb.img."""
    info = {'sdb': [], 'deleted': []}
    for d in deletions(env_dir)['sdb']:
        parts = [x.encode() for x in d.split('/') if x]
        n = ro
        for x in parts[:-1]:
            n = (n.kids or {}).get(x)
            if n is None:
                break
        ok = n is not None and n.kids is not None and parts and n.kids.pop(parts[-1], None) is not None
        info['deleted'].append({'path': '/opt/hmi/ID5/data/ro/' + d, 'found': bool(ok)})
        log('overlay: omitido /opt/hmi/ID5/data/ro/%s%s' % (d, '' if ok else ' (não existia)'))
    for rel, p in files(env_dir, 'sdb'):
        n = ro
        parts = rel.split('/')
        for x in parts[:-1]:
            b = x.encode()
            k = n.kids.get(b)
            if k is None or k.kids is None:          # não existe, ou era arquivo: vira pasta
                k = mkq6.N(b, 0o40775); n.kids[b] = k
            n = k
        b = parts[-1].encode()
        replaced = b in n.kids
        n.kids[b] = mkq6.N(b, exec_mode(p), p, os.path.getsize(p))
        info['sdb'].append(rel)
        log('overlay: %s /opt/hmi/ID5/data/ro/%s' % ('substitui' if replaced else 'adiciona', rel))
    return info


def status(env_dir):
    r = root(env_dir)
    sda, sdb = files(env_dir, 'sda'), files(env_dir, 'sdb')
    dl = deletions(env_dir)
    size = sum(os.path.getsize(p) for _, p in sda + sdb)
    return {'path': r, 'exists': os.path.isdir(r), 'sda': len(sda), 'sdb': len(sdb), 'deletes': len(dl['sda']) + len(dl['sdb']), 'bytes': size}


def reveal(env_dir):
    """Cria a pasta (se preciso) e a abre no Explorer/Finder."""
    from .server import ApiError
    from .catalog import WSL
    r = ensure(env_dir)
    try:
        if sys.platform == 'win32':
            os.startfile(r)
        elif WSL:
            win_path = subprocess.check_output(['wslpath', '-w', r], text=True).strip()
            subprocess.Popen(['explorer.exe', win_path])
        else:
            subprocess.run(['open', r], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise ApiError('não consegui abrir a pasta do overlay: %s' % e, 500)
    return dict(status(env_dir), ok=True)

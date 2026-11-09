"""Leitor/extrator de pacotes SWFL (.bin) do PSDZData.

Formato (descoberto por engenharia reversa): 10 bytes de cabeçalho, depois registros
  [tipo:1][id:2][tamanho:4 LE][?:2] + payload.
  tipo 2 = metadados texto "Chave=valor;..." (TargetPath, Name, Tag, Append, CPU ...)
  tipo 4 = bloco de dados do arquivo descrito pelo último registro tipo 2
Arquivos grandes vêm em blocos de 20 MB: o primeiro registro cria o arquivo, os seguintes
(Append=On) acrescentam. Vários blocos de dados podem seguir um mesmo registro de metadados.
"""
import os, posixpath, re

class SwflError(Exception):
    pass

def _meta(txt):
    return dict(x.split('=', 1) for x in txt.split(';') if '=' in x)

def records(path):
    """Gera (meta_dict, meta_text, data_offset, data_len, record_index) por bloco de dados (tipo 4)."""
    with open(path, 'rb') as f:
        for r in records_fh(f, path):
            yield r

def parse_name(path):
    """swfl_0000271a.bin.007_051_002 -> ('swfl','0000271a','bin','007_051_002')"""
    m = re.match(r'^(\w+?)_([0-9a-fA-F]{8})\.(\w+)\.(\d{3}_\d{3}_\d{3})$', os.path.basename(path))
    return m.groups() if m else None

def norm_target(meta):
    tp = posixpath.normpath('/' + meta.get('TargetPath', '/').lstrip('/')).lstrip('/')
    return tp

def summarize(path):
    """Resumo rápido: nº de arquivos, bytes, CPUs, destinos de topo."""
    files = set(); nbytes = 0; cpus = set(); roots = {}
    for meta, txt, off, ln, idx in records(path):
        files.add(norm_target(meta) + '/' + meta.get('Name', ''))
        nbytes += ln
        if 'CPU' in meta: cpus.add(meta['CPU'])
        r = '/'.join(norm_target(meta).split('/')[:2])
        roots[r] = roots.get(r, 0) + 1
    return {'files': len(files), 'bytes': nbytes, 'cpus': sorted(cpus), 'roots': roots}

def extract(path, out, select, progress=None):
    """Extrai blocos para out/<TargetPath>/<Name>.
    select(target_path, name, meta) -> bool.  Retorna lista de (relpath, tamanho)."""
    written = {}
    last_rec = {}
    size = float(os.path.getsize(path))
    with open(path, 'rb') as f:
        for meta, txt, off, ln, idx in records_fh(f, path):
            name = os.path.basename(meta.get('Name', 'x'))
            tp = norm_target(meta)
            if not select(tp, name, meta):
                continue
            dest = os.path.join(out, tp, name)
            if 'Append=On' in txt and dest in written:
                mode = 'ab'
            elif last_rec.get(dest) == idx:
                mode = 'ab'
            else:
                mode = 'wb'
                written[dest] = 0
                os.makedirs(os.path.dirname(dest), exist_ok=True)
            last_rec[dest] = idx
            with open(dest, mode) as o:
                f.seek(off)
                rem = ln
                while rem:
                    b = f.read(min(rem, 1 << 22))
                    if not b:
                        raise SwflError('arquivo truncado: ' + path)
                    o.write(b); rem -= len(b)
            written[dest] += ln
            if progress: progress(off / size)
    return [(os.path.relpath(k, out), v) for k, v in written.items()]

def records_fh(f, path):
    size = os.path.getsize(path)
    f.seek(0)
    if len(f.read(10)) < 10:
        raise SwflError('arquivo muito curto: ' + path)
    pos = 10
    meta, txt, idx = {}, '', 0
    while pos + 9 <= size:
        f.seek(pos)
        h = f.read(9)
        if len(h) < 9:
            break
        t = h[0]
        ln = int.from_bytes(h[3:7], 'little')
        if t == 2:
            txt = f.read(ln).decode('latin1')
            meta = _meta(txt); idx += 1
        elif t == 4:
            yield meta, txt, pos + 9, ln, idx
        pos += 9 + ln
    if pos != size:
        raise SwflError('estrutura inconsistente em %s (fim em %d de %d)' % (path, pos, size))

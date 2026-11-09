#!/usr/bin/env python3
"""Gera um imagefs QNX 6.3 (sem compressão) a partir de uma árvore de arquivos, para o memifs2 montar da RAM/flash.
API: build(entries) com entries = [(caminho, 'F', bytes|None, modo) | (caminho, 'D', None, modo) | (caminho, 'L', alvo, modo)]"""
import struct, time

def build(entries):
    now = int(time.time())
    dirs = []; ino = 1
    body = bytearray()
    dent = bytearray()
    files = []
    for path, kind, data, mode in entries:
        path = path.strip('/')
        name = path.encode() + b'\0'
        if kind == 'D':
            e = struct.pack('<HHIIIII', 0, 0, ino, 0o040000 | mode, 0, 0, now) + name
        elif kind == 'L':
            tgt = data.encode() + b'\0'
            e = struct.pack('<HHIIIII', 0, 0, ino, 0o120000 | mode, 0, 0, now) + struct.pack('<HH', len(name), len(tgt)) + name + tgt
        else:
            e = struct.pack('<HHIIIII', 0, 0, ino, 0o100000 | mode, 0, 0, now) + struct.pack('<II', 0, 0) + name
            files.append((len(dent), data))
        e += b'\0' * (-len(e) % 4)
        e = struct.pack('<H', len(e)) + e[2:]
        dent += e; ino += 1
    hdr_end = 92 + len(dent) + 4                        # terminador de 4 bytes
    pos = (hdr_end + 0xfff) & ~0xfff                    # dados alinhados a página
    blob = bytearray()
    for off_in_dir, data in files:
        pos = (pos + 3) & ~3
        struct.pack_into('<II', dent, off_in_dir + 24, pos, len(data))
        blob += b'\0' * (pos - 92 - len(dent) - 4 - len(blob)) if pos > 92 + len(dent) + 4 + len(blob) else b''
        blob += data; pos += len(data)
    # recompõe: cabeçalho + diretório + terminador + preenchimento + dados
    out = bytearray(b'imagefs\x04') + struct.pack('<IIII', 0, hdr_end, 92, 0)
    out += bytes(92 - len(out))
    out += dent + bytes(4)
    first = (hdr_end + 0xfff) & ~0xfff
    out += bytes(first - len(out))
    cur = first
    for off_in_dir, data in files:
        o = struct.unpack_from('<I', dent, off_in_dir + 24)[0]
    out = bytearray(out[:first])
    # grava arquivos em sequência alinhada a 4
    cur = first
    for off_in_dir, data in files:
        cur = (cur + 3) & ~3
        out += bytes(cur - len(out))
        struct.pack_into('<II', out, 92 + off_in_dir + 24, cur, len(data))
        out += data; cur += len(data)
    out += bytes(4)
    struct.pack_into('<I', out, 8, len(out))
    n = len(out) // 4 - 1
    acc = sum(struct.unpack_from('<%dI' % n, out, 0)) & 0xffffffff
    struct.pack_into('<I', out, len(out) - 4, (-acc) & 0xffffffff)
    return bytes(out)

if __name__ == '__main__':
    import sys, tarfile
    sys.path.insert(0, '.')
    t = tarfile.open(sys.argv[1]); ents = []
    for m in t.getmembers():
        p = m.name.lstrip('./')
        if not p: continue
        if m.isdir(): ents.append((p, 'D', None, 0o755))
        elif m.isreg(): ents.append((p, 'F', t.extractfile(m).read(), 0o755))
        elif m.issym(): ents.append((p, 'L', m.linkname, 0o755))
    open(sys.argv[2], 'wb').write(build(ents)); print(len(ents))

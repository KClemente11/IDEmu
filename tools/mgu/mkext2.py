#!/usr/bin/env python3
"""Cria uma imagem ext2 (rev 1, blocos de 4 KiB, sem journal) a partir de uma pasta, sem e2fsprogs.

O kernel do MGU não tem initramfs nem virtio: o sistema sobe de um "cartão" SD (sdhci-pci) com ext4.
O driver ext4 monta ext2 sem journal sem problemas, então basta este gravador simples.

Uso: mkext2.py PASTA imagem.img TAMANHO_MB [--root-owner]
  * todos os arquivos ficam com uid/gid 0 (o HMI roda como root na VM);
  * elos rígidos (mesmo st_ino) viram o mesmo inode; symlinks <= 59 bytes são "rápidos";
  * o tamanho da imagem deve ser potência de 2 se for usada como cartão SD no QEMU.
"""
import os, sys, stat, struct, time

BS = 4096
INODE_SIZE = 128
BPG = 8 * BS                # blocos por grupo (um bitmap de 1 bloco)
FT = {stat.S_IFREG: 1, stat.S_IFDIR: 2, stat.S_IFCHR: 3, stat.S_IFBLK: 4, stat.S_IFIFO: 5, stat.S_IFSOCK: 6, stat.S_IFLNK: 7}


class Img:
    def __init__(self, path, size_mb, ipg=4096):
        self.size = size_mb << 20
        self.nblocks = self.size // BS
        self.ngroups = (self.nblocks + BPG - 1) // BPG
        self.ipg = ipg
        self.ninodes = ipg * self.ngroups
        self.itb = (ipg * INODE_SIZE + BS - 1) // BS                  # blocos da tabela de inodes por grupo
        self.gdtb = (self.ngroups * 32 + BS - 1) // BS
        self.f = open(path, 'wb'); self.f.truncate(self.size)
        self.free_blocks = [0] * self.ngroups
        self.bmap = [bytearray(BS) for _ in range(self.ngroups)]
        self.imap = [bytearray(BS) for _ in range(self.ngroups)]
        self.itab = [bytearray(self.itb * BS) for _ in range(self.ngroups)]
        self.free_inodes = [ipg] * self.ngroups
        self.dirs = [0] * self.ngroups
        self.cur = 0                                                    # grupo corrente de alocação
        for g in range(self.ngroups):
            first = g * BPG
            n = min(BPG, self.nblocks - first)
            for b in range(n): pass
            # reserva: superbloco+GDT (em todos os grupos, pois não usamos sparse_super), bitmaps, tabela de inodes
            meta = 1 + self.gdtb + 2 + self.itb
            self.meta_blocks = meta
            for b in range(meta): self._set(g, b)
            if n < BPG:                                                  # bits além do fim do dispositivo
                for b in range(n, BPG): self._set(g, b, count=False)
            self.free_blocks[g] = n - meta
        self.next_ino = 11                                              # 1..10 reservados; 2 = raiz
        for i in range(1, 11): self._iset(0, i - 1)
        self.free_inodes[0] -= 10
        self.alloc_ptr = [meta for _ in range(self.ngroups)]

    def _set(self, g, b, count=True):
        self.bmap[g][b >> 3] |= 1 << (b & 7)

    def _iset(self, g, i):
        self.imap[g][i >> 3] |= 1 << (i & 7)

    def alloc(self, n):
        """Aloca n blocos (tenta contíguos); devolve lista de números absolutos."""
        out = []
        while n:
            g = self.cur
            while g < self.ngroups and self.free_blocks[g] == 0: g += 1
            if g >= self.ngroups: raise SystemExit('imagem cheia')
            self.cur = g
            first = g * BPG
            lim = min(BPG, self.nblocks - first)
            p = self.alloc_ptr[g]
            take = min(n, lim - p)
            for b in range(p, p + take): self._set(g, b)
            out.extend(range(first + p, first + p + take))
            self.alloc_ptr[g] = p + take; self.free_blocks[g] -= take; n -= take
        return out

    def write_blocks(self, blocks, data):
        """Grava data nos blocos dados (agrupando sequências contíguas)."""
        i = 0; off = 0
        while i < len(blocks):
            j = i
            while j + 1 < len(blocks) and blocks[j + 1] == blocks[j] + 1: j += 1
            ln = (j - i + 1) * BS
            chunk = data[off:off + ln]
            self.f.seek(blocks[i] * BS); self.f.write(chunk)
            off += ln; i = j + 1

    def new_inode(self, isdir=False):
        ino = self.next_ino; self.next_ino += 1
        if ino > self.ninodes: raise SystemExit('inodes esgotados (aumente ipg)')
        g = (ino - 1) // self.ipg
        self._iset(g, (ino - 1) % self.ipg); self.free_inodes[g] -= 1
        if isdir: self.dirs[g] += 1
        return ino

    def put_inode(self, ino, mode, size, nblocks_512, iblock, nlink, mtime, atime=None, ctime=None):
        g = (ino - 1) // self.ipg; off = ((ino - 1) % self.ipg) * INODE_SIZE
        rec = struct.pack('<HHIIIIIHHIII60sIIII12s', mode, 0, size & 0xFFFFFFFF, int(atime or mtime), int(ctime or mtime), int(mtime),
                          0, 0, nlink, nblocks_512, 0, 0, iblock, 0, 0, size >> 32, 0, b'\0' * 12)
        self.itab[g][off:off + INODE_SIZE] = rec[:INODE_SIZE]

    def block_ptrs(self, blocks):
        """Constrói i_block (15 ponteiros): 12 diretos + indireto simples/duplo; devolve (bytes60, blocos_extras)."""
        ptr = BS // 4
        direct = blocks[:12]; rest = blocks[12:]
        extra = []
        ind = dbl = 0
        if rest:
            chunk = rest[:ptr]; rest = rest[ptr:]
            ind = self.alloc(1)[0]; extra.append(ind)
            self.f.seek(ind * BS); self.f.write(struct.pack('<%dI' % len(chunk), *chunk).ljust(BS, b'\0'))
        if rest:
            dbl = self.alloc(1)[0]; extra.append(dbl)
            tops = []
            while rest:
                chunk = rest[:ptr]; rest = rest[ptr:]
                b = self.alloc(1)[0]; extra.append(b); tops.append(b)
                self.f.seek(b * BS); self.f.write(struct.pack('<%dI' % len(chunk), *chunk).ljust(BS, b'\0'))
            if len(tops) > ptr: raise SystemExit('arquivo grande demais (precisa de indireto triplo)')
            self.f.seek(dbl * BS); self.f.write(struct.pack('<%dI' % len(tops), *tops).ljust(BS, b'\0'))
        vals = list(direct) + [0] * (12 - len(direct)) + [ind, dbl, 0]
        return struct.pack('<15I', *vals), extra

    def finish(self):
        import uuid
        free_b = sum(self.free_blocks); free_i = sum(self.free_inodes)
        s = bytearray(1024); now = int(time.time())
        struct.pack_into('<IIIIII', s, 0, self.ninodes, self.nblocks, 0, free_b, free_i, 0)
        struct.pack_into('<IIIII', s, 24, 2, 2, BPG, BPG, self.ipg)            # log_block_size=2 (4 KiB)
        struct.pack_into('<II', s, 44, 0, now)                                  # mtime, wtime
        struct.pack_into('<HHHHHH', s, 52, 0, 0xFFFF, 0xEF53, 1, 1, 0)          # mnt, max_mnt, magic, state, errors, minor
        struct.pack_into('<I', s, 76, 1)                                        # rev_level 1
        struct.pack_into('<IH', s, 84, 11, INODE_SIZE)                          # first_ino, inode_size
        struct.pack_into('<III', s, 92, 0, 0x2, 0x2)                            # compat, incompat=FILETYPE, ro_compat=LARGE_FILE
        s[104:120] = uuid.uuid4().bytes
        s[120:136] = b'idemu-mgu'.ljust(16, b'\0')
        gd = bytearray(self.gdtb * BS)
        for g in range(self.ngroups):
            first = g * BPG
            bb = first + 1 + self.gdtb; ib = bb + 1; it = ib + 1
            if min(self.free_blocks[g], self.free_inodes[g], self.dirs[g]) < 0 or max(self.free_blocks[g], self.free_inodes[g], self.dirs[g]) > 65535: print('grupo', g, self.free_blocks[g], self.free_inodes[g], self.dirs[g])
            struct.pack_into('<IIIHHHH12s', gd, g * 32, bb, ib, it, self.free_blocks[g], self.free_inodes[g], self.dirs[g], 0, b'\0' * 12)
            self.f.seek(bb * BS); self.f.write(bytes(self.bmap[g]))
            self.f.seek(ib * BS); self.f.write(bytes(self.imap[g]))
            self.f.seek(it * BS); self.f.write(bytes(self.itab[g]))
        self.f.seek(1024); self.f.write(bytes(s))
        self.f.seek(BS); self.f.write(bytes(gd))
        self.f.close()


def build(root, path, size_mb):
    img = Img(path, size_mb)
    ino_of = {}                      # (dev, ino) -> inode ext2 (elos rígidos)
    links = {}                       # inode ext2 -> contagem de nomes
    total = [0]

    def write_file(full, st):
        size = st.st_size
        nblk = (size + BS - 1) // BS
        blocks = img.alloc(nblk) if nblk else []
        with open(full, 'rb') as f:
            i = 0
            while i < nblk:
                n = min(nblk - i, 2048)
                data = f.read(n * BS)
                img.write_blocks(blocks[i:i + n], data.ljust(n * BS, b'\0'))
                i += n
        ib, extra = img.block_ptrs(blocks)
        return size, (nblk + len(extra)) * (BS // 512), ib

    def walk(dirpath, ino_dir, parent_ino):
        ents = [('.', ino_dir, 2), ('..', parent_ino, 2)]
        subdirs = 0
        for name in sorted(os.listdir(dirpath)):
            full = os.path.join(dirpath, name)
            st = os.lstat(full); m = st.st_mode
            if len(name.encode()) > 255: print('nome longo demais, ignorado:', full); continue
            if stat.S_ISDIR(m):
                ino = img.new_inode(True); subdirs += 1
                walk(full, ino, ino_dir); ents.append((name, ino, 2))
            elif stat.S_ISLNK(m):
                tgt = os.readlink(full).encode(); ino = img.new_inode()
                if len(tgt) <= 59:
                    img.put_inode(ino, stat.S_IFLNK | 0o777, len(tgt), 0, tgt.ljust(60, b'\0'), 1, st.st_mtime)
                else:
                    b = img.alloc(1)[0]; img.f.seek(b * BS); img.f.write(tgt.ljust(BS, b'\0'))
                    ib, _ = img.block_ptrs([b]); img.put_inode(ino, stat.S_IFLNK | 0o777, len(tgt), BS // 512, ib, 1, st.st_mtime)
                ents.append((name, ino, 7))
            elif stat.S_ISREG(m):
                key = (st.st_dev, st.st_ino)
                if key in ino_of and st.st_nlink > 1:
                    ino = ino_of[key]; links[ino] += 1
                else:
                    ino = img.new_inode(); size, n512, ib = write_file(full, st)
                    ino_of[key] = ino; links[ino] = 1; total[0] += size
                    img.put_inode(ino, stat.S_IFREG | (m & 0o7777), size, n512, ib, 1, st.st_mtime)
                ents.append((name, ino, 1))
            # outros tipos (dispositivos, fifos) ficam de fora: o devtmpfs cria os /dev
        # grava o diretório
        buf = bytearray(); blocks_data = []
        cur = bytearray()
        for name, ino, ft in ents:
            nb = name.encode(); rl = (8 + len(nb) + 3) & ~3
            if len(cur) + rl > BS:
                # estende o último registro até o fim do bloco
                last = cur
                blocks_data.append(cur); cur = bytearray()
            cur += struct.pack('<IHBB', ino, rl, len(nb), ft) + nb + b'\0' * (rl - 8 - len(nb))
        blocks_data.append(cur)
        for b in blocks_data:               # ajusta rec_len do último registro de cada bloco
            # percorre até o último
            p = 0; lastp = 0
            while p < len(b):
                rl = struct.unpack_from('<H', b, p + 4)[0]; lastp = p; p += rl
            struct.pack_into('<H', b, lastp + 4, BS - lastp)
            b.extend(b'\0' * (BS - len(b)))
        blks = img.alloc(len(blocks_data))
        img.write_blocks(blks, b''.join(bytes(b) for b in blocks_data))
        ib, extra = img.block_ptrs(blks)
        st = os.lstat(dirpath)
        img.put_inode(ino_dir, stat.S_IFDIR | (st.st_mode & 0o7777), len(blocks_data) * BS, (len(blks) + len(extra)) * (BS // 512), ib, 2 + subdirs, st.st_mtime)

    img.dirs[0] += 1
    img._iset(0, 1)                                  # inode 2 (raiz): já contado entre os 10 reservados
    walk(root, 2, 2)
    # contagem de elos dos arquivos com mais de um nome
    for ino, n in links.items():
        if n > 1:
            g = (ino - 1) // img.ipg; off = ((ino - 1) % img.ipg) * INODE_SIZE
            struct.pack_into('<H', img.itab[g], off + 26, n)
    img.finish()
    return total[0], img.next_ino


if __name__ == '__main__':
    root, path, mb = sys.argv[1], sys.argv[2], int(sys.argv[3])
    t0 = time.time()
    nbytes, ninodes = build(root, path, mb)
    print('imagem pronta: %d arquivos/inodes, %.0f MB de dados, %.0f s' % (ninodes, nbytes / 1048576, time.time() - t0))

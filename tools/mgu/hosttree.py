"""Staging tree for a Linux root filesystem on a Windows host (iDrive 7 image build).

macOS and Linux keep the extracted root as a plain folder: the host filesystem stores modes, symlinks and names as they
are, and nothing in this module is used there (MANIFEST is False).

NTFS cannot hold that tree faithfully: it has no execute bits, symlinks need a privilege, names that differ only in case
collide, and some names (`aux`, `a:b`, a trailing dot) are not allowed. On Windows the extractor therefore keeps a
manifest beside the folder (`<root>.meta.json`):

    guest path -> [host path relative to the root, mode, symlink target or None]

Files and folders exist on disk under a Windows-safe name; symlinks exist only in the manifest. `mkext2.py` reads the
manifest back to write the real names, modes and links into the image.
"""
import json, os, re, sys

MANIFEST = sys.platform == 'win32' or bool(os.environ.get('IDEMU_TREE_MANIFEST'))    # the variable is for tests on other systems
_RESERVED = re.compile(r'^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$', re.I)
_BAD = set('<>:"|?*\\%')


def long_path(path):
    """Absolute path with the \\\\?\\ prefix on Windows, so deep guest trees are not cut off at 260 characters."""
    path = os.path.abspath(path)
    if sys.platform == 'win32' and not path.startswith('\\\\'):
        return '\\\\?\\' + path
    return path


def safe_name(name):
    """A file name Windows accepts. Different guest names give different results."""
    out = ''.join('%%%02X' % ord(c) if c in _BAD or ord(c) < 32 else c for c in name)
    if _RESERVED.match(out):
        out = '%%%02X' % ord(out[0]) + out[1:]
    if out.endswith(('.', ' ')):
        out = out[:-1] + '%%%02X' % ord(out[-1])
    return out


def _keys(host_rel):
    """Spellings NTFS could treat as the same name."""
    return {host_rel.upper(), host_rel.lower(), host_rel.casefold()}


class Tree:
    def __init__(self, root):
        self.root = long_path(root)
        self.meta_path = self.root + '.meta.json'
        self.ent = {}                      # guest path -> [host_rel, mode, link]
        self.taken = {}                    # case-insensitive host path -> guest path
        try:
            with open(self.meta_path, encoding='utf-8') as f:
                self.ent = json.load(f)
        except FileNotFoundError:
            pass
        for g, e in self.ent.items():
            for k in _keys(e[0]):
                self.taken[k] = g

    def save(self):
        tmp = self.meta_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.ent, f, separators=(',', ':'))
        os.replace(tmp, self.meta_path)

    # ---- paths ----
    @staticmethod
    def norm(gpath):
        parts = []
        for p in gpath.replace('\\', '/').split('/'):
            if p in ('', '.'):
                continue
            if p == '..':
                if parts: parts.pop()
                continue
            parts.append(p)
        return '/'.join(parts)

    def resolve(self, gpath, follow_last=False, _depth=0):
        """Guest path with the symlinks in its folders followed, as the kernel would on the real filesystem."""
        if _depth > 40:
            raise OSError('too many levels of symbolic links: %s' % gpath)
        parts = self.norm(gpath).split('/') if self.norm(gpath) else []
        cur = ''
        for i, p in enumerate(parts):
            g = cur + '/' + p if cur else p
            e = self.ent.get(g)
            last = i == len(parts) - 1
            if e and e[2] is not None and (not last or follow_last):
                target = e[2]
                base = '' if target.startswith('/') else cur
                rest = '/'.join(parts[i + 1:])
                return self.resolve('/'.join(x for x in (base, target, rest) if x), follow_last, _depth + 1)
            cur = g
        return cur

    def _entry(self, g):
        """Entry of an already resolved guest path, creating it (and its folders) with a free host name."""
        e = self.ent.get(g)
        if e:
            return e
        parent, _, name = g.rpartition('/')
        base = safe_name(name)
        if parent:
            pe = self._entry(parent)
            if pe[1] is None:
                pe[1] = 0o40755
            base = pe[0] + '/' + base
        host, n = base, 1
        while any(self.taken.get(k, g) != g for k in _keys(host)):
            host = '%s%%~%d' % (base, n); n += 1
        for k in _keys(host):
            self.taken[k] = g
        e = self.ent[g] = [host, None, None]
        return e

    def host(self, gpath, follow=True, parents=True):
        """Host path of a guest file or folder; makes the folders above it."""
        g = self.resolve(gpath, follow)
        if not g:
            return self.root
        e = self._entry(g)
        full = os.path.join(self.root, *e[0].split('/'))
        if parents:
            os.makedirs(os.path.dirname(full), exist_ok=True)
        return full

    # ---- entries ----
    def get(self, gpath, follow=False):
        return self.ent.get(self.resolve(gpath, follow))

    def is_link(self, gpath):
        e = self.get(gpath)
        return bool(e and e[2] is not None)

    def set_file(self, gpath, mode, follow=False):
        """Record a regular file (already written at host(gpath, follow)) and its permission bits."""
        g = self.resolve(gpath, follow)
        e = self._entry(g)
        e[1] = 0o100000 | (mode & 0o7777); e[2] = None
        return e

    def mkdir(self, gpath, mode=0o755):
        g = self.resolve(gpath, True)
        if not g:
            os.makedirs(self.root, exist_ok=True)
            return
        e = self._entry(g)
        os.makedirs(os.path.join(self.root, *e[0].split('/')), exist_ok=True)
        if e[1] is None or not e[1] & 0o40000:
            e[1] = 0o40000 | (mode & 0o7777)
        e[2] = None

    def symlink(self, gpath, target):
        """Record a symlink. It has no file on the host."""
        g = self.resolve(gpath, False)
        e = self._entry(g)
        full = os.path.join(self.root, *e[0].split('/'))
        if os.path.isfile(full):
            os.unlink(full)
        e[1] = 0o120777; e[2] = target

    def hardlink(self, gpath, target_gpath):
        """Second name for an existing file: an NTFS hard link when the volume allows it, otherwise a copy."""
        import shutil
        src_e = self.get(target_gpath, True)
        src = self.host(target_gpath)
        dst = self.host(gpath, follow=False)
        if os.path.lexists(dst):
            os.unlink(dst)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
        self.set_file(gpath, (src_e[1] if src_e and src_e[1] else 0o644))

    def detach(self, full):
        """A hard-linked file is about to be replaced under one of its names. The POSIX extractor does chmod 0600 on the
        shared inode first, so the names that keep the old content end up 0600: record the same here."""
        try:
            st = os.lstat(full)
        except OSError:
            return
        if st.st_nlink < 2 or not st.st_ino:
            return
        for e in self.ent.values():
            if e[2] is None and e[1] is not None and e[1] & 0o170000 == 0o100000:
                other = os.path.join(self.root, *e[0].split('/'))
                try:
                    so = os.lstat(other)
                except OSError:
                    continue
                if (so.st_dev, so.st_ino) == (st.st_dev, st.st_ino):
                    e[1] = 0o100600

    # ---- reading back (mkext2) ----
    def children(self):
        """{guest folder: {guest name: [host_rel, mode, link]}} for every entry of the manifest."""
        out = {}
        for g, e in self.ent.items():
            parent, _, name = g.rpartition('/')
            out.setdefault(parent, {})[name] = e
        return out

    def guest_name(self, host_rel):
        """Guest path stored under a host path, or None when the file was created outside the manifest."""
        for k in _keys(host_rel):
            g = self.taken.get(k)
            if g is not None and self.ent[g][0] == host_rel:
                return g
        for k in _keys(host_rel):
            g = self.taken.get(k)
            if g is not None:
                return g
        return None


def open_tree(root):
    """The manifest of an extracted root on Windows, or None where the folder itself is the truth."""
    return Tree(root) if MANIFEST else None


def path(root, rel):
    """Host path of a guest file inside an extracted root (follows guest symlinks on Windows)."""
    if not MANIFEST:
        return os.path.join(root, rel)
    return Tree(root).host(rel, parents=False)

"""iDrive 7 on Windows: the parts that can be checked on any system.

The Linux root of the head unit cannot live on NTFS as plain files, so on Windows the HAR extractor keeps a manifest
(tools/mgu/hosttree.py) and mkext2.py reads it back. IDEMU_TREE_MANIFEST=1 turns that mode on here; the image it gives
must be the one the plain-folder mode (macOS, Linux) gives.
"""
import os, stat, struct, subprocess, sys, tempfile, unittest, zlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TOOLS = os.path.join(ROOT, 'tools', 'mgu')
sys.path.insert(0, TOOLS)
from idemu import mgu7
import hosttree
from ext4ls import E4


def rec(name, mode, data=b'', link=None, magic=False):
    """One HAR record (format in tools/mgu/har.py)."""
    nb = name.encode(); lb = link.encode() if link is not None else b''
    stored = zlib.compress(data) if data else data
    if len(stored) >= len(data): stored = data
    head = bytearray(92)
    struct.pack_into('<I', head, 4, (len(lb) << 16) | len(nb))
    struct.pack_into('<II', head, 12, len(stored), len(data))
    struct.pack_into('<I', head, 60, mode)
    pad = b'' if (lb and mode & 0xF000 == 0x8000) else bytes(28)
    return (b'HAR#$%&@' + bytes(56) if magic else b'') + bytes(head) + nb + lb + pad + stored


def har(path, recs):
    with open(path, 'wb') as f: f.write(bytes(0x200) + b''.join(recs) + bytes(256))


PACKAGE_1 = [rec('/manifest', 0o100644, b'm', magic=True),
             rec('/usr', 0o40755), rec('/usr/bin', 0o40755), rec('/usr/lib', 0o40755), rec('/etc', 0o40755),
             rec('/usr/bin/tool', 0o100755, b'#!/bin/sh\n'), rec('/usr/bin/suid', 0o104755, b'x' * 5000),
             rec('/usr/lib/libA.so.1.0', 0o100644, b'A' * 70000), rec('/usr/lib/libA.so.1', 0o120777, link='libA.so.1.0'),
             rec('/usr/lib/libB.so', 0o120777, b'/usr/lib/libA.so.1.0'),                 # symlink with the target as data
             rec('/lib', 0o120777, link='usr/lib'), rec('/lib/libdl-2.27.so', 0o100755, b'DL'),   # written through the /lib symlink
             rec('/usr/bin/tool2', 0o100755, link='/usr/bin/tool'),                      # hard link
             rec('/usr/bin/dangling', 0o100644, link='/nope'),                           # hard link to a missing file
             rec('/etc/xt_DSCP.ko', 0o100644, b'UPPER'), rec('/etc/xt_dscp.ko', 0o100644, b'lower'),
             rec('/etc/E', 0o40755), rec('/etc/e', 0o40755), rec('/etc/E/f', 0o100600, b'EF'), rec('/etc/e/f', 0o100644, b'ef'),
             rec('/etc/aux', 0o100644, b'reserved'), rec('/etc/com1.txt', 0o100644, b'reserved2'),
             rec('/etc/a:b', 0o100644, b'colon'), rec('/etc/dot.', 0o100644, b'dot'), rec('/etc/q?*', 0o100640, b'q'), rec('/etc/100%', 0o100644, b'pct'),
             rec('/etc/long-target', 0o120777, link='/' + 'x' * 100), rec('/etc/empty', 0o100644, b'')]
PACKAGE_2 = [rec('/manifest', 0o100644, b'm2', magic=True), rec('/usr/lib/libB.so', 0o100755, b'now a file'),
             rec('/etc/idemu', 0o40755), rec('/etc/idemu/x.json', 0o100644, b'{}'), rec('/usr/bin/tool', 0o100755, b'#!/bin/sh\necho v2\n')]
EXPECTED = {'manifest': ('f', 0o644, b'm2'), 'usr': ('d', 0o755), 'usr/bin': ('d', 0o755), 'usr/lib': ('d', 0o755), 'etc': ('d', 0o755),
            'usr/bin/tool': ('f', 0o755, b'#!/bin/sh\necho v2\n'), 'usr/bin/suid': ('f', 0o4755, b'x' * 5000),
            'usr/lib/libA.so.1.0': ('f', 0o644, b'A' * 70000), 'usr/lib/libA.so.1': ('l', 'libA.so.1.0'),
            'usr/lib/libB.so': ('f', 0o755, b'now a file'), 'lib': ('l', 'usr/lib'), 'usr/lib/libdl-2.27.so': ('f', 0o755, b'DL'),
            'usr/bin/tool2': ('f', 0o600, b'#!/bin/sh\n'),             # the extractor does chmod 0600 on the shared inode before replacing `tool`
            'usr/bin/dangling': ('l', '/nope'),
            'etc/xt_DSCP.ko': ('f', 0o644, b'UPPER'), 'etc/xt_dscp.ko': ('f', 0o644, b'lower'),
            'etc/E': ('d', 0o755), 'etc/e': ('d', 0o755), 'etc/E/f': ('f', 0o600, b'EF'), 'etc/e/f': ('f', 0o644, b'ef'),
            'etc/aux': ('f', 0o644, b'reserved'), 'etc/com1.txt': ('f', 0o644, b'reserved2'),
            'etc/a:b': ('f', 0o644, b'colon'), 'etc/dot.': ('f', 0o644, b'dot'), 'etc/q?*': ('f', 0o640, b'q'), 'etc/100%': ('f', 0o644, b'pct'),
            'etc/long-target': ('l', '/' + 'x' * 100), 'etc/empty': ('f', 0o644, b''),
            'etc/idemu': ('d', 0o755), 'etc/idemu/x.json': ('f', 0o644, b'{}')}


def listing(image):
    """{path: ('d', mode) | ('l', target) | ('f', mode, data)} of an ext2 image."""
    e = E4(image); out = {}
    def walk(ino, prefix):
        for name, i, ft in e.entries(ino):
            if name in ('.', '..'): continue
            t = e.inode(i); m = e.mode(t); p = prefix + name
            if stat.S_ISDIR(m): out[p] = ('d', m & 0o7777); walk(i, p + '/')
            elif stat.S_ISLNK(m): out[p] = ('l', e.data(t).decode())
            else: out[p] = ('f', m & 0o7777, e.data(t))
    walk(2, '')
    e.f.close()
    return out


def build_image(tmp, manifest):
    env = dict(os.environ)
    env.pop('IDEMU_TREE_MANIFEST', None)
    if manifest: env['IDEMU_TREE_MANIFEST'] = '1'
    root = os.path.join(tmp, 'm' if manifest else 'p', 'root'); image = root + '.img'
    for n, recs in enumerate((PACKAGE_1, PACKAGE_2)):
        pkg = os.path.join(tmp, 'pkg%d.har' % n); har(pkg, recs)
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'har.py'), pkg, root], capture_output=True, text=True, env=env)
        if r.returncode: raise AssertionError(r.stderr)
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'mkext2.py'), root, image, '16'], capture_output=True, text=True, env=env)
    if r.returncode: raise AssertionError(r.stderr)
    return listing(image)


class ManifestImageTest(unittest.TestCase):
    def test_manifest_mode_writes_the_expected_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(build_image(tmp, True), EXPECTED)

    @unittest.skipIf(sys.platform == 'win32', 'the plain-folder mode needs a POSIX filesystem')
    def test_plain_folder_mode_is_unchanged_and_gives_the_same_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = build_image(tmp, False)
            self.assertEqual(plain, EXPECTED)
            self.assertFalse(os.path.exists(os.path.join(tmp, 'p', 'root.meta.json')))       # no manifest outside Windows


class HostTreeTest(unittest.TestCase):
    def test_names_windows_rejects_are_escaped_and_stay_distinct(self):
        names = ['aux', 'AUX.txt', 'com1', 'a:b', 'a?b', 'dot.', 'space ', '100%', 'plain', 'nul.tar.gz', 'a%3Ab']
        safe = [hosttree.safe_name(n) for n in names]
        self.assertEqual(len(set(s.upper() for s in safe)), len(names))
        for s in safe:
            self.assertIsNone(hosttree._RESERVED.match(s), s)
            self.assertFalse(set(s) & set('<>:"|?*\\'), s)
            self.assertFalse(s.endswith(('.', ' ')), s)
        self.assertEqual(hosttree.safe_name('plain'), 'plain')

    def test_names_that_differ_only_in_case_get_separate_host_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = hosttree.Tree(os.path.join(tmp, 'root'))
            a = t.host('lib/xt_DSCP.ko'); b = t.host('lib/xt_dscp.ko')
            self.assertNotEqual(a.upper(), b.upper())
            self.assertEqual(t.host('lib/xt_DSCP.ko'), a)

    def test_writes_follow_guest_symlinks_like_the_real_filesystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = hosttree.Tree(os.path.join(tmp, 'root'))
            t.mkdir('usr/lib'); t.symlink('lib', 'usr/lib'); t.symlink('usr/lib/libEGL.so.1', 'libEGL.so.1.0.0')
            self.assertEqual(t.resolve('lib/systemd/system/x.service'), 'usr/lib/systemd/system/x.service')
            self.assertEqual(t.resolve('lib/libEGL.so.1', True), 'usr/lib/libEGL.so.1.0.0')
            self.assertEqual(t.resolve('lib/libEGL.so.1', False), 'usr/lib/libEGL.so.1')
            t.symlink('abs', '/usr/lib'); self.assertEqual(t.resolve('abs/a'), 'usr/lib/a')
            t.symlink('loop', 'loop')
            with self.assertRaises(OSError): t.resolve('loop/x')


class WindowsRuntimeTest(unittest.TestCase):
    def test_overlay_symlink_table_matches_the_overlay(self):
        """Git for Windows checks the overlay symlinks out as text files; mgu7.OVERLAY_LINKS says which files they are."""
        base = os.path.join(TOOLS, 'rse_overlay'); real = {}
        for dp, dn, fn in os.walk(base):
            for f in fn:
                p = os.path.join(dp, f)
                if os.path.islink(p): real[os.path.relpath(p, base).replace(os.sep, '/')] = os.readlink(p).replace('\\', '/')
        if real:
            self.assertEqual(real, mgu7.OVERLAY_LINKS)
        else:                                            # checkout without symlinks: the placeholder holds the target
            for rel, target in mgu7.OVERLAY_LINKS.items():
                with open(os.path.join(base, rel), 'rb') as f: self.assertEqual(f.read().decode().strip(), target)

    def test_qemu_channels_keep_their_unix_form_and_gain_a_tcp_form(self):
        self.assertEqual(mgu7._chardev('inp', '/run/inp.sock'), 'socket,id=inp,path=/run/inp.sock,server=on,wait=off')
        self.assertEqual(mgu7._monitor('/run/mon.sock'), 'unix:/run/mon.sock,server,nowait')
        self.assertEqual(mgu7._chardev('gl', ('127.0.0.1', 5001)), 'socket,id=gl,host=127.0.0.1,port=5001,server=on,wait=off,nodelay=on')
        self.assertEqual(mgu7._monitor(('127.0.0.1', 5002)), 'tcp:127.0.0.1:5002,server=on,wait=off')

    def test_tools_run_with_python_unless_the_app_is_frozen(self):
        self.assertEqual(mgu7.tool_cmd('har.py'), [sys.executable, '-I', os.path.join(mgu7.TOOLS, 'har.py')])
        sys.frozen = True
        try: self.assertEqual(mgu7.tool_cmd('har.py'), [sys.executable, '--run-tool', os.path.join(mgu7.TOOLS, 'har.py')])
        finally: del sys.frozen

    @unittest.skipIf(sys.platform == 'win32', 'paths of the other systems')
    def test_paths_outside_windows_are_the_original_ones(self):
        self.assertFalse(mgu7.NATIVE)
        self.assertEqual(mgu7.OUT, os.path.join(mgu7.ROOT, 'mgu7'))
        self.assertEqual(mgu7.glhost_path(), os.path.join(mgu7.ROOT, 'bin', 'glhost7'))
        self.assertEqual(mgu7.QEMU_OWN, os.path.join(mgu7.ROOT, 'bin', 'qemu-system-x86_64'))
        self.assertEqual(mgu7._TXT, {})


if __name__ == '__main__':
    unittest.main()

"""Overlay do ambiente (idemu/overlay.py): arquivos do usuário gravados no sda/sdb a cada build."""
import os
import shutil
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import overlay  # noqa: E402
from idemu.qnxfs import mkdisk, mkq6, qnx4  # noqa: E402


def write(path, data=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path


class OverlayTest(unittest.TestCase):
    def setUp(self):
        self.env = tempfile.mkdtemp(prefix='idemu-ov-')
        self.addCleanup(shutil.rmtree, self.env, True)
        self.ov = os.path.join(self.env, 'overlay')

    def test_no_overlay_changes_nothing(self):
        tree = {'bin/ls': '/host/ls'}
        info = overlay.apply_sda(tree, self.env, log=lambda *_: None)
        self.assertEqual(tree, {'bin/ls': '/host/ls'})
        self.assertEqual(info, {'sda': [], 'deleted': []})
        ro = mkq6.N(b'ro', 0o40775)
        self.assertEqual(overlay.apply_sdb(ro, self.env, mkq6, log=lambda *_: None), {'sdb': [], 'deleted': []})
        self.assertEqual(ro.kids, {})

    def test_ensure_creates_layout(self):
        overlay.ensure(self.env)
        for p in ('sda', 'sdb', 'README.txt'):
            self.assertTrue(os.path.exists(os.path.join(self.ov, p)), p)
        self.assertEqual(overlay.status(self.env)['sda'], 0)

    def test_guest_target(self):
        g = overlay.guest_target
        self.assertEqual(g('/var/opt/hmi/data/ID5/plugins/a.so'), ('sda', 'var/opt/hmi/data/ID5/plugins/a.so'))
        self.assertEqual(g('/fs/sda0/repository/istep/opt/x'), ('sda', 'opt/x'))
        self.assertEqual(g('/opt/hmi/ID5/data/ro/id5/x'), ('sdb', 'id5/x'))
        self.assertEqual(g('/opt/hmi/data/ro/y'), ('sdb', 'y'))
        self.assertEqual(g('/fs/sdb0/ro/z'), ('sdb', 'z'))
        self.assertEqual(g('\\var\\..\\etc\\hosts'), ('sda', 'etc/hosts'))
        self.assertIsNone(g('/'))

    def test_sda_add_replace_delete_and_guards(self):
        plug = write(os.path.join(self.ov, 'sda', 'var', 'opt', 'hmi', 'data', 'ID5', 'plugins', 'my.so'), b'\x7fELF')
        rep = write(os.path.join(self.ov, 'sda', 'etc', 'hosts'), b'127.0.0.1 hu\n')
        write(os.path.join(self.ov, 'sda', 'opt', 'hmi', 'ID5', 'data', 'ro', 'wrong.bin'))
        write(os.path.join(self.ov, 'sda', 'opt', 'x' * 49))
        write(os.path.join(self.ov, 'sda', '.DS_Store'))
        with open(os.path.join(self.ov, 'delete.txt'), 'w') as f:
            f.write('# comentário\n/opt/sys/bin\n/fs/sda0/repository/istep/etc/motd  # inline\n/opt/hmi/ID5/data/ro/id5/big.zip\n')
        tree = {'etc/hosts': '/swfl/hosts', 'etc/motd': '/swfl/motd', 'opt/sys/bin/a': '/swfl/a', 'opt/sys/bin/b': '/swfl/b', 'opt/sys/binx': '/swfl/binx'}
        info = overlay.apply_sda(tree, self.env, log=lambda *_: None)
        self.assertEqual(tree, {'etc/hosts': rep, 'opt/sys/binx': '/swfl/binx', 'var/opt/hmi/data/ID5/plugins/my.so': plug})
        self.assertEqual(sorted(info['sda']), ['etc/hosts', 'var/opt/hmi/data/ID5/plugins/my.so'])
        self.assertEqual([d['files'] for d in info['deleted']], [2, 1])

    def test_sdb_add_replace_delete(self):
        ro = mkq6.N(b'ro', 0o40775)
        id5 = mkq6.N(b'id5', 0o40775); ro.kids[b'id5'] = id5
        id5.kids[b'big.zip'] = mkq6.N(b'big.zip', 0o100644, '/swfl/big.zip', 10)
        id5.kids[b'cfg.xml'] = mkq6.N(b'cfg.xml', 0o100644, '/swfl/cfg.xml', 10)
        new_cfg = write(os.path.join(self.ov, 'sdb', 'id5', 'cfg.xml'), b'<x/>')
        write(os.path.join(self.ov, 'sdb', 'new', 'deep', 'run.sh'), b'#!/bin/ksh\n')
        with open(os.path.join(self.ov, 'delete.txt'), 'w') as f:
            f.write('/opt/hmi/ID5/data/ro/id5/big.zip\n/fs/sdb0/ro/missing\n')
        info = overlay.apply_sdb(ro, self.env, mkq6, log=lambda *_: None)
        self.assertNotIn(b'big.zip', id5.kids)
        self.assertEqual(id5.kids[b'cfg.xml'].src, new_cfg)
        self.assertEqual(ro.kids[b'new'].kids[b'deep'].kids[b'run.sh'].mode, 0o100755)
        self.assertEqual([d['found'] for d in info['deleted']], [True, False])

    def test_sdb_image_builds(self):
        write(os.path.join(self.ov, 'sdb', 'plug', 'a.bin'), b'A' * 5000)
        root = mkq6.N(b'/', 0o40775); ro = mkq6.N(b'ro', 0o40775); root.kids[b'ro'] = ro
        overlay.apply_sdb(ro, self.env, mkq6, log=lambda *_: None)
        tpl = os.path.join(self.env, 'tpl.img')
        with open(os.path.join(ROOT, 'idemu', 'qnxfs', 'q6_template.img.z'), 'rb') as f, open(tpl, 'wb') as o:
            o.write(zlib.decompress(f.read()))
        out = os.path.join(self.env, 'sdb.img')
        mkq6.build(root, tpl, out)
        self.assertGreater(os.path.getsize(out), 0)

    def test_sda_image_contains_plugin(self):
        """Ponta a ponta no QNX4 como o builder faz (pastas + /repository/istep/...): o arquivo do overlay sai igual na imagem."""
        data = b'\x7fELF' + os.urandom(3000)
        write(os.path.join(self.ov, 'sda', 'var', 'opt', 'hmi', 'data', 'ID5', 'plugins', 'my.so'), data)
        tree = {}
        overlay.apply_sda(tree, self.env, log=lambda *_: None)
        t = mkdisk.Tree(); base = '/repository/istep/'
        t.mkdir('/repository', 0o40775); t.mkdir('/repository/istep', 0o40775)
        dirs = sorted({'/'.join(r.split('/')[:i]) for r in tree for i in range(1, len(r.split('/')))})
        for d in dirs:
            t.mkdir(base + d, 0o40775)
        for rel, p in tree.items():
            t.add(base + rel, overlay.exec_mode(p), p, os.path.getsize(p))
        img = os.path.join(self.env, 'sda.img')
        mkdisk.write(t, img, 8192)
        r = qnx4.R(img)
        found = {p: x for p, x in r.walk()}
        x = found['/repository/istep/var/opt/hmi/data/ID5/plugins/my.so']
        self.assertEqual(r.read(x), data)
        self.assertEqual(x['mode'] & 0o777, 0o755)


if __name__ == '__main__':
    unittest.main()

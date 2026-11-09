"""iDrive 8: partes que não precisam do firmware."""
import os, struct, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import mgu


class CpioTest(unittest.TestCase):
    def test_entries_are_aligned_and_terminated(self):
        d = mgu._cpio([('idemu', 0o40755, b''), ('idemu.sh', 0o100755, b'abc')])
        self.assertEqual(d[:6], b'070701')
        self.assertIn(b'TRAILER!!!', d)
        self.assertEqual(len(d) % 4, 0)
        p = d.index(b'idemu.sh\0')
        self.assertEqual(d[(p + 9 + 3) & ~3:((p + 9 + 3) & ~3) + 3], b'abc')


class DtbTest(unittest.TestCase):
    def test_placeholder_for_initrd_end_exists(self):
        d = open(os.path.join(mgu.TOOLS, 'virt_mgu22.dtb'), 'rb').read()
        self.assertIn(struct.pack('>II', 0xdeadbeef, 0xfeedf00d), d)


class AngleTest(unittest.TestCase):
    def test_env_var_wins(self):
        old = os.environ.get('IDEMU_ANGLE'); os.environ['IDEMU_ANGLE'] = '/x/y'
        try: self.assertEqual(mgu.find_angle(), '/x/y')
        finally:
            if old is None: del os.environ['IDEMU_ANGLE']
            else: os.environ['IDEMU_ANGLE'] = old


class CommandTest(unittest.TestCase):
    def test_input_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = mgu.MguRuntime(tmp, {'id': 'teste-mgu'})
            sent = []; rt.send_cmd = sent.append
            rt.key(7, 1); rt.key(7, 0); rt.rotor(-2); rt.rotor(0)
            rt.touch(10, 20, True); rt.touch(11, 21, True, True); rt.touch(11, 21, False)
            self.assertEqual(sent, ['k 7 1 0 1', 'k 7 0 0 1', 'r -2', 'd 10 20', 'm 11 21', 'u'])

    def test_status_reports_kind_and_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(tmp + '/logs')
            open(tmp + '/logs/console.log', 'wb').write(b'x IDEMU-HMI-EXIT a\nIDEMU-HMI-EXIT b\n')
            rt = mgu.MguRuntime(tmp, {'id': 'teste-mgu'})
            s = rt.status()
            self.assertEqual((s['kind'], s['disp'], s['hmi_exits']), ('mgu22', [2880, 960], 2))


if __name__ == '__main__':
    unittest.main()

"""iDrive 7: partes que não precisam do firmware (quadro RGBA do glhost7, pacotes, overlay)."""
import os, struct, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import mgu7


class FrameTest(unittest.TestCase):
    def rt_with_frame(self, tmp, w, h, seq):
        rt = mgu7.Mgu7Runtime(tmp, {'id': 'teste-mgu7'}); os.makedirs(rt.run, exist_ok=True)
        px = b''.join(bytes([x % 251, (x * 3) % 251, (x * 7) % 251, 255]) for x in range(w * h))
        open(rt.frame_path, 'wb').write(struct.pack('<iii', w, h, seq) + b'\0' * 52 + px)
        return rt, px

    def test_frame_rgba_to_rgb(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, px = self.rt_with_frame(tmp, 4, 3, 7)
            self.assertEqual(rt.frame_seq(), 7)
            seq, w, h, rgb = rt.frame_bytes()
            self.assertEqual((seq, w, h, len(rgb)), (7, 4, 3, 36))
            self.assertEqual(rgb[:6], px[0:3] + px[4:7])
            png, s = rt.screen_png(); self.assertEqual((png[:8], s), (b'\x89PNG\r\n\x1a\n', 7))

    def test_no_frame_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = mgu7.Mgu7Runtime(tmp, {'id': 'x'})
            self.assertEqual((rt.frame_seq(), rt.frame_bytes(), rt.screen_png()), (0, None, (None, 0)))

    def test_status_kind_and_input_without_vm(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = mgu7.Mgu7Runtime(tmp, {'id': 'x'}); rt.key(1, 1); rt.rotor(2); rt.touch(1, 2, True)      # sem a VM, nada a enviar
            s = rt.status(); self.assertEqual((s['kind'], s['disp']), ('mgu7', [1920, 720]))


class TouchTest(unittest.TestCase):
    """O toque vira linhas "d X Y" / "m X Y" / "u" na serial de entrada (ttyS0 do guest), lidas pelo idemu-wl (src/mgu/wlstub.c)."""
    def rt_with_socket(self, tmp):
        import socket
        rt = mgu7.Mgu7Runtime(tmp, {'id': 'x'}); a, b = socket.socketpair(); rt._inp = a
        return rt, b

    def lines(self, b):
        b.settimeout(0.5); out = b''
        try:
            while True:
                d = b.recv(4096)
                if not d: break
                out += d
        except Exception: pass
        return out.decode().split()

    def test_down_move_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, b = self.rt_with_socket(tmp)
            rt.touch(100, 200, True); rt.touch(110, 210, True, move=True); rt.touch(110, 210, False)
            self.assertEqual(self.lines(b), ['d', '100', '200', 'm', '110', '210', 'u'])

    def test_coordinates_are_clamped_to_the_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, b = self.rt_with_socket(tmp)
            rt.touch(-5, 99999, True)
            self.assertEqual(self.lines(b), ['d', '0', '719'])           # tela central: 1920x720

    def test_quick_tap_is_held_for_a_moment(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            rt, b = self.rt_with_socket(tmp)
            t0 = time.time(); rt.touch(1, 1, True); rt.touch(1, 1, False)
            self.assertGreaterEqual(time.time() - t0, 0.08)

    def test_controller_keys_and_rotor_become_linux_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, b = self.rt_with_socket(tmp)
            rt.key(8, 1); rt.key(8, 0); rt.key(12, 1); rt.key(5, 1)            # PUSH = Espaço (57), inclinar à direita = seta (106); MAP não tem tecla
            rt.rotor(2); rt.rotor(-1); rt.key(1058, 1)                            # giro: M (50) duas vezes, N (49) uma; código cru 1058 = tecla 58
            self.assertEqual(self.lines(b), ['k', '57', '1', 'k', '57', '0', 'k', '106', '1', 'k', '50', '1', 'k', '50', '0', 'k', '50', '1', 'k', '50', '0', 'k', '49', '1', 'k', '49', '0', 'k', '58', '1'])

    def test_closed_socket_is_dropped_quietly(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, b = self.rt_with_socket(tmp); b.close(); rt._inp.close()
            rt.touch(1, 1, True); self.assertIsNone(rt._inp)


class PatchTest(unittest.TestCase):
    def test_hmi_patches_target_the_expected_bytes(self):
        import subprocess
        src = open(os.path.join(mgu7.TOOLS, 'patch_rse.py')).read()
        self.assertIn('HMI_PATCHES', src)
        ns = {}
        exec(compile(src.split('root = sys.argv[1]')[0], 'patch_rse.py', 'exec'), ns)
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'usr', 'bin'))
            hmi = bytearray(b'\x90' * 0x6e87800)                       # arquivo falso com os bytes originais nas posições dos patches
            for rel, off, old, new in ns['HMI_PATCHES']:
                self.assertEqual(len(old), len(new)); hmi[off:off + len(old)] = old
            open(os.path.join(tmp, 'usr', 'bin', 'HmiMain3D'), 'wb').write(hmi)
            for rel in ('usr/bin/ioclcproxy', 'usr/bin/udpnm'):
                d = bytearray(b'\0' * (max(ns['PATCHES'][rel]) + 16))
                for o in ns['PATCHES'][rel]: d[o:o + 4] = bytes.fromhex('4883ec28')
                open(os.path.join(tmp, rel), 'wb').write(d)
            r = subprocess.run([sys.executable, '-I', os.path.join(mgu7.TOOLS, 'patch_rse.py'), tmp], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = open(os.path.join(tmp, 'usr', 'bin', 'HmiMain3D'), 'rb').read()
            for rel, off, old, new in ns['HMI_PATCHES']: self.assertEqual(out[off:off + len(new)], new)
            r = subprocess.run([sys.executable, '-I', os.path.join(mgu7.TOOLS, 'patch_rse.py'), tmp], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)                                  # já alterado: os bytes não batem mais


class PackagesTest(unittest.TestCase):
    def test_pick_prefers_requested_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, 'swe', 'swfl'); os.makedirs(d)
            for v in ('001_001_001', '030_016_002', '036_010_004'): open(os.path.join(d, 'swfl_0000567a.bin.' + v), 'w').close()
            self.assertTrue(mgu7.pick(tmp, '0000567a', '030_016_002').endswith('030_016_002'))
            self.assertTrue(mgu7.pick(tmp, '0000567a', '999_999_999').endswith('036_010_004'))
            with self.assertRaises(RuntimeError): mgu7.pick(tmp, '0000ffff')

    def test_guest_files_and_overlay_exist(self):
        for f in mgu7.GUEST_FILES: self.assertTrue(os.path.isfile(os.path.join(mgu7.GUEST, f)), f)
        for f in ('fstab_dummy',): pass
        self.assertTrue(os.path.isfile(os.path.join(mgu7.TOOLS, 'rse_overlay', 'etc', 'fstab')))
        self.assertTrue(os.path.isfile(os.path.join(mgu7.TOOLS, 'idemu-init.sh')))
        self.assertTrue(os.path.isfile(mgu7.glhost_path()))


class RoleTest(unittest.TestCase):
    def test_default_is_central_screen_and_rse_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.pop('IDEMU_MGU7_ROLE', None)
            try:
                rt = mgu7.Mgu7Runtime(tmp, {'id': 'x'}); self.assertEqual((rt.role, rt.disp), ('hu', (1920, 720)))
                rt = mgu7.Mgu7Runtime(tmp, {'id': 'x', 'role': 'rse'}); self.assertEqual((rt.role, rt.disp), ('rse', (1920, 1080)))
            finally:
                if old is not None: os.environ['IDEMU_MGU7_ROLE'] = old

    def test_create_stores_role(self):
        from idemu import server, catalog
        with tempfile.TemporaryDirectory() as tmp:
            old = (server.ENVS, catalog.psdz_ok, catalog.load_settings, catalog.packages_ok)
            server.ENVS = os.path.join(tmp, 'environments'); os.makedirs(server.ENVS)
            catalog.psdz_ok = lambda p: True; catalog.packages_ok = lambda k: True; catalog.load_settings = lambda: {'psdz_path': tmp}
            try:
                app = server.App()
                self.assertEqual(app.create({'kind': 'mgu7', 'name': 'a'})['role'], 'hu')
                e = app.create({'kind': 'mgu7', 'name': 'b', 'role': 'rse'}); self.assertEqual((e['role'], e['coding']['display']), ('rse', '1920x1080'))
                with self.assertRaises(server.ApiError): app.create({'kind': 'mgu7', 'name': 'c', 'role': 'x'})
            finally: server.ENVS, catalog.psdz_ok, catalog.load_settings, catalog.packages_ok = old


class FakeServicesTest(unittest.TestCase):
    """tools/mgu/gen_fakesvc.py: tabela dos serviços SOME/IP falsos do head unit (lida por idemu-fakesvc)."""
    DB = {'version': '0.1.0', 'instanceIDs': {'a.b.Svc': {'Front': 1}, 'a.b.Other': {'1': 1}},
          'datatypes': {'t.Mode': {'type': 'enum', 'enumWidth': 1, 'items': {'ON': 99, 'OFF': 0}, 'name': 'Mode'},
                        't.Wide': {'type': 'enum', 'enumWidth': 2, 'defaultValue': 65535, 'items': {'X': 1}, 'name': 'Wide'},
                        't.St': {'type': 'struct', 'name': 'St', 'members': [{'dataRef': 'UInt8', 'name': 'crc'}, {'dataRef': 'UInt8', 'bitWidth': 4, 'defaultValue': 15, 'name': 'a'},
                                                                          {'dataRef': 'UInt8', 'bitWidth': 4, 'defaultValue': 2, 'name': 'b'}, {'dataRef': 'UInt32', 'defaultValue': 2147483647, 'name': 'n'},
                                                                          {'dataRef': 't.Wide', 'name': 'w'}]}},
          'interfaces': {'a.b.Svc': {'name': 'Svc', 'serviceId': 0xb015, 'version': {'major': 1, 'minor': 2}, 'events': {}, 'methods': {},
                                     'fields': {'mode': {'dataRef': 't.Mode', 'getter': {'id': 22}, 'setter': {'id': 38}, 'notifier': {'id': 32774, 'eventgroups': [3]}},
                                                'st': {'dataRef': 't.St', 'getter': {'id': 17}}}},
                         'a.b.Other': {'name': 'Other', 'serviceId': 0x1531, 'version': {'major': 1, 'minor': 0}, 'events': {}, 'methods': {}, 'fields': {'flag': {'dataRef': 'Bool', 'notifier': {'id': 32769, 'eventgroups': [1]}}}}}}

    def gen(self, *args):
        import json, subprocess
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, 'i.json'), os.path.join(tmp, 'o.tab'); json.dump(self.DB, open(src, 'w'))
            r = subprocess.run([sys.executable, '-I', os.path.join(mgu7.TOOLS, 'gen_fakesvc.py'), src, dst] + list(args), capture_output=True, text=True)
            return r.returncode, (open(dst).read().splitlines() if r.returncode == 0 else r.stderr)

    def test_table_layout_and_serialization(self):
        rc, lines = self.gen('Svc')
        self.assertEqual(rc, 0)
        self.assertEqual(lines[0], 'S b015 1 1 2 Svc/Front')
        self.assertEqual(lines[1], 'F 22 38 8006 3 00 mode')                       # enum de 1 byte: primeiro item
        self.assertEqual(lines[2], 'F 17 - - - 00f2' + '7fffffff' + 'ffff st'.replace(' st', '') + ' st')   # crc, bits 15|2, UInt32, enum de 2 bytes (valor padrão)

    def test_override_and_select_by_id(self):
        rc, lines = self.gen('0x1531', 'Svc=mode=63')
        self.assertEqual(rc, 0); self.assertIn('S 1531 1 1 0 Other/1', lines); self.assertIn('F - - 8001 1 00 flag', lines); self.assertIn('F 22 38 8006 3 63 mode', lines)

    def test_unknown_interface_fails(self):
        rc, err = self.gen('Nada'); self.assertNotEqual(rc, 0)

    def test_allow_offers_patches_user_policy_and_global(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(tmp + '/etc/idemu'); os.makedirs(tmp + '/etc/vsomeip/10007_10007')
            open(tmp + '/etc/idemu/fakesvc.tab', 'w').write('S b015 1 1 2 Svc/Front\nF 22 - - - 00 x\nS 5535 1 1 0 Key/1\n')
            pol = {'security': {'policies': [{'allow': {'offers': [{'instance': 'any', 'service': '0xb016'}], 'requests': []}, 'credentials': {'gid': '10007', 'uid': '10007'}}]}}
            json.dump(pol, open(tmp + '/etc/vsomeip/10007_10007/vsomeip_security.json', 'w'))
            json.dump({'security': {'policies': [{'credentials': {'gid': '5000', 'uid': '5000'}, 'allow': {}}]}}, open(tmp + '/etc/vsomeip/vsomeip_security.json', 'w'))
            mgu7.allow_fake_offers(tmp, 10007); mgu7.allow_fake_offers(tmp, 10007)       # idempotente
            for f in ('/etc/vsomeip/10007_10007/vsomeip_security.json', '/etc/vsomeip/vsomeip_security.json'):
                pols = [p for p in json.load(open(tmp + f))['security']['policies'] if str(p['credentials']['uid']) == '10007']
                self.assertEqual(len(pols), 1)
                self.assertEqual([o['service'] for o in pols[0]['allow']['offers']], ['0xb016', '0xb015', '0x5535'])
            self.assertEqual(len(json.load(open(tmp + '/etc/vsomeip/vsomeip_security.json'))['security']['policies']), 2)


if __name__ == '__main__':
    unittest.main()

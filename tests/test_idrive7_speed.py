"""iDrive 7: boot rápido (snapshot), canal gráfico em memória compartilhada, relógio rápido e editor de codificação. Nada aqui precisa do firmware nem da VM."""
import json, os, re, struct, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from idemu import coding7, mgu7, server


def tiny_dictionary():
    """Um coding7.json pequeno, no formato que tools/mgu/gen_coding7.py grava: duas áreas, parâmetros de 1 byte, de vários bytes e numéricos."""
    def blob(n, fill=0): return bytes([fill]) * n
    hu = bytearray(blob(2172)); hu[2 + 0] = 0x20                                  # área 0 (posição 0): GETRIEBETYP = 1 (máscara 0x60) na fábrica
    rse = bytearray(blob(2178))
    return {'version': 1,
            'areas': [{'id': 0x3000, 'name': 'HMI_SPEECH', 'hu': [0, 151], 'rse': [0, 158]}, {'id': 0x3004, 'name': 'SYSTEM_CONFIGURATION', 'hu': [601, 150], 'rse': [608, 150]}],
            'blob': {'hu': bytes(hu).hex(), 'rse': bytes(rse).hex()},
            'params': [
                {'name': 'GETRIEBETYP', 'area': 0x3000, 'start': 2, 'end': 2, 'mask': 0x60, 'vals': [[0, 'nicht_aktiv'], [1, 'handschalter'], [2, 'automatik']]},
                {'name': 'CID_TOUCH', 'area': 0x3004, 'start': 5, 'end': 5, 'mask': 0x01, 'vals': [[0, 'nicht_aktiv'], [1, '']]},
                {'name': 'RANGE_MAX', 'area': 0x3000, 'start': 1, 'end': 1, 'mask': 0x0f, 'vals': [[0, '1200'], [3, '800']]},
                {'name': 'VAR_CAM_POSITION_X', 'area': 0x3000, 'start': 89, 'end': 90, 'mask': 0xff, 'vals': []},          # 2 bytes: não editável
                {'name': 'OUTRA_AREA', 'area': 0x3012, 'start': 3, 'end': 3, 'mask': 0x01, 'vals': []},                      # área sem posição no HU/RSE: não editável
                {'name': 'SEM_MASCARA', 'area': 0x3000, 'start': 4, 'end': 4, 'mask': 0, 'vals': []}]}


class CodingBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'coding7.json'); json.dump(tiny_dictionary(), open(self.path, 'w'))
        self._old = coding7.path; coding7.path = lambda: self.path; coding7._cache.clear()
        self.addCleanup(lambda: (setattr(coding7, 'path', self._old), coding7._cache.clear()))
        self.env = {'id': 'x', 'kind': 'mgu7', 'role': 'hu', 'coding': {}}


class Coding7Test(CodingBase):
    def test_only_single_byte_parameters_with_a_position_are_editable(self):
        names = set(coding7.fields(self.env))
        self.assertEqual(names, {'GETRIEBETYP', 'CID_TOUCH', 'RANGE_MAX'})

    def test_describe_has_factory_value_options_and_groups(self):
        d = coding7.describe(self.env, self.tmp.name); P = {p['name']: p for p in d['params']}
        self.assertEqual((P['GETRIEBETYP']['factory'], P['GETRIEBETYP']['value'], P['GETRIEBETYP']['coded']), (1, 1, False))
        self.assertEqual([o['value'] for o in P['GETRIEBETYP']['options']], [0, 1, 2])
        self.assertEqual(P['GETRIEBETYP']['options'][1]['label'], 'Manual')               # va_GETRIEBETYP_handschalter
        self.assertEqual(P['CID_TOUCH']['options'][1]['label'], 'Active')                 # valor sem sufixo = o próprio parâmetro ligado
        self.assertEqual((P['RANGE_MAX']['bits'], P['RANGE_MAX']['max']), (4, 15))
        self.assertEqual({g['id'] for g in d['groups']}, {'HMI_SPEECH', 'SYSTEM_CONFIGURATION'})

    def test_apply_builds_the_block_bits_and_nothing_else(self):
        self.assertIsNone(coding7.build_blob(self.env))                                    # sem mudanças: o HMI usa a codificação padrão dele
        done = coding7.apply_changes(self.env, {'CID_TOUCH': 1, 'GETRIEBETYP': 2, 'RANGE_MAX': 3})
        self.assertEqual({n for n, _, _ in done}, {'CID_TOUCH', 'GETRIEBETYP', 'RANGE_MAX'})
        blob = coding7.build_blob(self.env); self.assertEqual(len(blob), 2172)
        self.assertEqual(blob[601 + 5], 0x01)                                              # CID_TOUCH: bit 0 do byte 5 da área em 601
        self.assertEqual(blob[2], 0x40)                                                    # GETRIEBETYP = 2 -> bits 5 e 6 = 10b
        self.assertEqual(blob[1], 0x03)                                                    # RANGE_MAX = 3 (nibble baixo)
        self.assertEqual(sum(1 for b in blob if b), 3)

    def test_rse_uses_its_own_layout(self):
        env = dict(self.env, role='rse'); coding7.apply_changes(env, {'CID_TOUCH': 1})
        blob = coding7.build_blob(env); self.assertEqual((len(blob), blob[608 + 5]), (2178, 1))

    def test_value_equal_to_factory_is_not_stored_and_none_resets(self):
        coding7.apply_changes(self.env, {'GETRIEBETYP': 1}); self.assertEqual(self.env['coding']['extra'], {})
        coding7.apply_changes(self.env, {'CID_TOUCH': 1}); self.assertEqual(self.env['coding']['extra'], {'CID_TOUCH': 1})
        coding7.apply_changes(self.env, {'CID_TOUCH': None}); self.assertEqual(self.env['coding']['extra'], {})

    def test_by_label_and_invalid_values(self):
        coding7.apply_changes(self.env, {'GETRIEBETYP': 'automatik'}); self.assertEqual(self.env['coding']['extra'], {'GETRIEBETYP': 2})
        for bad in ({'GETRIEBETYP': 4}, {'CID_TOUCH': 2}, {'CID_TOUCH': 'talvez'}, {'NAO_EXISTE': 1}, {'VAR_CAM_POSITION_X': 1}):
            with self.assertRaises(ValueError): coding7.apply_changes(dict(self.env), bad)

    def test_serial_lines_fit_the_guest_line_buffer(self):
        coding7.apply_changes(self.env, {'CID_TOUCH': 1}); lines = coding7.serial_lines(coding7.build_blob(self.env))
        self.assertEqual(lines[-1], 'c end'); self.assertEqual(len(lines), 2172 // 64 + 1 + 1)
        self.assertTrue(all(len(l) < 200 for l in lines))                                  # wlstub.c descarta linhas com mais de 200 bytes
        data = bytearray()
        for l in lines[:-1]:
            _, off, hx = l.split(); self.assertEqual(int(off, 16), len(data)); data += bytes.fromhex(hx)
        self.assertEqual(bytes(data), coding7.build_blob(self.env))

    def test_default_touch_coding_exists_for_a_new_central_screen(self):
        self.assertTrue({'CID_TOUCH', 'ZBE_TOUCH'} <= set(coding7.DEFAULT_HU))


class Generator(unittest.TestCase):
    def test_area_table_is_contiguous_and_matches_the_hmi_layout(self):
        sys.path.insert(0, os.path.join(ROOT, 'tools', 'mgu')); import gen_coding7
        end = 0
        for a, name, hu, rse in gen_coding7.AREAS:
            self.assertEqual(hu[0], end + (10 if a == 0x3010 else 0), name); end = hu[0] + hu[1]      # cada área começa onde a anterior termina (a 0x300f, DUMMY, ocupa 10 bytes sem classe)
            self.assertGreaterEqual(rse[0], hu[0], name)
        self.assertEqual(end, gen_coding7.SIZE_HU)
        self.assertEqual(gen_coding7.AREAS[-1][3][0] + gen_coding7.AREAS[-1][3][1], gen_coding7.SIZE_RSE)

    def test_labels_cover_every_area(self):
        sys.path.insert(0, os.path.join(ROOT, 'tools', 'mgu')); import gen_coding7
        for _, name, _, _ in gen_coding7.AREAS: self.assertIn(name, coding7.AREA_LABELS)


class RingProtocol(unittest.TestCase):
    """O Python lê o cabeçalho do anel pelos deslocamentos de proto.h: se a estrutura mudar, isto avisa."""
    def offsets(self):
        src = open(os.path.join(ROOT, 'src', 'mgu', 'proto.h')).read(); body = src[src.index('struct shm_hdr {'):src.index('};', src.index('struct shm_hdr {'))]
        off, out = 0, {}
        for m in re.finditer(r'(unsigned char|unsigned long long|unsigned int)\s+([^;]+);', body):
            t, names = m.group(1), m.group(2)
            for n in names.split(','):
                n = n.strip(); arr = re.match(r'(\w+)\[(\d+)\]', n); size = {'unsigned char': 1, 'unsigned long long': 8, 'unsigned int': 4}[t]
                cnt = int(arr.group(2)) if arr else 1; name = arr.group(1) if arr else n
                if size > 1 and off % size: off += size - off % size
                out[name] = off; off += size * cnt
        return out, off

    def test_header_offsets(self):
        o, total = self.offsets()
        self.assertEqual((o['magic'], o['epoch'], o['g_start'], o['host_idle']), (0, 4, 8, 16))
        self.assertEqual((o['g_tail'], o['g_head'], o['h_tail'], o['h_head']), (56, 120, 184, 248))     # os mesmos de Mgu7Runtime._ring_idle
        self.assertLessEqual(total, 4096)

    def test_python_reads_the_same_offsets(self):
        src = open(os.path.join(ROOT, 'idemu', 'mgu7.py')).read()
        self.assertIn("struct.unpack_from('<Q', m, 56)", src); self.assertIn("struct.unpack_from('<Q', m, 120)", src)

    def test_sizes_are_consistent(self):
        h = open(os.path.join(ROOT, 'src', 'mgu', 'proto.h')).read()
        g = int(re.search(r'#define G_SIZE\s+\((\d+)u << 20\)', h).group(1)) << 20; r = int(re.search(r'#define H_SIZE\s+\((\d+)u << 20\)', h).group(1)) << 20
        s = int(re.search(r'#define SHM_SIZE\s+\((\d+)u << 20\)', h).group(1)) << 20
        self.assertEqual(s, mgu7.SHM_BYTES); self.assertTrue(g & (g - 1) == 0 and r & (r - 1) == 0)
        self.assertLessEqual(4096 + g + r, s)


class GuestFilesTest(unittest.TestCase):
    def test_fast_clock_library_is_shipped_and_exports_the_clock_functions(self):
        p = os.path.join(mgu7.GUEST, 'libfastclock.so'); d = open(p, 'rb').read()
        self.assertEqual(d[:4], b'\x7fELF'); self.assertEqual(struct.unpack_from('<H', d, 18)[0], 62)       # x86-64
        self.assertIn(b'clock_gettime', d); self.assertIn(b'gettimeofday', d); self.assertNotIn(b'libc.so', d)  # sem dependências
        self.assertEqual(mgu7.GUEST_FILES['libfastclock.so'], 'usr/lib/idemu/libfastclock.so')

    def test_init_script_is_valid_shell_and_has_no_long_fixed_sleeps(self):
        p = os.path.join(mgu7.TOOLS, 'idemu-init.sh')
        self.assertEqual(subprocess.run(['sh', '-n', p], capture_output=True).returncode, 0)
        src = open(p).read()
        self.assertEqual(re.findall(r'^\s*sleep\s+(\d+)\s*$', src, re.M), ['5'])                  # só o laço do relógio do cluster
        for mark in ('== wl ready', 'idemu.coding=1', '== coding applied', 'libfastclock.so', 'resource0'):
            self.assertIn(mark, src)
        self.assertLess(src.index('== wl ready'), src.index('== coding applied'), 'a codificação só entra depois do compositor ler a serial')
        self.assertLess(src.index('== coding applied'), src.index('st hmi'), 'o HMI começa depois de a codificação estar na memória compartilhada')

    def test_stamp_changes_with_the_guest_sources_and_gates_image_ready(self):
        a = mgu7.guest_stamp(); self.assertEqual(a, mgu7.guest_stamp())
        with tempfile.TemporaryDirectory() as tmp:
            old = mgu7.OUT; mgu7.OUT = tmp
            try:
                open(os.path.join(tmp, 'root.img'), 'wb').close(); open(os.path.join(tmp, 'bzImage'), 'wb').close()
                self.assertFalse(mgu7.image_ready())                                             # sem carimbo: imagem velha, refazer
                open(os.path.join(tmp, 'stamp'), 'w').write('outro'); self.assertFalse(mgu7.image_ready())
                open(os.path.join(tmp, 'stamp'), 'w').write(a); self.assertTrue(mgu7.image_ready())
            finally: mgu7.OUT = old


class SnapshotTest(unittest.TestCase):
    """Boot rápido: o snapshot só vale com o mesmo QEMU, a mesma imagem, o mesmo papel e a mesma codificação."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.q = os.path.join(self.tmp.name, 'qemu'); open(self.q, 'wb').write(b'qemu v1')
        self._o = (mgu7.find_qemu, mgu7.qemu_img, mgu7.has_shm)
        mgu7.find_qemu = lambda: self.q; mgu7.qemu_img = lambda: '/bin/true'; mgu7.has_shm = lambda q: True
        self.addCleanup(lambda: (setattr(mgu7, 'find_qemu', self._o[0]), setattr(mgu7, 'qemu_img', self._o[1]), setattr(mgu7, 'has_shm', self._o[2])))
        self.env = {'id': 'snap', 'kind': 'mgu7', 'role': 'hu', 'coding': {'extra': {'CID_TOUCH': 1}}}

    def rt(self, **env):
        rt = mgu7.Mgu7Runtime(self.tmp.name, dict(self.env, **env)); return rt

    def save(self, rt):
        os.makedirs(rt.snap_dir, exist_ok=True)
        for f in ('disk.qcow2', 'gl.rec'): open(os.path.join(rt.snap_dir, f), 'wb').write(b'x' * 10)
        json.dump(rt.snap_stamps(), open(os.path.join(rt.snap_dir, 'meta.json'), 'w'))

    def test_valid_when_everything_matches(self):
        rt = self.rt(); self.assertFalse(rt.snap_valid()); self.save(rt)
        self.assertTrue(rt.snap_valid()); i = rt.snapshot_info(); self.assertEqual((i['valid'], i['enabled'], i['size'] > 0), (True, True, True))

    def test_invalidated_by_coding_role_qemu_image_or_switch(self):
        rt = self.rt(); self.save(rt)
        self.assertFalse(self.rt(coding={'extra': {'CID_TOUCH': 0}}).snap_valid())            # codificação mudou
        self.assertFalse(self.rt(role='rse').snap_valid())                                   # outra tela
        self.assertFalse(self.rt(fast_boot=False).snap_valid())                              # o usuário desligou o boot rápido
        open(self.q, 'wb').write(b'qemu v2 maior'); self.assertFalse(self.rt().snap_valid())  # outro QEMU
        open(self.q, 'wb').write(b'qemu v1'); os.utime(self.q, (1, 1)); self.assertFalse(self.rt().snap_valid())
        os.utime(self.q, None); self.save(rt); os.unlink(os.path.join(rt.snap_dir, 'gl.rec')); self.assertFalse(rt.snap_valid())     # arquivo faltando

    def test_drop_snapshot(self):
        rt = self.rt(); self.save(rt); rt.drop_snapshot(); self.assertFalse(os.path.exists(rt.snap_dir))

    def test_off_without_the_own_qemu_or_qemu_img(self):
        rt = self.rt(); self.save(rt); mgu7.qemu_img = lambda: None; self.assertFalse(rt.snap_valid())

    def test_has_shm_needs_the_own_qemu_and_firmware(self):
        mgu7.has_shm = self._o[2]
        self.assertFalse(mgu7.has_shm('/usr/bin/true'))
        old = os.environ.get('IDEMU_NO_SHM'); os.environ['IDEMU_NO_SHM'] = '1'
        try: self.assertFalse(mgu7.has_shm(mgu7.QEMU_OWN))
        finally:
            if old is None: os.environ.pop('IDEMU_NO_SHM')
            else: os.environ['IDEMU_NO_SHM'] = old

    def test_server_reports_snapshot_info_for_idrive7(self):
        env = dict(self.env, build={'state': 'ready'}, fast_boot=True)
        a = server.App.__new__(server.App); a.env_dir = lambda eid: self.tmp.name
        self.assertIn('valid', a.snapshot_info('snap', env))


class Idrive7ServerTest(CodingBase):
    def test_new_central_screen_starts_with_touch_coded(self):
        src = open(os.path.join(ROOT, 'idemu', 'server.py')).read()
        self.assertIn("dict(coding7.DEFAULT_HU)", src)

    def test_coding_info_works_for_idrive7_and_not_for_idrive4(self):
        a = server.App.__new__(server.App); a.rt = None; a.flashes = {}; a.builds = {}
        a.load_env = lambda eid: dict(self.env, kind=self.env_kind); a.env_dir = lambda eid: self.tmp.name
        from unittest.mock import patch
        self.env_kind = 'mgu7'
        with patch.object(server.catalog, 'packages_ok', return_value=True):
            d = a.coding_info('x')
        self.assertGreater(len(d['params']), 0); self.assertFalse(d['running'])
        self.env_kind = 'cic'
        with self.assertRaises(server.ApiError): a.coding_info('x')


if __name__ == '__main__':
    unittest.main()

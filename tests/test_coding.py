"""Editor de coding: leitura do firmware (símbolos), aplicação de alterações, tabela do guest e backups. Sem emulador."""
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import coding, codegen, ifs  # noqa: E402


def fake_lib(path, syms):
    """ELF32 mínimo: .dynsym/.dynstr e um segmento com as funções 'mov r0,#v; bx lr'."""
    strtab = b'\0'
    names = {}
    for n, _ in syms:
        names[n] = len(strtab)
        strtab += n.encode() + b'\0'
    code_off = 0x200
    code = b''
    dyn = b'\0' * 16
    for i, (n, ins) in enumerate(syms):
        va = code_off + len(code)
        code += struct.pack('<II', ins, 0xe12fff1e)
        dyn += struct.pack('<IIIBBH', names[n], va, 8, 0x12, 0, 1)
    dyn_off = code_off + len(code)
    str_off = dyn_off + len(dyn)
    shoff = str_off + len(strtab)
    eh = bytearray(52)
    eh[:6] = b'\x7fELF\x01\x01'
    struct.pack_into('<I', eh, 28, 52)     # phoff
    struct.pack_into('<I', eh, 32, shoff)
    struct.pack_into('<H', eh, 42, 32)     # phentsize
    struct.pack_into('<H', eh, 44, 1)
    struct.pack_into('<H', eh, 46, 40)     # shentsize
    struct.pack_into('<H', eh, 48, 3)
    ph = struct.pack('<8I', 1, 0, 0, 0, shoff, shoff, 5, 0x1000)
    body = bytes(eh) + ph
    body += b'\0' * (code_off - len(body)) + code + dyn + strtab
    sh0 = struct.pack('<10I', *([0] * 10))
    sh1 = struct.pack('<10I', 0, 11, 0, dyn_off, dyn_off, len(dyn), 2, 0, 4, 16)   # DYNSYM, link -> 2
    sh2 = struct.pack('<10I', 0, 3, 0, str_off, str_off, len(strtab), 0, 0, 1, 0)
    with open(path, 'wb') as f:
        f.write(body + sh0 + sh1 + sh2)


class ReadDefaults(unittest.TestCase):
    def test_group_and_factory_value_from_symbols(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'lib.so')
            fake_lib(p, [('nbtSysetDefaults_getCbfHMI_CB_FCOMPASS', 0xe3a00001),          # mov r0,#1
                         ('nbtSysetDefaults_getCbfKOMBI_CB_FBIG', 0xe3010234),            # movw r0,#0x1234
                         ('nbtSysetDefaults_getCbfNAVIGATION_CB_FNOPE', 0xe1a00000),      # outra instrução: sem valor
                         ('outra_coisa', 0xe3a00005)])
            g, v = coding._read_defaults(p)
            self.assertEqual(g, {'COMPASS': 'HMI', 'BIG': 'KOMBI', 'NOPE': 'NAVIGATION'})
            self.assertEqual(v, {'COMPASS': 1, 'BIG': 0x1234})
        finally:
            shutil.rmtree(d)


class Apply(unittest.TestCase):
    def env(self):
        return {'chassis': 'F30', 'brand': 'bmw', 'coding': {'language': 'pt_BR', 'extra': {'SERVICE_HISTORY': 1}}}

    def test_number_text_language_and_removal(self):
        e = self.env()
        coding.apply_changes(e, {'COMPASS': 1, 'STARTUP_TYPE': 'animation', 'language': 'en_GB', 'SERVICE_HISTORY': None})
        self.assertEqual(e['coding']['language'], 'en_GB')
        self.assertEqual(e['coding']['extra'], {'COMPASS': 1, 'STARTUP_TYPE': 2})

    def test_rejects_unknown_and_out_of_range(self):
        for bad in ({'NAO_EXISTE': 1}, {'COMPASS': 2}, {'COMPASS': 'x'}, {'language': 'xx_XX'}):
            with self.assertRaises(ValueError):
                coding.apply_changes(self.env(), bad)

    def test_change_reaches_the_guest_table(self):
        e = self.env()
        coding.apply_changes(e, {'COMPASS': 1})
        row = codegen.load_dict()['COMPASS'][0]
        tab, n, warn = codegen.build_table(codegen.profile_for(e))
        self.assertEqual(warn, [])
        rows = [struct.unpack_from('<HHBB', tab, i) for i in range(0, len(tab), 6)]
        self.assertIn((row['blk'], row['byte'] + row['e'], row['mask'], row['mask']), rows)
        self.assertEqual(n, len(rows))


class Backups(unittest.TestCase):
    def test_roundtrip_and_limit(self):
        d = tempfile.mkdtemp()
        try:
            env = {'chassis': 'F30', 'coding': {'language': 'de_DE', 'extra': {'COMPASS': 1}}}
            bid = coding.backup(env, d, 'nota')
            self.assertEqual(coding.read_backup(d, bid)['coding'], env['coding'])
            lst = coding.list_backups(d)
            self.assertEqual((lst[0]['id'], lst[0]['note'], lst[0]['changed']), (bid, 'nota', 1))
            for _ in range(40):
                coding.backup(env, d)
            self.assertEqual(len(coding.list_backups(d)), 30)
            with self.assertRaises(ValueError):
                coding.read_backup(d, '../env')
        finally:
            shutil.rmtree(d)


class ValueLabels(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(coding.value_label('COMPASS', 'nicht_aktiv'), 'Not active')
        self.assertEqual(coding.value_label('COMPASS', 'va_COMPASS'), 'Active')
        self.assertEqual(coding.value_label('X', 'wert_15'), '15')


class BootScript(unittest.TestCase):
    def script(self):
        def ent(typ, body):
            n = (4 + len(body) + 3) & ~3
            return struct.pack('<HBB', n, typ, 0) + body + b'\0' * (n - 4 - len(body))
        s = ent(4, b'/boot/bin/ksh\0/bin/ksh\0')
        s += ent(0, b'\0 \0\0\0\0\x09\x1cdevb-sdmmc-omap5evm\0devb\0') + ent(1, b'2\0/dev/sda0\0') + ent(1, b'2\0/dev/ser1\0')
        s += ent(0, b'\0\0\0\0\0\0\x02\x1c/boot/bin/gs\0gs\0') + ent(0, b'\0\0\0\0\0\0\x0e\x1c/opt/sys/bin/starter\0starter\0')
        s += ent(0, b'\0\0\0\0\0\0\x0a\x1csysinit\0sysinit\0')
        return bytearray(s + b'\0\0\0\0')

    def test_skips_only_hardware_waits(self):
        b = self.script()
        ifs.speed_up_script(b)
        ent = ifs._script_entries(b)
        self.assertEqual([e[2] for e in ent], [4, 3, 3, 1, 3, 3, 0])       # ser1 e sysinit ficam

    def test_unknown_script_fails_instead_of_breaking(self):
        b = self.script().replace(b'/boot/bin/gs', b'/boot/bin/xx')
        with self.assertRaises(ValueError):
            ifs.speed_up_script(b)


if __name__ == '__main__':
    unittest.main()

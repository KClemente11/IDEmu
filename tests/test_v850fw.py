"""Testes da leitura do firmware do IOC (V850/RH850) nos pacotes SWFL (idemu/v850fw.py), com um pacote sintético."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import v850, v850fw  # noqa: E402


def record(typ, payload):
    return bytes([typ, 0, 0]) + len(payload).to_bytes(4, 'little') + b'\0\0' + payload


def write(path, data):
    with open(path, 'wb') as f:
        f.write(data)


def package(blocks):
    """Pacote SWFL mínimo: 10 bytes de cabeçalho; por bloco, um registro tipo 2 (metadados) e um tipo 4 (dados)."""
    out = bytearray(10)
    for meta, data in blocks:
        out += record(2, meta.encode('latin1')) + record(4, data)
    return bytes(out)


APP = (b'\x00' * 16 + b'IpcTest\x00IpcSGW\x00IpcSGWCtrl\x00cfDsiData\x00IpctrustedVIN_Ctrl\x00m2Handle\x00'
       b'\x00BMW UGW2 stuff\x00' + b'8140_APPL\x00TEST_SW \x00Jun  8 2017\x0015:20:16\x00cbuild_ScPF\x00HIKAWSBL\x00DV850T05xxxxxV107\x00'
       b'Headunit C1\x00Nov 25 2013\x00BMW UGW2\x00V2.1.007\x00Nov 25 2013\x00BMW DiagnosticsRouter\x00V2.1.005\x00'
       b'DiagCoreEmptyList\x00V000-009-051-00337\x00Gateway\x002013-08-27T16:36:25\x00Bernal-Marin\x00K2L Composer/BMW ZGW\x00'
       b'-------- BIOSControl V850 --------\x00UPD70F3554\x00UPD70F4006\x00')


class V850FwTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='v850fw')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_psdz(self):
        d = os.path.join(self.tmp, 'psdzdata', 'swe', 'swfl')
        os.makedirs(d)
        gw = b'\x03\x00\x14\x09' + b'\xff' * 0x2000 + b'DATA' + b'\xff' * 0x1000
        write(os.path.join(d, 'swfl_0000271a.bin.007_051_002'), package([
            ('TargetPath=/fs/;Name=io-ipc;Tag=FIL;CPU=Jacinto;', b'ELF'),
            ('Name=v850ApplicationFlash;Address=000A0040;Tag=IOC_FLASH;CPU=Jacinto;Offset=00;SELECTIVE=DEFAULT;SEL_HWINDEX=2-3;', APP),
            ('Name=rh850ApplicationFlash;Address=000A0200;Tag=IOC_FLASH;CPU=Jacinto;Offset=00;SELECTIVE=DEFAULT;SEL_HWINDEX=4-*;', APP)]))
        write(os.path.join(d, 'swfl_0000271a.bin.007_039_008'), package([
            ('Name=v850ApplicationFlash;Address=000A0040;Tag=IOC_FLASH;SEL_HWINDEX=2-*;', APP)]))
        write(os.path.join(d, 'swfl_0000271f.bin.007_051_002'), package([
            ('Name=v850GWTableFlash;Address=00160000;Tag=GATEWAY_FLASH;SEL_HWINDEX=2-3;', gw)]))
        return os.path.join(self.tmp, 'psdzdata')

    def test_hw_ranges(self):
        self.assertEqual(v850fw.hw_range('2-3'), (2, 3))
        self.assertEqual(v850fw.hw_range('4-*'), (4, None))
        self.assertEqual(v850fw.hw_range('3'), (3, 3))
        self.assertTrue(v850fw.hw_matches('2-3', 3))
        self.assertFalse(v850fw.hw_matches('2-3', 4))
        self.assertTrue(v850fw.hw_matches('4-*', 9))
        self.assertFalse(v850fw.hw_matches('4-*', 3))

    def test_family(self):
        self.assertEqual(v850fw.family('rh850GWTableFlash'), 'RH850')
        self.assertEqual(v850fw.family('v850ApplicationRseFlash'), 'V850')

    def test_identity(self):
        i = v850fw.identity(APP)
        self.assertEqual(i['appl'], '8140_APPL')
        self.assertEqual(i['build'], 'Jun  8 2017 15:20:16')
        self.assertEqual(i['device'], 'Headunit C1')
        self.assertEqual(i['bootloader_ids'], ['DV850T05xxxxxV107'])
        self.assertEqual([(c['name'], c['version']) for c in i['components']], [('BMW UGW2', 'V2.1.007'), ('BMW DiagnosticsRouter', 'V2.1.005')])
        self.assertEqual(i['gateway_data'], 'V000-009-051-00337')
        self.assertEqual(i['gateway_data_built']['tool'], 'K2L Composer/BMW ZGW')
        self.assertEqual(i['device_ids'], ['UPD70F3554', 'UPD70F4006'])
        self.assertEqual(v850fw.identity(b'nada'), {})

    def test_ipc_channels(self):
        self.assertEqual(v850fw.ipc_channels(APP), ['IpcTest', 'IpcSGW', 'IpcSGWCtrl', 'cfDsiData', 'IpctrustedVIN_Ctrl'])

    def test_gw_info(self):
        g = v850fw.gw_info(b'\x03\x00' + b'\xff' * 0x3000 + b'X' + b'\xff' * 0x500)
        self.assertEqual((g['pages_4k_used'], g['pages_4k']), (2, 4))
        self.assertEqual(g['last_data_offset'], 0x3002)
        self.assertEqual(g['header'][:4], '0300')

    def test_scan_picks_newest_and_extracts(self):
        psdz = self.make_psdz()
        out = os.path.join(self.tmp, 'out')
        r = v850fw.scan(psdz, extract=out)
        self.assertEqual(sorted(r['packages']), ['app', 'gateway'])
        self.assertEqual(list(r['packages']['app']), ['007_051_002'])
        names = [b['name'] for b in r['packages']['app']['007_051_002']['blocks']]
        self.assertEqual(names, ['v850ApplicationFlash', 'rh850ApplicationFlash'])        # o arquivo `io-ipc` (Tag=FIL) não entra
        blk = r['packages']['app']['007_051_002']['blocks'][1]
        self.assertEqual((blk['family'], blk['hwindex'], blk['address']), ('RH850', '4-*', 0xA0200))
        with open(os.path.join(out, 'v850ApplicationFlash.007_051_002.bin'), 'rb') as f:
            self.assertEqual(f.read(), APP)
        gw = r['packages']['gateway']['007_051_002']['blocks'][0]['gateway_table']
        self.assertEqual(gw['pages_4k_used'], 2)
        old = v850fw.scan(psdz, versions=['007_039_008'])
        self.assertEqual(list(old['packages']['app']), ['007_039_008'])

    def test_scan_without_psdz(self):
        self.assertEqual(v850fw.scan(os.path.join(self.tmp, 'nao-existe'))['packages'], {})

    def test_summary(self):
        s = v850fw.summary(v850fw.scan(self.make_psdz()))
        self.assertEqual([v['family'] for v in s['variants']], ['V850', 'RH850'])
        self.assertEqual(s['gateway_table']['pages_used'], 2)
        self.assertIn('IpcSGW', s['ipc_channels'])
        self.assertEqual(v850fw.summary({}), {'variants': [], 'ipc_channels': [], 'gateway_table': None})

    def test_shipped_data(self):
        """O JSON que acompanha o IDEmu (extraído da PSdZData 007_051_002) tem as variantes e o gateway."""
        s = v850fw.summary()
        fams = sorted((v['family'], v['hwindex'], v['device']) for v in s['variants'])
        self.assertIn(('V850', '2-3', 'Headunit C1'), fams)
        self.assertIn(('RH850', '4-*', 'Headunit D6'), fams)
        self.assertTrue(any(v['appl'] == '8173_APPL' for v in s['variants']))
        for n in ('IpcSGW', 'IpcDGW', 'IpcTouch_O5', 'IpcOnOff', 'IpcWatchDog', 'IpcAmpControl', 'IpctrustedVIN_Ctrl'):
            self.assertIn(n, s['ipc_channels'])
        self.assertEqual((s['gateway_table']['pages_used'], s['gateway_table']['pages']), (113, 160))
        json.dumps(s)

    def test_link_snapshot_has_firmware(self):
        link = v850.V850Link(os.path.join(self.tmp, 'nao.sock'), None)
        snap = link.snapshot()
        self.assertTrue(snap['firmware']['variants'])


if __name__ == '__main__':
    unittest.main()

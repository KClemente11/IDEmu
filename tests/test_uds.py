"""UDS diagnostic emulator (idemu/uds.py): encoding, services, presets, configuration checks and gateway addresses."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import uds, canbus  # noqa: E402


class UdsTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='idemu-uds-')
        self.addCleanup(shutil.rmtree, self.d, True)
        self.can = canbus.CanBus()
        self.emu = uds.UdsEmulator(uds.config_path(self.d), can=self.can, log_path=os.path.join(self.d, 'uds.log'))

    def ask(self, ecu, req):
        r = self.emu.handle(0xF4, ecu, bytes.fromhex(req))
        return None if r is None else r.hex().upper()

    def test_b58_dids_decode_like_the_collector(self):
        self.assertEqual(self.ask(0x12, '224201'), '624201654D')            # 101.3 kPa * 256
        self.assertEqual(self.ask(0x18, '22DA12'), '62DA12007B')            # 75 C + 48
        self.assertEqual(self.ask(0x12, '224300'), '6243000E43')            # (92 + 273.15) * 10
        r = bytes.fromhex(self.ask(0x12, '224205'))
        self.assertTrue(100 <= int.from_bytes(r[3:5], 'big') / 128.0 <= 240)

    def test_obd_and_supported_pids(self):
        self.assertTrue(self.ask(0x12, '010C').startswith('410C'))
        bitmap = int(self.ask(0x12, '0100')[4:], 16)
        for pid in (0x05, 0x0C, 0x0D):
            self.assertTrue(bitmap & (1 << (32 - pid)), pid)

    def test_standard_services_and_negative_replies(self):
        self.assertEqual(self.ask(0x12, '229999'), '7F2231')
        self.assertEqual(self.ask(0x12, '3E00'), '7E00')
        self.assertIsNone(self.ask(0x12, '3E80'))
        self.assertEqual(self.ask(0x12, '2F0101'), '6F0101')                # MHD map switch is echoed
        self.assertEqual(self.ask(0x12, '1902AF'), '5902FF')
        self.assertEqual(self.ask(0x12, '1003'), '5003003201F4')
        self.assertEqual(self.ask(0x12, '8501'), '7F8511')
        self.assertIsNone(self.ask(0x40, '22F190'))                         # no such ECU: the tester times out
        cfg = self.emu.config(); cfg['unknown_ecu'] = 'nrc'; self.emu.save(cfg)
        self.assertEqual(self.ask(0x40, '22F190'), '7F2211')

    def test_raw_rules_win_and_support_wildcards(self):
        cfg = self.emu.config()
        cfg['ecus']['12']['raw'] = [{'request': '22 40 ..', 'response': '62 40 00 01 02'}, {'request': '3101', 'response': ''}]
        self.emu.save(cfg)
        self.assertEqual(self.ask(0x12, '224077'), '6240000102')
        self.assertIsNone(self.ask(0x12, '3101'))

    def test_s63_record_layout(self):
        cfg = uds.merge_preset(self.emu.config(), 's63tu'); self.emu.save(cfg)
        r = bytes.fromhex(self.ask(0x12, '224000'))
        self.assertEqual(r[:3], b'\x62\x40\x00')
        data = r[3:]
        self.assertEqual(len(data), 36)
        self.assertEqual(int.from_bytes(data[0:2], 'big'), 4096)            # lambda 1.0 / 0.000244140625
        self.assertEqual(data[15], round((90 + 48) / 0.75))                 # TMOT
        self.assertEqual(int.from_bytes(data[10:12], 'big', signed=True), round(20 / 0.0078125))

    def test_set_value_holds_it_and_drops_the_sweep(self):
        self.emu.set_value('12', 'dids', '4205', 200)
        self.assertEqual(self.ask(0x12, '224205'), '6242056400')            # 200 * 128 = 0x6400
        self.assertNotIn('wave', self.emu.config()['ecus']['12']['dids']['4205'])
        with open(uds.config_path(self.d)) as f:
            self.assertEqual(json.load(f)['ecus']['12']['dids']['4205']['value'], 200.0)

    def test_signed_and_clamped_encoding(self):
        self.assertEqual(uds.encode_field({'bytes': 2, 'scale': 0.1, 'signed': True, 'value': -5}, 0), b'\xff\xce')
        self.assertEqual(uds.encode_field({'bytes': 1, 'scale': 1, 'value': 999}, 0), b'\xff')
        self.assertEqual(uds.encode_field({'hex': '01 02'}, 0), b'\x01\x02')

    def test_validate_reports_the_bad_entry(self):
        with self.assertRaisesRegex(ValueError, '12 dids 4205'):
            uds.validate({'ecus': {'12': {'dids': {'4205': {'hex': 'XYZ'}}}}})
        with self.assertRaises(ValueError):
            uds.validate({'gateway_ips': ['1.2.3']})
        self.assertIn('0C', uds.validate({'ecus': {'0x12': {'obd': {'c': {'value': 1}}}}})['ecus']['12']['obd'])

    def test_transactions_log_and_can_monitor(self):
        self.ask(0x12, '224201')
        t = self.emu.transactions()
        self.assertEqual(t['items'][-1]['resp'], '624201654D')
        frames = self.can.frames_since(0)['frames']
        self.assertEqual([f['id'] for f in frames], ['6F1', '612'])
        self.assertEqual(frames[0]['data'], '1203224201')
        with open(os.path.join(self.d, 'uds.log')) as f:
            self.assertIn('224201', f.read())

    def test_long_replies_are_segmented(self):
        fr = uds.isotp_frames(0xF1, bytes(range(20)))
        self.assertEqual(fr[0][:3], b'\xf1\x10\x14')
        self.assertEqual([f[1] for f in fr[1:]], [0x21, 0x22, 0x23])

    def test_gateway_ips_include_overlay_files(self):
        p = os.path.join(self.d, 'gw.txt')
        with open(p, 'w') as f:
            f.write('169.254.10.20\n')
        ips = uds.gateway_ips(self.d, [('var/opt/hmi/data/ID5/plugins/BoostDeck/gateway-ip.txt', p), ('x/other.txt', p)])
        self.assertEqual(ips, [uds.DEFAULT_IP, '169.254.10.20'])


if __name__ == '__main__':
    unittest.main()

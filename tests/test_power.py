import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from idemu.power import EvoPower
from idemu.most import MostCar
from idemu import server
from idemu import shim_update
from idemu.qnxfs import mkdisk, qnx4


class PowerTest(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.power = EvoPower(lambda: self.now)

    def test_defaults_preserve_ignition_and_do_not_trigger_on_first_sample(self):
        self.assertEqual(self.power.sample(True)['power_state_detailed'], 0x63)
        self.assertEqual(self.power.sample(False)['power_state_detailed'], 0)
        self.assertEqual(self.power.sample(True)['power_state_detailed'], 0x63)
        self.power.configure({'on_wake': True})
        self.assertEqual(self.power.sample(True)['mode'], 'auto')

    def test_manual_welcome_expires_and_can_be_repeated(self):
        self.power.sample(True)
        self.power.action('welcome')
        self.assertEqual(self.power.sample(True)['power_state_detailed'], 0x5A)
        self.assertEqual(self.power.sample(True)['power_state'], 0)
        with self.assertRaises(ValueError): self.power.action('welcome')
        self.now += 10
        self.assertEqual(self.power.sample(True)['power_state_detailed'], 0x63)
        self.power.action('welcome')
        self.assertEqual(self.power.sample(True)['mode'], 'welcome')

    def test_sleep_wake_opt_in_and_ignition_edge(self):
        self.power.configure({'on_wake': True, 'duration': 3})
        self.power.action('sleep')
        self.assertEqual(self.power.sample(True)['power_state_detailed'], 0)
        self.power.action('wake')
        self.assertEqual(self.power.sample(True)['power_state_detailed'], 0x5A)
        self.now += 3
        self.assertEqual(self.power.sample(False)['mode'], 'awake')
        self.power.action('auto')
        self.assertEqual(self.power.sample(False)['power_state_detailed'], 0)
        self.assertEqual(self.power.sample(True)['power_state_detailed'], 0x5A)
        self.now += 3
        self.assertEqual(self.power.sample(True)['power_state_detailed'], 0x63)
        self.assertEqual(self.power.sample(True)['mode'], 'auto')

    def test_wake_does_not_show_welcome_without_opt_in(self):
        self.power.action('sleep')
        self.power.action('wake')
        self.assertEqual(self.power.sample(True)['mode'], 'awake')

    def test_sleep_and_auto_cancel_pending_welcome(self):
        self.power.action('welcome')
        self.power.action('sleep')
        self.now += 60
        self.assertEqual(self.power.sample(True)['mode'], 'sleep')
        self.power.action('welcome')
        self.power.action('auto')
        self.assertEqual(self.power.sample(False)['power_state_detailed'], 0)

    def test_reject_invalid_config_without_partial_change(self):
        for value in (0, 61, float('inf'), float('nan'), True, None, 'abc'):
            with self.assertRaises(ValueError): self.power.configure({'duration': value, 'on_wake': True})
            self.assertFalse(self.power.config()['on_wake'])
        with self.assertRaises(ValueError): self.power.configure({'on_wake': 'false'})
        with self.assertRaises(ValueError): self.power.action('bogus')


class PowerIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.messages = []
        bridge = SimpleNamespace(subs={(0xD1, 2): {0x430: 1, 0x434: 1}},
                                 publish=lambda fb, fkt, data, inst: self.messages.append((fb, inst, fkt, data)) or 1)
        self.car = MostCar(bridge)
        self.car.can = SimpleNamespace(get_signal=lambda name: 69)
        self.rt = SimpleNamespace(id='test', env={'id': 'test'}, state='running', v850=SimpleNamespace(bridge=SimpleNamespace(car=self.car)), can=self.car.can)
        self.h = object.__new__(server.H)

    def test_api_actions_publish_native_status_and_persist_only_config(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'ENVS', folder), patch.object(server.APP, 'rt', self.rt):
            self.car.publish_all()
            self.messages.clear()
            state = self.h.api_power('POST', 'power/action', {'action': 'welcome'})
            self.assertEqual(state['power_state_detailed'], 0x5A)
            self.assertIn((0xD1, 2, 0x434, b'\x5a'), self.messages)
            self.assertIn((0xD1, 2, 0x430, b'\x00'), self.messages)
            self.h.api_power('POST', 'power/config', {'on_wake': True, 'duration': 20})
            saved = server.APP.read_env('test')
            self.assertEqual(saved['welcome'], {'on_wake': True, 'duration': 20.0})
            self.assertNotIn('mode', saved['welcome'])
            self.h.api_power('POST', 'power/action', {'action': 'auto'})
            self.assertIn((0xD1, 2, 0x434, b'\x63'), self.messages)

    def test_unsupported_generation_and_stopped_runtime_are_rejected(self):
        with patch.object(server.APP, 'rt', self.rt):
            self.rt.env['kind'] = 'mgu22'
            self.assertFalse(self.h.api_power('GET', 'power/state', {})['supported'])
            with self.assertRaises(server.ApiError): self.h.api_power('POST', 'power/action', {'action': 'welcome'})
            self.rt.env.pop('kind')
            self.rt.state = 'stopped'
            self.assertFalse(self.h.api_power('GET', 'power/state', {})['running'])
            with self.assertRaises(server.ApiError): self.h.api_power('POST', 'power/action', {'action': 'welcome'})


class ShimRefreshTest(unittest.TestCase):
    def test_refresh_preserves_coding_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); libraries = root / 'libs'; libraries.mkdir()
            elf = b'\x7fELF\x01\x01' + b'\0' * 12 + b'\x28\x00' + b'new emulator code'
            tree = mkdisk.Tree()
            for name in ('libscreen.so.1', 'libBMWOTFapi.so.3'):
                (libraries / name).write_bytes(elf)
                tree.add('/lib/' + name, 0o100755, b'old', 3)
            tree.add('/coding.tab', 0o100644, b'keep-coding', 11)
            tree.add('/boot.sh', 0o100755, b'keep-boot', 9)
            mkdisk.write(tree, str(root / 'shim.img'), 2048)
            self.assertTrue(shim_update.refresh(root, libraries))
            reader = qnx4.R(str(root / 'shim.img'))
            try: data = {n: reader.read(e) for n, e in reader.walk() if not e['mode'] & 0o40000}
            finally: reader.f.close()
            self.assertEqual(data['/coding.tab'], b'keep-coding')
            self.assertEqual(data['/boot.sh'], b'keep-boot')
            self.assertEqual(data['/lib/libscreen.so.1'], elf)
            self.assertFalse(shim_update.refresh(root, libraries))

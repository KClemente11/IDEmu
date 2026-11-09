import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from idemu import windows_update as updater


class WindowsUpdateTest(unittest.TestCase):
    def check(self, release, payload, choice=6):
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / 'IDEmu.exe'
            launcher.with_name('installed-version.txt').write_text('0.1.9\n', encoding='ascii')
            launched = []

            def setup(path):
                launched.append(path.read_bytes())
                shutil.rmtree(path.parent)

            with (patch.object(updater.sys, 'executable', str(launcher)),
                  patch.object(updater, 'open_url', side_effect=[io.BytesIO(json.dumps(release).encode()), io.BytesIO(payload)]) as fetch,
                  patch.object(updater, 'dialog', return_value=choice) as dialog,
                  patch.object(updater, 'start_setup', side_effect=setup)):
                code = updater.main()
                return code, fetch.call_count, launched, dialog.call_args.args[0]

    def release(self, payload, tag='v0.1.10'):
        return {'tag_name': tag, 'assets': [{
            'name': updater.ASSET, 'state': 'uploaded', 'size': len(payload),
            'browser_download_url': f'https://github.com/{updater.REPO}/releases/download/{tag}/{updater.ASSET}',
            'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(),
        }]}

    def test_newer_verified_payload_is_handed_off(self):
        payload = b'test installer'
        self.assertEqual(self.check(self.release(payload), payload)[:3], (0, 2, [payload]))

    def test_cancel_and_older_release_do_not_download(self):
        payload = b'test installer'
        self.assertEqual(self.check(self.release(payload), payload, choice=7)[:3], (0, 1, []))
        self.assertEqual(self.check(self.release(payload, 'v0.1.8'), payload)[:3], (0, 1, []))

    def test_wrong_bytes_or_wrong_repository_cannot_launch_setup(self):
        release = self.release(b'correct')
        code, downloads, launched, message = self.check(release, b'corrupt')
        self.assertEqual((code, downloads, launched), (1, 2, []))
        self.assertIn('SHA-256', message)
        release['assets'][0]['browser_download_url'] = 'https://example.com/IDEmu-Setup.exe'
        self.assertEqual(self.check(release, b'correct')[:3], (1, 1, []))

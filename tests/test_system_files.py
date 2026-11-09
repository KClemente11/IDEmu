import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from idemu import catalog, server


class SystemFilesTest(unittest.TestCase):
    def test_catalog_and_missing_environment_do_not_import_backends(self):
        with tempfile.TemporaryDirectory() as temp:
            code = """
import sys
from idemu import catalog, server
catalog.load_settings = lambda: {}
catalog.STAGE = server.ENVS
for kind in catalog.DIRECT_BACKENDS:
    catalog.package_status(kind)
catalog.evo_package_status()
app = server.APP
app.save_env({'id': 'missing', 'kind': 'mgu22'})
assert app.list_envs()[0]['build']['state'] == 'none'
for method in (app.start_build, app.start):
    try:
        method('missing')
    except server.ApiError as error:
        assert error.code == 409
    else:
        raise AssertionError('missing files accepted')
assert not {'idemu.' + name for name in ('cic', 'mgu7', 'mgu', 'runtime', 'builder')}.intersection(sys.modules)
"""
            subprocess.run([sys.executable, '-c', code], check=True,
                           env=dict(os.environ, IDEMU_ENVS=temp))

    def test_evo_gate_checks_each_selected_role_again_before_start(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(server, 'ENVS', temp):
            root = Path(temp)
            paths = {}
            for role, sid in (('os', '0000271a'), ('brand', '00002719'), ('hmi', '00002720')):
                path = root / f'swfl_{sid}.bin.007_051_002'
                path.touch()
                paths[role] = str(path)
            app = server.App()
            env = app.create({'name': 'ID6', 'swfl': paths})
            self.assertTrue(env['files_ok'])
            self.assertFalse(catalog.evo_package_status(dict(paths, hmi=paths['os']))['ok'])
            Path(paths['hmi']).unlink()
            self.assertFalse(app.load_env(env['id'])['files_ok'])
            with patch.object(server, 'runtime_module', side_effect=AssertionError('backend loaded')):
                for method in (app.start_build, app.start):
                    with self.assertRaisesRegex(server.ApiError, 'System Files'):
                        method(env['id'])

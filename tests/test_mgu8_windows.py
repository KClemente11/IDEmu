"""Native MGU22 image preparation: guest paths, binaries and initramfs fidelity."""
import os
import mmap
import socket
import subprocess
import threading
import time
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools' / 'mgu'))
import build_guest8
import build_image
from idemu import mgu
from idemu.initramfs import validate_cpio
from test_mgu7_windows import build_image as fixture_image
from ext4ls import E4


def elf(machine=183):
    header = bytearray(64)
    header[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', header, 18, machine)
    return header


def cpio_entries(path):
    data = Path(path).read_bytes(); offset = 0; entries = {}
    while offset < len(data):
        header = data[offset:offset + 110]
        assert header[:6] == b'070701'
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name = data[offset + 110:offset + 110 + namesize - 1].decode()
        offset = (offset + 110 + namesize + 3) & ~3
        payload = data[offset:offset + size]
        offset = (offset + size + 3) & ~3
        if name == 'TRAILER!!!': break
        entries[name] = (mode, payload)
    return entries


class GuestHelpersTest(unittest.TestCase):
    def test_package_picker_accepts_tar_suffix_without_changing_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'swe' / 'swfl' / 'swfl_00009ff7.bin.007_034_003'
            base.parent.mkdir(parents=True)
            archive = Path(str(base) + '.tar'); archive.write_bytes(b'firmware')
            self.assertEqual(build_image.package(tmp, 'swfl', '00009ff7', '007_034_003'), str(archive))
            self.assertEqual(archive.read_bytes(), b'firmware')
            with self.assertRaises(FileNotFoundError):
                build_image.package(tmp, 'swfl', '00009ff7', 'wrong_version')

    def test_prebuilt_helpers_are_validated_before_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'; source.mkdir()
            dest = Path(tmp) / 'dest'; dest.mkdir()
            for name in build_guest8.GUEST_FILES: (source / name).write_bytes(elf())
            build_image.prepare_guest('unused', dest, source)
            self.assertEqual({p.name for p in dest.iterdir()}, set(build_guest8.GUEST_FILES))
            for machine in (62, 40):
                (source / 'libcod.so.0').write_bytes(elf(machine))
                with self.assertRaisesRegex(ValueError, 'AArch64'):
                    build_guest8.validate_guest(source)
            (source / 'libcod.so.0').write_bytes(b'MZ' + bytes(62))
            with self.assertRaisesRegex(ValueError, 'ELF64'):
                build_guest8.validate_guest(source)

    def test_missing_llvm_fails_before_firmware_is_extracted(self):
        with patch.dict(os.environ, {}, clear=True), patch('shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'IDEMU_CLANG'):
                build_image.main(['missing-firmware', '--build-guest'])

    def test_frozen_app_relaunches_itself_as_a_tool(self):
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(build_image.tool_cmd('simg2raw.py', 'a', 'b'),
                             [sys.executable, '--run-tool', str(ROOT / 'tools' / 'mgu' / 'simg2raw.py'), 'a', 'b'])

    def test_windows_runtime_reaches_image_check_without_an_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), patch.object(mgu, 'image_ready', return_value=False):
            rt = mgu.MguRuntime(tmp, {'id': 'normal-id8'})
            with self.assertRaisesRegex(RuntimeError, 'imagem'):
                rt.start()

    def test_windows_qemu_command_uses_tcg_and_named_ram(self):
        cmd = mgu.windows_qemu_command('boot.dtb', 'Local\\unique', ('127.0.0.1', 54321), 'console=ttyAMA0')
        self.assertIn('tcg,thread=multi', cmd)
        self.assertIn('cortex-a76', cmd)
        self.assertNotIn('hvf', cmd)
        self.assertIn('memory-backend-idemu,id=m0,size=12288M,mapping-name=Local\\unique,share=on', cmd)
        self.assertIn('tcp:127.0.0.1:54321,server=on,wait=off,nodelay=on', cmd)

    def test_catalog_enables_native_id8_without_an_opt_in_and_requires_helpers(self):
        from idemu import catalog
        with patch.object(sys, 'platform', 'win32'), patch.object(catalog, 'WSL', False), \
                patch.object(catalog, 'native_mgu8_ready', return_value=True), patch.dict(os.environ, {}, clear=True):
            self.assertTrue(catalog.backend_supported('mgu22'))
            with patch.object(catalog, 'native_mgu8_ready', return_value=False):
                self.assertFalse(catalog.backend_supported('mgu22'))

    def test_native_packaging_requires_both_host_and_guest_helpers(self):
        from build_windows import require_mgu8_helpers
        with tempfile.TemporaryDirectory() as tmp:
            native = Path(tmp); guest = native / 'guest8'; guest.mkdir()
            with self.assertRaisesRegex(ValueError, 'qemu-system-aarch64.exe'):
                require_mgu8_helpers(native, guest)
            for name in ('qemu-system-aarch64.exe', 'mguhost.exe'): (native / name).write_bytes(b'MZ')
            with self.assertRaisesRegex(ValueError, 'guest helpers'):
                require_mgu8_helpers(native, guest)
            for name in build_guest8.GUEST_FILES: (guest / name).write_bytes(elf())
            self.assertEqual(require_mgu8_helpers(native, guest), ('qemu-system-aarch64.exe', 'mguhost.exe'))
            (native / 'mguhost.exe').write_bytes(b'ELF')
            with self.assertRaisesRegex(ValueError, 'not a Windows executable'):
                require_mgu8_helpers(native, guest)

    def test_environment_runtime_is_available_for_native_id8(self):
        from idemu import catalog, server
        env = {'kind': 'mgu22', 'coding': {'hmi_version': 'id8'}}
        with patch.object(sys, 'platform', 'win32'), patch.object(catalog, 'WSL', False), \
                patch.object(catalog, 'native_mgu8_ready', return_value=True), patch.object(catalog, 'native_evo_ready', return_value=False):
            self.assertTrue(server.runtime_available(env))
            with patch.object(catalog, 'native_mgu8_ready', return_value=False):
                self.assertFalse(server.runtime_available(env))


@unittest.skipUnless(sys.platform == 'win32', 'Win32 named mappings')
class NamedRamTest(unittest.TestCase):
    def test_cancelled_ram_preparation_closes_its_mapping(self):
        from idemu import runtime
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'guest').mkdir()
            for filename in mgu.GUEST_FILES: (root / 'guest' / filename).write_bytes(b'helper')
            (root / 'base.cpio').write_bytes(b'base')
            opened = []; real_mapping = mmap.mmap; checks = 0
            def mapping(*args, **kwargs):
                result = real_mapping(*args, **kwargs); opened.append(result); return result
            def check():
                nonlocal checks
                checks += 1
                if checks == 2: raise runtime.BootStopped()
            with patch.object(mgu, 'OUT', tmp), patch.object(mgu, 'MB', 4), \
                    patch.object(mgu, 'INITRD_AT', mgu.GUEST_BASE + 4096), patch.object(mgu.mmap, 'mmap', side_effect=mapping):
                with self.assertRaises(runtime.BootStopped):
                    mgu._prepare_ram(str(root / 'boot.dtb'), shm_name='Local\\cancel-' + uuid.uuid4().hex, check=check)
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].closed)

    def test_children_exit_before_ram_mapping_is_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = mgu.MguRuntime(tmp, {'id': 'cleanup-test'})
            events = []
            rt.q = SimpleNamespace(terminate=lambda: events.append('terminate'), wait=lambda timeout: events.append('wait'))
            rt._ram = SimpleNamespace(close=lambda: events.append('release RAM'))
            channel = rt._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rt.stop()
            self.assertEqual(events, ['terminate', 'wait', 'release RAM'])
            self.assertEqual(channel.fileno(), -1)
            self.assertIsNone(rt._ram)

    def test_ram_is_shared_and_dtb_initrd_end_is_patched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'guest').mkdir()
            for filename in mgu.GUEST_FILES: (root / 'guest' / filename).write_bytes(b'helper')
            (root / 'base.cpio').write_bytes(b'base')
            name = 'Local\\IDEmu-test-' + uuid.uuid4().hex
            with patch.object(mgu, 'OUT', tmp), patch.object(mgu, 'MB', 4), \
                    patch.object(mgu, 'INITRD_AT', mgu.GUEST_BASE + 4096):
                memory = mgu._prepare_ram(str(root / 'boot.dtb'), 'override', name)
                try:
                    with mmap.mmap(-1, 4 << 20, tagname=name) as other:
                        self.assertEqual(other[4096:4100], b'base')
                        self.assertIn(b'override', other[4100:32768])
                        self.assertNotIn(struct.pack('>II', 0xdeadbeef, 0xfeedf00d), (root / 'boot.dtb').read_bytes())
                        other[0:4] = b'live'
                        self.assertEqual(memory[:4], b'live')
                finally: memory.close()

    def test_oversized_initrd_is_rejected_before_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'guest').mkdir()
            for filename in mgu.GUEST_FILES: (root / 'guest' / filename).write_bytes(b'helper')
            (root / 'base.cpio').write_bytes(b'base')
            with patch.object(mgu, 'OUT', tmp), patch.object(mgu, 'MB', 1), patch.object(mgu.mmap, 'mmap') as mapping:
                with self.assertRaisesRegex(RuntimeError, 'initramfs'):
                    mgu._prepare_ram(str(root / 'boot.dtb'))
                mapping.assert_not_called()


class ImagePreparationTest(unittest.TestCase):
    def test_readiness_validates_existing_archive_and_invalidates_its_cache_on_change(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mgu, 'OUT', tmp), patch.object(mgu, '_image_check', (None, False)):
            root = Path(tmp); (root / 'guest').mkdir(); (root / 'Image').write_bytes(b'kernel')
            for name in mgu.GUEST_FILES: (root / 'guest' / name).write_bytes(b'helper')
            archive = root / 'base.cpio'; archive.write_bytes(b'corrupt but present')
            with patch.object(mgu, 'validate_cpio', wraps=validate_cpio) as validate:
                self.assertFalse(mgu.image_ready()); self.assertFalse(mgu.image_ready())
                self.assertEqual(validate.call_count, 1)
                archive.write_bytes(mgu._cpio([('file', 0o100644, b'data')]) * 6)
                self.assertTrue(mgu.image_ready()); self.assertTrue(mgu.image_ready())
                self.assertEqual(validate.call_count, 2)
                st = archive.stat()
                with archive.open('r+b') as stream: stream.write(b'BADBAD')
                os.utime(archive, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
                self.assertFalse(mgu.image_ready())
                self.assertEqual(validate.call_count, 3)

    def test_concatenated_cpio_requires_complete_headers_payloads_and_trailers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'base.cpio'
            archive = mgu._cpio([('file', 0o100755, b'payload')])
            path.write_bytes(archive * 6)
            self.assertEqual(validate_cpio(path, 6)['archives'], 6)
            for invalid in (archive[:-1], archive[:110], archive + archive[1:], archive * 5):
                path.write_bytes(invalid)
                with self.assertRaises(ValueError): validate_cpio(path, 6)

    def test_converter_flushes_even_when_the_process_does_not_finalize_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_image(tmp, True)
            image = Path(tmp) / 'm/root.img'; output = Path(tmp) / 'root.cpio'
            code = ('import os,runpy,sys; script,image,output=sys.argv[1:]; '
                    'sys.argv=[script,image,output]; globals_kept_alive=runpy.run_path(script,run_name="__main__"); os._exit(0)')
            subprocess.run([sys.executable, '-c', code, str(ROOT / 'tools/mgu/ext2cpio.py'), str(image), str(output)], check=True)
            self.assertEqual(validate_cpio(output, 1)['archives'], 1)
            self.assertIn('etc/xt_dscp.ko', cpio_entries(output))

    def test_kernel_panic_is_reported_instead_of_waiting_for_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = mgu.MguRuntime(tmp, {'id': 'panic-test'})
            Path(rt.logd).mkdir()
            log = Path(rt.logd) / 'console.log'
            log.write_bytes(b'Kernel panic - not syncing: No working init found.\n')
            with self.assertRaisesRegex(RuntimeError, 'Guest boot failed.*No working init'):
                rt._check_guest_boot()
            log.write_bytes(b'IDEMU-HMI-START\n')
            rt._check_guest_boot()

    def test_bad_image_is_rejected_before_starting_a_vm(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mgu, 'OUT', tmp), patch.object(mgu, 'image_ready', return_value=True):
            Path(tmp, 'base.cpio').write_bytes(mgu._cpio([('file', 0o100644, b'data')])[:-5])
            rt = mgu.MguRuntime(tmp, {'id': 'bad-image'})
            with self.assertRaisesRegex(RuntimeError, 'incomplete or corrupted.*Rebuild'):
                rt.start()
            self.assertIsNone(rt.q)
            self.assertIsNone(rt.gl)
            self.assertIsNone(rt._boot_worker)

    def test_catalog_discovers_and_stages_all_six_tar_archives(self):
        from idemu import catalog
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); firmware = root / 'id8'; stage = root / 'stage'
            required = catalog.required_packages('mgu22')
            self.assertEqual(len(required), 6)
            files = []
            for item in required:
                kind = item.get('package_kind', 'swfl')
                path = firmware / 'swe' / kind / f'{kind}_{item["id"]}.bin.{item["version"]}.tar'
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(item['id'].encode()); files.append(path)
            with patch.object(catalog, 'STAGE', str(stage)), patch.object(catalog, 'load_settings', return_value={'psdz_path': tmp}):
                self.assertTrue(catalog.package_status('mgu22')['ok'])
                self.assertEqual(catalog.effective_psdz('mgu22'), str(firmware))
                found = catalog.scan_folder(tmp, [r['id'] for r in required], kind='mgu22')
                self.assertTrue(all(found['files'].values()))
                with patch.object(sys, 'platform', 'win32'):
                    for path in files:
                        self.assertEqual(catalog.stage_file(str(path), 'mgu22'), (True, 'ok'))
                with patch.object(catalog, 'load_settings', return_value={}):
                    self.assertTrue(catalog.packages_ok('mgu22'))
                    self.assertEqual(catalog.effective_psdz('mgu22'), str(stage))
                for path in files:
                    staged = stage / 'swe' / path.parent.name / path.name
                    self.assertFalse(staged.is_symlink())
                    self.assertEqual(staged.read_bytes(), path.read_bytes())
                files[-1].unlink()
                (stage / 'swe/swfk' / files[-1].name).unlink()
                self.assertFalse(catalog.package_status('mgu22')['ok'])

    def test_ext_image_goes_directly_to_cpio_preserving_linux_metadata(self):
        with tempfile.TemporaryDirectory(prefix='mgu8 with spaces ') as tmp:
            fixture_image(tmp, True)
            image = Path(tmp) / 'm' / 'root.img'
            output = Path(tmp) / 'root.cpio'
            build_image.ext2cpio(str(image), str(output), '/', '/opt/ivi/rootfs')
            entries = cpio_entries(output)
            prefix = 'opt/ivi/rootfs/'
            self.assertEqual(entries[prefix + 'etc/xt_DSCP.ko'][1], b'UPPER')
            self.assertEqual(entries[prefix + 'etc/xt_dscp.ko'][1], b'lower')
            self.assertEqual(entries[prefix + 'etc/aux'][1], b'reserved')
            self.assertEqual(entries[prefix + 'usr/bin/suid'][0], stat.S_IFREG | 0o4755)
            self.assertEqual(entries[prefix + 'lib'], (stat.S_IFLNK | 0o777, b'usr/lib'))
            e = E4(image)
            try:
                build_image.grab(e, '/usr/lib/libA.so.1', Path(tmp) / 'lib.so')
                self.assertEqual((Path(tmp) / 'lib.so').read_bytes(), b'A' * 70000)
            finally:
                e.f.close()

    def test_guest_symlink_resolution_uses_posix_paths_and_detects_loops(self):
        class Image:
            def __init__(self): self.seen = []
            def lookup(self, path): self.seen.append(path); return path
            def inode(self, path): return path
            def mode(self, path): return stat.S_IFREG if path == '/lib/actual' else stat.S_IFLNK
            def data(self, path):
                return {'/lib/a': b'../lib/b', '/lib/b': b'/lib/actual', '/lib/actual': b'library', '/loop': b'loop'}[path]
        with tempfile.TemporaryDirectory() as tmp:
            e = Image(); output = Path(tmp) / 'library'
            build_image.grab(e, '/lib/a', output)
            self.assertEqual(e.seen, ['/lib/a', '/lib/b', '/lib/actual'])
            self.assertEqual(output.read_bytes(), b'library')
            with self.assertRaisesRegex(ValueError, 'symlink loop'):
                build_image.grab(e, '/loop', output)


class SharedImageRebuildTest(unittest.TestCase):
    def setup_app(self, tmp):
        from idemu import catalog, server
        root = Path(tmp) / 'mgu22'; (root / 'guest').mkdir(parents=True)
        (root / 'Image').write_bytes(b'kernel')
        for name in mgu.GUEST_FILES: (root / 'guest' / name).write_bytes(b'helper')
        (root / 'base.cpio').write_bytes(b'corrupt shared image left by an earlier environment')
        for patcher in (patch.object(mgu, 'OUT', str(root)), patch.object(mgu, '_image_check', (None, False)),
                        patch.object(server, 'ENVS', str(Path(tmp) / 'envs')),
                        patch.object(server, 'require_system_files'), patch.object(server, 'files_ok', return_value=True),
                        patch.object(server, 'runtime_module', return_value=mgu),
                        patch.object(catalog, 'backend_supported', return_value=True),
                        patch.object(catalog, 'effective_psdz', return_value='firmware')):
            self.enterContext(patcher)
        app = server.App()
        return app, root

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate():
            if time.monotonic() > deadline: self.fail('Build did not reach the expected state')
            time.sleep(.01)

    def test_create_and_build_repairs_corrupt_shared_cache_and_rebuild_can_be_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, root = self.setup_app(tmp)
            env = app.create({'kind': 'mgu22', 'name': 'New ID8'})
            eid = env['id']
            self.assertEqual(env['build']['state'], 'none')
            started, release = threading.Event(), threading.Event()
            def build(*args, **kwargs):
                started.set()
                if not release.wait(3): raise TimeoutError('Test build was not released')
                (root / 'base.cpio').write_bytes(mgu._cpio([('file', 0o100644, b'data')]) * 6)
            with patch.object(mgu, 'build', side_effect=build) as builder:
                try:
                    app.start_build(eid)
                    self.assertTrue(started.wait(2))
                    self.assertEqual(app.build_info(eid)['state'], 'building')
                    release.set()
                    self.wait_for(lambda: eid not in app.builds)
                    self.assertEqual(app.build_info(eid)['state'], 'ready')
                    self.assertEqual(builder.call_count, 1)
                    app.start_build(eid)
                    self.assertEqual(builder.call_count, 1)  # A new wizard can reuse a validated image.
                    started.clear(); release.clear()
                    app.start_build(eid, force=True)
                    self.assertTrue(started.wait(2))
                    self.assertEqual(app.build_info(eid)['state'], 'building')
                    release.set()
                    self.wait_for(lambda: eid not in app.builds)
                    self.assertEqual(builder.call_count, 2)
                finally: release.set()

    def test_builder_returning_without_a_valid_image_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, root = self.setup_app(tmp)
            eid = app.create({'kind': 'mgu22', 'name': 'Invalid output'})['id']
            with patch.object(mgu, 'build'):
                app.start_build(eid)
                self.wait_for(lambda: app.build_info(eid)['state'] == 'error')
            self.assertIn('did not produce a valid image', app.build_info(eid)['error'])

    def test_shared_image_cannot_be_rebuilt_while_another_id8_environment_runs(self):
        from idemu import server
        with tempfile.TemporaryDirectory() as tmp:
            app, root = self.setup_app(tmp)
            eid = app.create({'kind': 'mgu22', 'name': 'Other ID8'})['id']
            app.rt = SimpleNamespace(id='running-id8', state='running', env={'kind': 'mgu22'})
            with patch.object(mgu, 'build') as builder, self.assertRaisesRegex(server.ApiError, 'shared image'):
                app.start_build(eid, force=True)
            builder.assert_not_called()


if __name__ == '__main__':
    unittest.main()

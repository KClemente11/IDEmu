#!/usr/bin/env python3
"""Install the audited welcome/disclaimer emulator experiment with image backups.

Run only with the selected environment stopped. Keeps original SWFL/system_files intact.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from idemu.qnxfs import mkdisk, qnx4
from patch_welcome_disclaimer import patch, SOURCE_SHA256

GUEST_HMI = '/repository/istep/opt/hmi/ID5/bin/HmiMain3D'


def image_entry(image, name):
    reader = qnx4.R(str(image))
    try:
        entry = next(entry for path, entry in reader.walk() if path == name)
        return reader.read(entry), reader.ps, reader.extents(entry)
    finally:
        reader.f.close()


def install(environment, source, timeout=10):
    environment = environment.resolve()
    images = environment / 'images'
    target = environment / 'overlay/sda/opt/hmi/ID5/bin/HmiMain3D'
    manifest_path = environment / 'welcome-disclaimer-patch.json'
    if target.exists() or manifest_path.exists():
        raise ValueError('Existing welcome overlay/manifest must be reviewed before another installation')
    if not 1 <= timeout <= 60:
        raise ValueError('Test timeout must be 1–60 seconds')
    patched, manifest = patch(source.read_bytes())
    original, partition, extents = image_entry(images / 'sda.img', GUEST_HMI)
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256 or len(original) != len(patched):
        raise ValueError('Built sda.img does not contain the audited original HmiMain3D')
    env_path = environment / 'env.json'
    env = json.loads(env_path.read_text(encoding='utf-8'))
    if env.get('kind') is not None:
        raise ValueError('Requires an Evo environment')
    backup = environment / ('welcome-disclaimer-backup-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    for name, src in [('env.json', env_path), ('sda.img', images / 'sda.img'), ('shim.img', images / 'shim.img')]:
        shutil.copy2(src, backup / name)
    (backup / 'HmiMain3D.original').write_bytes(original)
    temporary_sda = images / 'sda.img.welcome-new'
    temporary_shim = images / 'shim.img.welcome-new'
    if temporary_sda.exists() or temporary_shim.exists():
        raise ValueError('An earlier installation has staging images; review them first')
    try:
        shutil.copyfile(images / 'sda.img', temporary_sda)
        with temporary_sda.open('r+b') as output:
            pos = 0
            for block, count in extents:
                chunk = patched[pos:pos + count * 512]
                output.seek((partition + block - 1) * 512)
                output.write(chunk)
                pos += len(chunk)
        assert pos == len(patched)
        reader = qnx4.R(str(images / 'shim.img'))
        tree = mkdisk.Tree()
        try:
            for path, entry in reader.walk():
                if path in ('/.bitmap', '/.inodes'):
                    continue
                if stat.S_ISDIR(entry['mode']):
                    tree.mkdir(path, entry['mode'])
                    continue
                data = reader.read(entry)
                if path == '/coding.tab':
                    rows = [row for row in struct.iter_unpack('<HHBB', data)
                            if not (row[0] == 0x3001 and row[1] == 58 and row[2] == 0xFF)]
                    rows.append((0x3001, 58, 0xFF, timeout))
                    data = b''.join(struct.pack('<HHBB', *row) for row in rows)
                tree.add(path, entry['mode'], data, len(data), entry['mtime'])
        finally:
            reader.f.close()
        mkdisk.write(tree, str(temporary_shim), (images / 'shim.img').stat().st_size // 512)
        actual, _, _ = image_entry(temporary_sda, GUEST_HMI)
        if actual != patched:
            raise ValueError('Patched image verification failed')
        coding, _, _ = image_entry(temporary_shim, '/coding.tab')
        if (0x3001, 58, 0xFF, timeout) not in struct.iter_unpack('<HHBB', coding):
            raise ValueError('Disclaimer timing verification failed')
        env.setdefault('coding', {}).setdefault('extra', {})['LEGAL_DISCLAIMER_TIME'] = timeout
        env['fast_boot'] = False
        manifest.update(backup=str(backup), legal_disclaimer_time=timeout,
                        installed_in_images=True, original_product_line_unchanged=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(patched)
        os.replace(temporary_sda, images / 'sda.img')
        os.replace(temporary_shim, images / 'shim.img')
        env_path.write_text(json.dumps(env, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    except Exception:
        for name, dst in [('env.json', env_path), ('sda.img', images / 'sda.img'), ('shim.img', images / 'shim.img')]:
            shutil.copy2(backup / name, dst)
        if target.exists():
            target.unlink()
        raise
    finally:
        for staging in (temporary_sda, temporary_shim):
            if staging.exists():
                staging.unlink()
    print(json.dumps({'overlay': str(target), 'backup': str(backup),
                      'sha256': manifest['output_sha256'], 'timeout': timeout}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', type=Path)
    parser.add_argument('source', type=Path)
    parser.add_argument('--timeout', type=int, default=10)
    args = parser.parse_args()
    install(args.environment, args.source, args.timeout)

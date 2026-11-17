"""Refresh emulator-owned libraries in an existing Evo shim image before boot."""
import os
from pathlib import Path
import stat
from .qnxfs import mkdisk, qnx4


def refresh(image_dir, library_dir=None):
    library_dir = Path(library_dir or Path(__file__).parent / 'shim/lib')
    image = Path(image_dir) / 'shim.img'
    replacements = {}
    for name in ('libscreen.so.1', 'libBMWOTFapi.so.3'):
        data = (library_dir / name).read_bytes()
        if data[:6] != b'\x7fELF\x01\x01' or data[18:20] != b'\x28\x00':
            raise ValueError('Invalid Evo guest library: ' + name)
        replacements['/lib/' + name] = data
    reader = qnx4.R(str(image))
    try:
        # mkdisk generates filesystem metadata itself; copying it makes duplicate entries.
        entries = [(name, entry) for name, entry in reader.walk()
                   if name not in ('/.bitmap', '/.inodes')]
        changed = [name for name, entry in entries
                   if name in replacements and reader.read(entry) != replacements[name]]
        if not changed: return False
        tree = mkdisk.Tree()
        for name, entry in entries:
            if stat.S_ISDIR(entry['mode']): tree.mkdir(name, entry['mode'])
            else:
                data = replacements[name] if name in replacements else reader.read(entry)
                tree.add(name, entry['mode'], data, len(data), entry['mtime'])
    finally:
        reader.f.close()
    temporary = image.with_name('shim.img.updating')
    try:
        mkdisk.write(tree, str(temporary), image.stat().st_size // 512)
        os.replace(temporary, image)
    finally:
        if temporary.exists(): temporary.unlink()
    return True

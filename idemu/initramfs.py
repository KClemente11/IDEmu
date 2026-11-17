"""Streaming integrity checks for the concatenated newc archives used by MGU22."""
import os


def validate_cpio(path, expected_archives=None):
    size = os.path.getsize(path)
    offset = entries = archives = 0
    last_name = None
    with open(path, 'rb') as stream:
        while offset < size:
            stream.seek(offset)
            header = stream.read(110)
            if len(header) != 110 or header[:6] not in (b'070701', b'070702'):
                raise ValueError(f'Invalid initramfs header at byte {offset}; archive is incomplete or corrupted')
            try: fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
            except ValueError as error:
                raise ValueError(f'Invalid initramfs fields at byte {offset}') from error
            length, namesize = fields[6], fields[11]
            if not 1 <= namesize <= 65536:
                raise ValueError(f'Invalid initramfs filename length at byte {offset}')
            name = stream.read(namesize)
            if len(name) != namesize or name[-1:] != b'\0' or b'\0' in name[:-1]:
                raise ValueError(f'Truncated initramfs filename at byte {offset}')
            data = (offset + 110 + namesize + 3) & ~3
            end = (data + length + 3) & ~3
            if end > size:
                raise ValueError(f'Truncated initramfs entry at byte {offset}: {name[:-1]!r}')
            last_name = name[:-1]
            if last_name == b'TRAILER!!!':
                if length: raise ValueError('Initramfs trailer contains unexpected data')
                archives += 1
            entries += 1
            offset = end
    if last_name != b'TRAILER!!!' or not archives:
        raise ValueError('Initramfs is missing its final archive trailer')
    if expected_archives is not None and archives != expected_archives:
        raise ValueError(f'Initramfs contains {archives} complete archives; expected {expected_archives}')
    return {'entries': entries, 'archives': archives, 'size': size}

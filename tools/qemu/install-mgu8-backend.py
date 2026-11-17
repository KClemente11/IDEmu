"""Install IDEmu's Windows shared-RAM backend into a QEMU source tree."""
from pathlib import Path
import shutil
import sys


def install(source):
    source = Path(source)
    backend = Path(__file__).resolve().parents[2] / 'src' / 'qemu' / 'hostmem-idemu-win32.c'
    shutil.copy2(backend, source / 'backends' / backend.name)
    meson = source / 'backends' / 'meson.build'
    text = meson.read_text()
    if backend.name not in text:
        anchor = "if host_os != 'windows'"
        if anchor not in text:
            raise RuntimeError('Unsupported QEMU backends/meson.build: Windows guard not found')
        text = text.replace(anchor, "if host_os == 'windows'\n  system_ss.add(files('hostmem-idemu-win32.c'))\nendif\n\n" + anchor, 1)
        meson.write_text(text, newline='\n')
    # -object is decoded through QAPI's ObjectOptions union, even for QOM
    # classes that are already registered. Register the CLI schema as well.
    schema = source / 'qapi' / 'qom.json'
    text = schema.read_text()
    if "'struct': 'MemoryBackendIdemuProperties'" not in text:
        marker = '##\n# @MemoryBackendShmProperties:'
        enum = "    'memory-backend-ram',\n"
        union = "      'memory-backend-ram':         'MemoryBackendProperties',\n"
        if not all(anchor in text for anchor in (marker, enum, union)):
            raise RuntimeError('Unsupported QEMU qapi/qom.json: memory backend anchors not found')
        properties = """##
# @MemoryBackendIdemuProperties:
#
# IDEmu Windows shared guest RAM.
#
# @mapping-name: Name of the mapping initialized by IDEmu.
#
# Since: 11.1
##
{ 'struct': 'MemoryBackendIdemuProperties',
  'base': 'MemoryBackendProperties',
  'data': { 'mapping-name': 'str' },
  'if': 'CONFIG_WIN32' }

"""
        text = text.replace(marker, properties + marker, 1)
        text = text.replace(enum, enum + "    { 'name': 'memory-backend-idemu', 'if': 'CONFIG_WIN32' },\n", 1)
        text = text.replace(union, union + "      'memory-backend-idemu':       { 'type': 'MemoryBackendIdemuProperties', 'if': 'CONFIG_WIN32' },\n", 1)
        schema.write_text(text, newline='\n')


if __name__ == '__main__':
    install(sys.argv[1])

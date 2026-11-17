#!/usr/bin/env python3
"""Experimental Evo emulator overlay: redirect startup disclaimer to native welcome.

Only accepts the audited original binary for the explicitly selected version.
007_051_002 is emulator-tested; 006_017_006 is a static port. Not an on-car installer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

SOURCE_SHA256 = 'fe770d1957fdfcd250d1f8cf7fba0e9a7c25e8c053e59f04f3274055fedda935'
SOURCE_SHA256_006 = '2c906b5c6799a37a17b0ed51c37f67e0c1a2bc0edfb87596008f075062e9e6bf'

# Canonical 007 addresses -> independently inspected 006 counterparts.
ADDRESSES_006 = {
    0x35121C: 0x335970, 0x351220: 0x335974, 0x35122C: 0x335980,
    0x351260: 0x3359B4, 0x3514B0: 0x335C04,
    0x3410DC: 0x32857C, 0x34101C: 0x3284BC, 0x341020: 0x3284C0,
    0x34104C: 0x3284EC, 0x341050: 0x3284F0,
    0x352194: 0x3368A8, 0x352198: 0x3368AC,
    0x3512BC: 0x335A10, 0x3512D4: 0x335A28, 0x351380: 0x335AD4,
    0x351180: 0x3358D4, 0x351450: 0x335BA4,
    0x34E0F4: 0x332924, 0x34F280: 0x333B88,
}
EXPECTED_006 = {0x35121C: 0xEB51375D, 0x351260: 0xEB51374C, 0x3514B0: 0xEB5136B8}


def patch(data, firmware='007_051_002'):
    if firmware not in ('007_051_002', '006_017_006'):
        raise ValueError('Unsupported firmware profile')
    source_hash = SOURCE_SHA256_006 if firmware == '006_017_006' else SOURCE_SHA256
    addresses = ADDRESSES_006 if firmware == '006_017_006' else {}
    expected_words = EXPECTED_006 if firmware == '006_017_006' else {}
    address = lambda canonical: addresses.get(canonical, canonical)
    if hashlib.sha256(data).hexdigest() != source_hash:
        raise ValueError('Requires the audited original %s HmiMain3D; input hash differs' % firmware)
    blob = bytearray(data)
    phoff = struct.unpack_from('<I', data, 28)[0]
    phentsize, phnum = struct.unpack_from('<HH', data, 42)

    def offset(va):
        for i in range(phnum):
            kind, off, addr, _, size, *_ = struct.unpack_from('<8I', data, phoff + i * phentsize)
            if kind == 1 and addr <= va < addr + size:
                return off + va - addr
        raise ValueError('Address outside file-backed ELF load segments')

    changes = []
    def branch(source, target, link=False):
        delta = target - source - 8
        if delta % 4 or not -(1 << 25) <= delta < (1 << 25):
            raise ValueError('ARM branch is out of range')
        return (0xEB000000 if link else 0xEA000000) | ((delta // 4) & 0xFFFFFF)

    # Add eight zero-initialized bytes at the end of the existing writable LOAD segment.
    # They hold a pending disclaimer pointer and a once-per-process sent flag.
    loads = []
    for i in range(phnum):
        header = phoff + i * phentsize
        fields = struct.unpack_from('<8I', data, header)
        if fields[0] == 1 and fields[6] & 2:
            loads.append((header, fields))
    header, fields = max(loads, key=lambda item: item[1][2] + item[1][5])
    pending = (fields[2] + fields[5] + 3) & ~3
    new_memsz = pending + 8 - fields[2]
    # Keep the existing popup timeout and track the replacement's close event.
    sites = [(0x35121C, 0xEB54367A, 0xE3000493, 'Timed disclaimer request: state 1171'),
             (0x351220, 0xE3A02000, 0xE3A02001, 'Allow this timed replacement request when emulator display reports off'),
             (0x35122C, 0xE2822001, 0xE3A02001, 'Preserve request activation argument after setting flag 1'),
             (0x351260, 0xEB543669, 0xE3000493, 'Untimed disclaimer request: state 1171'),
             (0x3514B0, 0xEB5435D5, 0xE3000493, 'Track native welcome closure as disclaimer completion'),
             (0x3410DC, 0x18BD8830, 0xE1A00000, 'Register welcome popup requirements despite the suppressing variant'),
             (0x34101C, 0xE92D4800, 0xE3A00001, 'Welcome-specific availability returns true'),
             (0x341020, 0xE28DB004, 0xE12FFF1E, 'Return from welcome availability override'),
             (0x34104C, 0xE92D4800, 0xE3A00001, 'Welcome-specific initialization eligibility returns true'),
             (0x341050, 0xE28DB004, 0xE12FFF1E, 'Return from welcome initialization override'),
             (0x352194, 0xE1A02000, 0xE3A02001, 'Emulator: initial disclaimer callback monitor-on argument'),
             (0x352198, 0xE1A01005, 0xE3A01001, 'Emulator: initial disclaimer callback display-enabled argument')]
    # Wait for the real user-on notification after startup, rather than opening during init.
    # Reuse the original disclaimer confirmation routine, which this replacement never displays.
    queue, trigger = address(0x3512BC), address(0x3512D4)
    words = [0xE59FC00C, 0xE59C3004, 0xE3530000, 0x058C0000, 0xE12FFF1E, pending,
             0xE3510063, 0x13510064, 0x112FFF1E, 0xE92D4010,
             0xE59F4020, 0xE5940000, 0xE3500000, 0x08BD8010,
             0xE3A03000, 0xE5843000, 0xE3A03001, 0xE5843004,
             branch(trigger + 12 * 4, address(0x351180), True), 0xE8BD8010, pending]
    assert queue + len(words) * 4 <= address(0x351380)
    for i, word in enumerate(words):
        va = queue + i * 4
        sites.append((va, struct.unpack_from('<I', data, offset(va))[0], word,
                      'Deferred disclaimer-to-welcome bridge'))
    sites += [(0x351450, 0xEBFFFF4A, branch(address(0x351450), queue, True), 'Queue the disclaimer replacement'),
              (0x34E0F4, 0xE92D4830, branch(address(0x34E0F4), trigger), 'Open pending welcome on user-on status'),
              (0x34F280, 0xE12FFF34, 0xE1A00000, 'Skip the synthetic initial power callback'),
              (0x100000 + header + 20, fields[5], new_memsz, 'Reserve bridge state in writable LOAD memory')]
    for va, expected, replacement, purpose in sites:
        expected = expected_words.get(va, expected)
        va = address(va)
        off = offset(va)
        actual = struct.unpack_from('<I', blob, off)[0]
        if actual != expected:
            raise ValueError('Unexpected instruction at %#x' % va)
        struct.pack_into('<I', blob, off, replacement)
        changes.append(dict(va=hex(va), file_offset=hex(off), original=hex(actual),
                            replacement=hex(replacement), purpose=purpose))
    result = bytes(blob)
    return result, dict(firmware=firmware, source_sha256=source_hash,
                        output_sha256=hashlib.sha256(result).hexdigest(), changes=changes,
                        bridge_state_va=hex(pending),
                        status=('static port; full 006 HMI runtime not validated' if firmware == '006_017_006'
                                else 'experimental emulator overlay; opens after detailed mode 0x63 or 0x64'),
                        emulator_display_bootstrap=True, physical_unit_validated=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('environment', type=Path)
    parser.add_argument('--firmware', choices=('007_051_002', '006_017_006'), default='007_051_002')
    args = parser.parse_args()
    result, manifest = patch(args.source.read_bytes(), args.firmware)
    target = args.environment / 'overlay/sda/opt/hmi/ID5/bin/HmiMain3D'
    if target.exists():
        raise SystemExit('Overlay already contains HmiMain3D; preserve it before installing this experiment')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result)
    manifest_path = args.environment / 'welcome-disclaimer-patch.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(target)
    print(manifest['output_sha256'])


if __name__ == '__main__':
    main()

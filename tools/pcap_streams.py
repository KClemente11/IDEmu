#!/usr/bin/env python3
"""Lê uma captura do loopback do guest (tcpdump -w, link-type NULL) e remonta os fluxos TCP.

Uso: python3 tools/pcap_streams.py c.pcap [bytes_por_fluxo=256]
Mostra, por conexão (cliente -> servidor), o tamanho total e os primeiros bytes em hex/ASCII — base para
estudar o protocolo DSI/SIPC entre `most`, servicebroker, HMI e NBTCarHU.
"""
import struct
import sys
import collections


def read_pcap(path):
    d = open(path, 'rb').read()
    magic = d[:4]
    if magic in (b'\xd4\xc3\xb2\xa1', b'\x4d\x3c\xb2\xa1'):
        e = '<'
    elif magic in (b'\xa1\xb2\xc3\xd4', b'\xa1\xb2\x3c\x4d'):
        e = '>'
    else:
        raise SystemExit('não é pcap')
    linktype = struct.unpack(e + 'I', d[20:24])[0]
    off = 24
    while off + 16 <= len(d):
        ts_s, ts_u, caplen, _ = struct.unpack(e + 'IIII', d[off:off + 16])
        off += 16
        yield ts_s + ts_u / 1e6, linktype, d[off:off + caplen]
        off += caplen


def main():
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    flows = collections.OrderedDict()
    for ts, lt, pkt in read_pcap(path):
        if lt == 0:           # BSD loopback: 4 bytes de família (ordem do host, pode vir em qualquer ordem)
            pkt = pkt[4:]
        elif lt == 1:         # ethernet
            pkt = pkt[14:]
        if not pkt or pkt[0] >> 4 != 4:
            continue
        ihl = (pkt[0] & 15) * 4
        if pkt[9] != 6:
            continue
        src, dst = pkt[12:16], pkt[16:20]
        tcp = pkt[ihl:]
        sp, dp, seq, ack = struct.unpack('>HHII', tcp[:12])
        doff = (tcp[12] >> 4) * 4
        flags = tcp[13]
        data = tcp[doff:]
        key = (src, sp, dst, dp)
        f = flows.setdefault(key, {'t0': ts, 'segs': {}, 'syn': False})
        if flags & 2:
            f['syn'] = True
        if data:
            f['segs'][seq] = data
    for (src, sp, dst, dp), f in flows.items():
        buf = b''
        for sq in sorted(f['segs']):
            buf += f['segs'][sq]
        ip = lambda b: '.'.join(str(x) for x in b)
        print('%s:%d -> %s:%d  t=%.2f  %d bytes' % (ip(src), sp, ip(dst), dp, f['t0'], len(buf)))
        if buf:
            print('   hex  ', buf[:n].hex())
            print('   ascii', ''.join(chr(c) if 32 <= c < 127 else '.' for c in buf[:n]))


if __name__ == '__main__':
    main()

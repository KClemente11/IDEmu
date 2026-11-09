#!/usr/bin/env python3
"""Contorno do pânico do kernel do MGU (4.14.x-apl) no QEMU: divide error em tk_setup_internals.

O kernel usa o relógio do TSC como relógio inicial e só calcula mult/shift dele quando a frequência do TSC é "conhecida"
(CPUID 0x15 do Apollo Lake). O QEMU/TCG não expõe essa folha, então mult = 0 e a divisão estoura.
Este utilitário liga-se ao gdbstub do QEMU (iniciado com -gdb tcp::PORT -S), para antes de timekeeping_init,
grava mult/shift válidos em clocksource_tsc e deixa o guest continuar. Nada no kernel é alterado em disco.
Uso: tscfix.py PORTA [bz_do_kernel]   (os endereços abaixo valem para os kernels 4.14.198/4.14.300 do MGU)
"""
import socket, sys, time

CALL_SITE = {   # timekeeping_init: chamada de clocksource_default_clock
    'default': 0xffffffff810e7540,   # tk_setup_internals (1ª chamada: timekeeping_init)
}
MULT, SHIFT = 0xffffffff81c25290, 0xffffffff81c25294

def pkt(s, data):
    cs = sum(data.encode()) & 0xff
    s.sendall(('$%s#%02x' % (data, cs)).encode())

def read(s, timeout=60):
    s.settimeout(timeout); buf = b''
    while True:
        c = s.recv(1)
        if not c: raise EOFError
        if c == b'$': buf = b''; continue
        if c == b'#': s.recv(2); s.sendall(b'+'); return buf.decode()
        buf += c

def cmd(s, data, timeout=60):
    pkt(s, data)
    while True:
        c = s.recv(1)
        if c == b'+': break
    return read(s, timeout)

def main(port, addr=None):
    addr = addr or CALL_SITE['default']
    for _ in range(100):
        try: s = socket.create_connection(('127.0.0.1', int(port))); break
        except OSError: time.sleep(.1)
    cmd(s, 'qSupported:swbreak+;hwbreak+')
    r = cmd(s, 'Z0,%x,1' % addr)
    if r != 'OK': raise SystemExit('Z0 falhou: ' + r)
    pkt(s, 'c')
    while s.recv(1) != b'+': pass
    r = read(s, 300)                                   # T05...: parou no ponto
    print('parou:', r[:60], flush=True)
    print('mult', cmd(s, 'M%x,4:%s' % (MULT, (0x01000000).to_bytes(4, 'little').hex())), flush=True)
    print('shift', cmd(s, 'M%x,4:%s' % (SHIFT, (24).to_bytes(4, 'little').hex())), flush=True)
    cmd(s, 'z0,%x,1' % addr)
    pkt(s, 'c'); s.close()
    print('tscfix: mult/shift gravados, guest liberado')

if __name__ == '__main__': main(*sys.argv[1:3])

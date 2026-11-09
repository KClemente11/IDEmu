#!/usr/bin/env python3
"""Passo a passo da ISR do devc-sersci quando chega um caractere no SCIF1: envia 'e' e segue a execução de usuário."""
import os, socket, subprocess, sys, time, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootinfo, dis as D
from gdbc import Gdb
HOME = os.path.expanduser('~')
d = '/tmp/cic'
edits = [bootinfo.root_password_edit('root'), (b'/usr/bin/srv-starter-QNX', b'/bin/echo' + bytes(15)),
         (b'/bin/login\0login\0', b'/bin/ksh\0\0\0-ksh\0\0')]
bootinfo.build(HOME + '/Downloads/System files/ID4/swfl_000003a6.bin.008_090_002', d + '/ifs.bin', edits=edits)
try: os.remove(d + '/ser1.sock')
except OSError: pass
cmd = [HOME + '/id4-qemu/build/qemu-system-sh4', '-M', 'cic', '-m', '256', '-display', 'none', '-monitor', 'none',
       '-serial', 'file:%s/ser0.txt' % d, '-chardev', 'socket,id=s1,path=%s/ser1.sock,server=on,wait=off,logfile=%s/ser1.log' % (d, d),
       '-serial', 'chardev:s1', '-gdb', 'tcp:127.0.0.1:1234',
       '-device', 'loader,file=%s/ifs.bin,addr=0x08010000,force-raw=on' % d, '-device', 'loader,addr=0x880138e0,cpu-num=0']
p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
try:
    g = Gdb(1234)
    # espera o prompt: deixa rodar ~20 s e interrompe
    g._send('c'); time.sleep(float(os.environ.get('WAIT', '22')))
    g.s.sendall(b'\x03'); g._recv()
    c = socket.socket(socket.AF_UNIX); c.connect(d + '/ser1.sock')
    c.sendall(b'e')
    g.bp(0x88009600)
    g.s.settimeout(60)
    while True:
        g._send('c'); g._recv()
        ev = g.u32(0xff000028)
        if ev == 0x7a0:
            break
        g.unbp(0x88009600); g.step(); g.bp(0x88009600)
    print('INTEVT', hex(ev), flush=True)
    g.unbp(0x88009600)
    n = 0; last = None
    for i in range(int(os.environ.get('STEPS', '6000'))):
        rg = g.regs(); pc = rg['pc']
        if pc < 0x80000000 or (0x08040000 <= pc < 0x08050000):
            print('%08x r0=%08x r1=%08x r2=%08x r3=%08x r4=%08x' % (pc, rg['r0'], rg['r1'], rg['r2'], rg['r3'], rg['r4']), flush=True)
        g.step()
finally:
    p.kill()

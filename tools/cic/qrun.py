#!/usr/bin/env python3
"""Roda o QEMU da placa CIC por N segundos e mostra console, log de periféricos e registradores finais.
uso: qrun.py SEGUNDOS [--ifs arquivo] [--dir pasta] [-- args extras do qemu]"""
import os, subprocess, sys, time, socket, signal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootinfo
HOME = os.path.expanduser('~')
QEMU = os.environ.get('CIC_QEMU', HOME + '/id4-qemu/build/qemu-system-sh4')
IFS = HOME + '/Downloads/System files/ID4/swfl_000003a6.bin.008_090_002'

def main():
    a = sys.argv[1:]
    secs = float(a.pop(0)) if a else 10
    ifs = IFS; d = '/tmp/cic'; extra = []; dflags = 'unimp,guest_errors'; mons = []
    while a:
        x = a.pop(0)
        if x == '--ifs': ifs = a.pop(0)
        elif x == '--dir': d = a.pop(0)
        elif x == '--d': dflags = a.pop(0)
        elif x == '--mon': mons.append(a.pop(0))
        elif x == '--': extra = a; break
    os.makedirs(d, exist_ok=True)
    for f in ('ser0.txt', 'ser1.txt', 'log.txt', 'out.txt'):
        try: os.remove(os.path.join(d, f))
        except OSError: pass
    mon = os.path.join(d, 'mon.sock')
    try: os.remove(mon)
    except OSError: pass
    bootinfo.build(ifs, d + '/ifs.bin', edits=[bootinfo.root_password_edit('root')])
    ifs = d + '/ifs.bin'
    cmd = [QEMU, '-M', 'cic', '-m', '256', '-display', 'none', '-monitor', 'unix:%s,server,nowait' % mon,
           '-serial', 'file:%s/ser0.txt' % d, '-serial', 'file:%s/ser1.txt' % d, '-d', dflags, '-D', d + '/log.txt',
           '-device', 'loader,file=%s,addr=0x08010000,force-raw=on' % ifs, '-device', 'loader,addr=0x880138e0,cpu-num=0'] + extra
    p = subprocess.Popen(cmd, stdout=open(d + '/out.txt', 'w'), stderr=subprocess.STDOUT)
    time.sleep(secs)
    regs = ''
    try:
        s = socket.socket(socket.AF_UNIX); s.connect(mon); s.settimeout(3); time.sleep(0.3)
        s.recv(4096); s.send(b'info registers\n'); time.sleep(0.5); regs = s.recv(65536).decode('latin1')
        for c in mons:
            s.send(c.encode() + b'\n'); time.sleep(0.4); regs += s.recv(65536).decode('latin1')
        s.send(b'quit\n')
    except Exception as e:
        regs = 'sem monitor: %s' % e
    time.sleep(0.3)
    if p.poll() is None: p.kill()
    for f in ('out.txt', 'log.txt', 'ser0.txt', 'ser1.txt'):
        print('=== %s' % f)
        try: print(open(os.path.join(d, f), 'rb').read()[:6000].decode('latin1'))
        except OSError: pass
    print('=== regs'); print(regs)

main()

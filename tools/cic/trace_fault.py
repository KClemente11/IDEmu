#!/usr/bin/env python3
"""Passo a passo no tratador de falha de página do kernel (QNX 6.3/SH) quando TEA == alvo.
uso: trace_fault.py [TEA_alvo [nsteps]]"""
import os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootinfo, dis as D, struct
from gdbc import Gdb

HOME = os.path.expanduser('~')
QEMU = HOME + '/id4-qemu/build/qemu-system-sh4'
IFS = HOME + '/Downloads/System files/ID4/swfl_000003a6.bin.008_090_002'
tea_target = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x7bff0000
nsteps = int(sys.argv[2], 0) if len(sys.argv) > 2 else 3000
SLOW = 0x88049160   # caminho lento do tlb miss (ver vetor 0x88009400)

d = '/tmp/cic'; os.makedirs(d, exist_ok=True)
bootinfo.build(IFS, d + '/ifs.bin')
cmd = [QEMU, '-M', 'cic', '-m', '256', '-display', 'none', '-monitor', 'none', '-serial', 'file:%s/ser0.txt' % d,
       '-serial', 'file:%s/ser1.txt' % d, '-gdb', 'tcp:127.0.0.1:1234',
       '-device', 'loader,file=%s/ifs.bin,addr=0x08010000,force-raw=on' % d, '-device', 'loader,addr=0x880138e0,cpu-num=0']
p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
try:
    g = Gdb(1234)
    g.bp(SLOW)
    kdata = open(os.path.expanduser('~') + '/id4-qemu/dummy', 'a') if False else None
    # imagem do kernel para desmontar (procnto-instr extraído)
    sp = os.environ.get('SP', '')
    kern = None
    for cand in (sp + '/id4/ifs/proc/boot/procnto-instr',):
        if os.path.exists(cand):
            kern = open(cand, 'rb').read()
    def kdis(pc):
        if kern and 0x88020000 <= pc < 0x8807d762:
            o = 0x1000 + pc - 0x88020000
            w = struct.unpack_from('<H', kern, o)[0]
            t = D.dis1(w, pc)
            v = D.lit(kern, 0x8801f000, pc, w)
            return t + ('' if v is None else '   ; =0x%x' % (v & 0xffffffff))
        return ''
    n = 0
    while True:
        r = g.cont()
        try:
            tea = g.u32(0xff00000c)
        except Exception as e:
            print('erro lendo TEA', e, flush=True); tea = 0
        n += 1
        if n % 10 == 1: print('parada %d tea=%08x' % (n, tea), flush=True)
        if tea == tea_target:
            break
        g.unbp(SLOW); g.step(); g.bp(SLOW)
    print('parado no caminho lento, TEA=%08x (parada %d)' % (tea, n))
    for i in range(nsteps):
        rg = g.regs()
        pc = rg['pc']
        print('%08x %-40s r0=%08x r1=%08x r2=%08x r3=%08x r4=%08x r5=%08x r6=%08x r7=%08x' % (
            pc, kdis(pc), rg['r0'], rg['r1'], rg['r2'], rg['r3'], rg['r4'], rg['r5'], rg['r6'], rg['r7']))
        g.step()
finally:
    p.kill()

#!/usr/bin/env python3
"""Rastreia (instrução a instrução) o dev-ipc depois que ele começa a ler um quadro da FPGA.
Pré-requisito: QEMU rodando com CIC_XARGS="-gdb tcp:127.0.0.1:1234" e CIC_FPGA_IRQ=1.
uso: trace_ipc.py ELF_DO_DEV_IPC [n_passos [esperar_n_tx_ch2]]"""
import os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dis as D
from gdbc import Gdb
from elfx import Elf

el = Elf(sys.argv[1])
nsteps = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
wait_n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
LOG = os.environ.get('CIC_DIR', '/tmp/cic') + '/log.txt'
READER = 0x08043fca      # antes do jsr 0x8041ee0(canal), no caminho de contabilização de quadros do dev-ipc (r4 = canal)
WANT_CH = int(os.environ.get('WANT_CH', '2'))

while True:
    try:
        if open(LOG, errors='ignore').read().count('ipc: TX dados 09 02 12') >= wait_n:
            break
    except OSError:
        pass
    time.sleep(0.5)

g = Gdb(1234, retries=400)
g.s.settimeout(600)
ref = el.d[el.off(READER):el.off(READER) + 8]
g.bp(READER)
hits = 0
while True:
    g.cont()
    rg = g.regs()
    ok = False
    try:
        ok = g.mem(READER, 8) == ref and rg['pc'] == READER and rg['r4'] == WANT_CH
    except Exception:
        pass
    hits += 1
    if ok:
        print('parado no tratador (hit %d) canal=%x' % (hits, rg['r4']), flush=True)
        break
    g.unbp(READER); g.step(); g.bp(READER)

g.unbp(READER)
for i in range(nsteps):
    rg = g.regs()
    pc = rg['pc']
    o = el.off(pc) if 0x08040000 <= pc < 0x08050000 else None
    if o is not None:
        w = struct.unpack_from('<H', el.d, o)[0]
        t = D.dis1(w, pc)
        extra = ''
        if t.startswith(('jsr', 'bsr', 'jmp')):
            extra = '  -> r0=%x r1=%x r2=%x r3=%x r4=%x r5=%x r6=%x r7=%x' % tuple(rg['r%d' % k] for k in range(8))
        print('%08x  %s%s' % (pc, t, extra), flush=True)
    elif not (0x88009400 <= pc < 0x88009440):
        print('%08x  (fora do dev-ipc) r0=%x r4=%x r5=%x' % (pc, rg['r0'], rg['r4'], rg['r5']), flush=True)
    g.step()

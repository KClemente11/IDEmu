#!/usr/bin/env python3
"""Roda o iDrive 8 fora da interface web. A tela vai para mgu22/screen.png (atualizada a cada 2 s).
Uso: run.py [--seconds N] [--debug]   (sem --seconds roda até Ctrl-C)"""
import os, signal, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from idemu import mgu
secs = float(sys.argv[sys.argv.index('--seconds') + 1]) if '--seconds' in sys.argv else None
if not mgu.image_ready(): sys.exit('rode antes: tools/mgu/build_image.py')
rt = mgu.MguRuntime(os.path.join(ROOT, 'mgu22', 'cli'), {'id': 'mgu22-cli'}, debug='--debug' in sys.argv)
signal.signal(signal.SIGTERM, lambda *a: (rt.stop(), os._exit(0)))
rt.start(); t0 = time.time(); last = 0
print('pasta de execução:', rt.run, flush=True)
open(os.path.join(ROOT, 'mgu22', 'run.path'), 'w').write(rt.run)
try:
    while rt.state in ('booting', 'running') and (secs is None or time.time() - t0 < secs):
        time.sleep(2)
        png, seq = rt.screen_png()
        if png and seq != last:
            open(os.path.join(ROOT, 'mgu22', 'screen.png'), 'wb').write(png); last = seq
            print(f'{time.time() - t0:6.0f} s  quadro #{seq}  {rt.state}', flush=True)
    if rt.err: print('erro:', rt.err)
except KeyboardInterrupt: pass
finally: rt.stop()

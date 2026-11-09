#!/usr/bin/env python3
# gsh.py 'comando' [espera_s]: roda no console do guest e mostra a saída nova de serial.log
import os,sys,time
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..','mgu22')
R=open(OUT+'/run.path').read(); p=OUT+'/cli/logs/console.log'; sz=os.path.getsize(p); w=float(sys.argv[2]) if len(sys.argv)>2 else 1
open(R+'/console.in','w').write(sys.argv[1]+'\n'); time.sleep(w)
d=open(p,'rb').read()[sz:].decode('latin1')
for l in d.splitlines():
    if 'kretprobe' in l or 'Minidump' in l: continue
    print(l[:int(os.environ.get('W','240'))])

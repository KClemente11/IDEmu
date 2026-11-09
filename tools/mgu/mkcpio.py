#!/usr/bin/env python3
# cpio newc mínimo: mkcpio.py saida.cpio [nome:modo:arquivo|nome:dir ...]
import sys,os,struct
def ent(o,name,mode,data,ino):
    nm=name.encode()+b'\0'
    h='070701'+''.join('%08X'%v for v in (ino,mode,0,0,1,0,len(data),0,0,0,0,len(nm),0))
    b=h.encode()+nm; b+=b'\0'*((4-len(b)%4)%4); o.write(b); o.write(data); o.write(b'\0'*((4-len(data)%4)%4))
with open(sys.argv[1],'wb') as o:
    ino=1
    for a in sys.argv[2:]:
        p=a.split(':')
        if p[1]=='dir': ent(o,p[0],0o40755,b'',ino)
        else: ent(o,p[0],0o100000|int(p[1],8),open(p[2],'rb').read(),ino)
        ino+=1
    ent(o,'TRAILER!!!',0,b'',ino)

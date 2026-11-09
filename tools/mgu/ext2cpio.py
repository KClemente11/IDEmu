#!/usr/bin/env python3
# Converte a imagem ext4 inteira em cpio newc (initramfs). Uso: ext2cpio.py img saida.cpio
import sys,stat,struct,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from ext4ls import E4
e=E4(sys.argv[1]); o=open(sys.argv[2],'wb'); n=[0,0]; SRC=sys.argv[3] if len(sys.argv)>3 else '/'; PFX=sys.argv[4] if len(sys.argv)>4 else ''
def ent(name,mode,data,ino,uid=0,gid=0,rd=(0,0)):
    nm=name.encode()+b'\0'
    h='070701'+''.join('%08X'%v for v in (ino,mode,uid,gid,1,0,len(data),0,0,rd[0],rd[1],len(nm),0))
    b=h.encode()+nm; b+=b'\0'*((4-len(b)%4)%4); o.write(b); o.write(data); o.write(b'\0'*((4-len(data)%4)%4)); n[0]+=1; n[1]+=len(data)
seen={}
def walk(i,p):
    for nm,ino,ft in e.entries(i):
        if nm in('.','..','lost+found'): continue
        t=e.inode(ino); m=e.mode(t); pp=(p+'/'+nm).lstrip('/')
        uid=struct.unpack('<H',t[2:4])[0]; gid=struct.unpack('<H',t[24:26])[0]
        if stat.S_ISDIR(m): ent(pp,m,b'',ino,uid,gid); walk(ino,pp)
        elif stat.S_ISREG(m) or stat.S_ISLNK(m): ent(pp,m,e.data(t),ino,uid,gid)
        elif stat.S_ISCHR(m) or stat.S_ISBLK(m):
            d=struct.unpack('<I',t[40:44])[0]; ent(pp,m,b'',ino,uid,gid,((d>>8)&0xfff,d&0xff))
if PFX:
    q=''
    for c in PFX.strip('/').split('/'):
        q=(q+'/'+c).lstrip('/'); ent(q,0o40755,b'',1)
walk(e.lookup(SRC) if SRC!='/' else 2,PFX.strip('/'))
ent('TRAILER!!!',0,b'',1)
print('entradas',n[0],'bytes',n[1])

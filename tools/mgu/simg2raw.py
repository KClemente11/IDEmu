#!/usr/bin/env python3
# gz + Android sparse -> raw (streaming)
import gzip,struct,sys
src,dst=sys.argv[1:3]
f=gzip.open(src,'rb')
h=f.read(28); magic,maj,minr,fhs,chs,bs,tb,tc,cs=struct.unpack('<IHHHHIIII',h)
assert magic==0xED26FF3A,hex(magic)
print('sparse bs',bs,'blocks',tb,'chunks',tc,'size',bs*tb,flush=True)
f.read(fhs-28)
o=open(dst,'wb'); o.truncate(bs*tb); pos=0
for i in range(tc):
    t,_,sz,total=struct.unpack('<HHII',f.read(chs))
    n=sz*bs
    if t==0xCAC1:
        o.seek(pos); r=n
        while r:
            b=f.read(min(r,1<<24)); o.write(b); r-=len(b)
    elif t==0xCAC2:
        v=f.read(4)
        if v!=b'\0\0\0\0':
            o.seek(pos); o.write(v*(n//4))
    elif t==0xCAC3: pass
    elif t==0xCAC4: f.read(4)
    pos+=n
o.close(); print('ok',flush=True)

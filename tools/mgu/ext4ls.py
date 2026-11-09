#!/usr/bin/env python3
# leitor ext4 mínimo (só leitura): ls, cat, extração para diretório. Uso: ext4ls.py img ls /path | cat /path | x /path destdir
import struct,sys,os,stat
class E4:
    def __init__(s,p):
        s.f=open(p,'rb'); s.f.seek(1024); sb=s.f.read(1024)
        assert struct.unpack('<H',sb[56:58])[0]==0xEF53
        s.bs=1024<<struct.unpack('<I',sb[24:28])[0]; s.ipg=struct.unpack('<I',sb[40:44])[0]; s.isz=struct.unpack('<H',sb[88:90])[0]; s.bpg=struct.unpack('<I',sb[32:36])[0]
        s.fc=struct.unpack('<I',sb[92:96])[0]; s.ic=struct.unpack('<I',sb[96:100])[0]; s.ro=struct.unpack('<I',sb[100:104])[0]; s.dsz=struct.unpack('<H',sb[254:256])[0] or 32; s.first=struct.unpack('<I',sb[20:24])[0]
        s.b64=bool(s.ic&0x80); s.gdt=(s.first+1)*s.bs
    def rd(s,o,n): s.f.seek(o); return s.f.read(n)
    def inode(s,i):
        g=(i-1)//s.ipg; idx=(i-1)%s.ipg; d=s.rd(s.gdt+g*s.dsz,s.dsz); it=struct.unpack('<I',d[8:12])[0]
        if s.b64 and s.dsz>=64: it|=struct.unpack('<I',d[40:44])[0]<<32
        return s.rd(it*s.bs+idx*s.isz,s.isz)
    def size(s,ino): return struct.unpack('<I',ino[4:8])[0]|(struct.unpack('<I',ino[108:112])[0]<<32)
    def mode(s,ino): return struct.unpack('<H',ino[0:2])[0]
    def extents(s,b):
        m,n,_,dep=struct.unpack('<HHHH',b[:8]); assert m==0xF30A
        out=[]
        for k in range(n):
            e=b[12+k*12:24+k*12]
            if dep==0:
                lb,ln,hi,lo=struct.unpack('<IHHI',e); u=ln>0x8000
                if u: ln-=0x8000
                out.append((lb,ln,(hi<<32)|lo,u))
            else:
                lb,lo,hi,_=struct.unpack('<IIHH',e); out+=s.extents(s.rd(((hi<<32)|lo)*s.bs,s.bs))
        return out
    def data(s,ino):
        sz=s.size(ino); fl=struct.unpack('<I',ino[32:36])[0]
        if stat.S_ISLNK(s.mode(ino)) and sz<60 and not fl&0x80000: return ino[40:40+sz]
        if fl&0x10000000: return ino[40:100][:sz]
        out=bytearray(sz)
        if fl&0x80000:
            for lb,ln,pb,u in s.extents(ino[40:100]):
                if u: continue
                st=lb*s.bs
                if st>=sz: continue
                b=s.rd(pb*s.bs,ln*s.bs)[:sz-st]; out[st:st+len(b)]=b
        else:
            ptr=struct.unpack('<15I',ino[40:100]); blks=[]
            for p in ptr[:12]: blks.append(p)
            if ptr[12]:
                ib=s.rd(ptr[12]*s.bs,s.bs); blks+=list(struct.unpack('<%dI'%(s.bs//4),ib))
            for i,p in enumerate(blks):
                if p and i*s.bs<sz:
                    b=s.rd(p*s.bs,s.bs)[:sz-i*s.bs]; out[i*s.bs:i*s.bs+len(b)]=b
        return bytes(out)
    def entries(s,i):
        d=s.data(s.inode(i)); p=0; out=[]
        while p+8<=len(d):
            ino,rl,nl,ft=struct.unpack('<IHBB',d[p:p+8])
            if rl<8: break
            if ino and nl: out.append((d[p+8:p+8+nl].decode('utf8','replace'),ino,ft))
            p+=rl
        return out
    def lookup(s,path):
        i=2
        for c in [x for x in path.split('/') if x]:
            for n,ino,ft in s.entries(i):
                if n==c:
                    t=s.inode(ino)
                    if stat.S_ISLNK(s.mode(t)):
                        l=s.data(t).decode()
                        if l.startswith('/'): i=s.lookup(l)
                        else: i=ino
                    else: i=ino
                    break
            else: raise FileNotFoundError(path)
        return i
if __name__=='__main__':
    e=E4(sys.argv[1]); c=sys.argv[2]
    if c=='ls':
        for n,i,ft in sorted(e.entries(e.lookup(sys.argv[3]))):
            t=e.inode(i); print('%o %10d %s%s'%(e.mode(t),e.size(t),n,(' -> '+e.data(t).decode('latin1')) if stat.S_ISLNK(e.mode(t)) else ''))
    elif c=='cat':
        sys.stdout.buffer.write(e.data(e.inode(e.lookup(sys.argv[3]))))
    elif c=='find':
        def w(i,p,sub):
            for n,ino,ft in e.entries(i):
                if n in('.','..'): continue
                t=e.inode(ino); pp=p+'/'+n
                if sub in pp: print(e.size(t),pp)
                if stat.S_ISDIR(e.mode(t)): w(ino,pp,sub)
        w(2,'',sys.argv[3])

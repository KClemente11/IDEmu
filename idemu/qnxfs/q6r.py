import struct,sys
class Q6:
    def __init__(s,path,base=0):
        s.d=open(path,'rb').read(); s.base=base
        s.sb_off=base+0x2000; s.parse(s.sb_off)
    def parse(s,off):
        b=s.d[off:off+512]
        s.bs=struct.unpack('<I',b[48:52])[0]
        s.nb=struct.unpack('<I',b[60:64])[0]
        s.roots={}
        o=72
        for nm in ['Inode','Bitmap','Longfile','Unknown']:
            size=struct.unpack('<Q',b[o:o+8])[0]; ptr=struct.unpack('<16I',b[o+8:o+72]); s.roots[nm]=(size,ptr,b[o+72],b[o+73]); o+=80
    def blk(s,n): return s.d[s.base+0x3000+n*s.bs:s.base+0x3000+(n+1)*s.bs]
    def walk(s,size,ptr,lv):
        out=[];need=(size+s.bs-1)//s.bs
        def rec(p,l):
            if len(out)>=need: return
            if p==0xffffffff: out.extend([None]); return
            if l==0: out.append(p); return
            for q in struct.unpack('<%dI'%(s.bs//4),s.blk(p)):
                if len(out)>=need: break
                rec(q,l-1)
        for p in ptr:
            if len(out)>=need: break
            rec(p,lv)
        return out
    def fdata(s,size,ptr,lv):
        return b''.join(s.blk(x) if x is not None else b'\0'*s.bs for x in s.walk(size,ptr,lv))[:size]
    def inode(s,n):
        if not hasattr(s,'itab'):
            r=s.roots['Inode']; s.itab=s.walk(*r[:3])
        o=(n-1)*128; bl=s.itab[o//s.bs]; b=s.blk(bl)[o%s.bs:o%s.bs+128]
        sz,uid,gid,ft,mt,at,ct,mode,ext=struct.unpack('<QIIIIIIHH',b[:36]); ptr=struct.unpack('<16I',b[36:100]); lv,st=b[100],b[101]
        return dict(n=n,size=sz,uid=uid,gid=gid,ft=ft,mt=mt,at=at,ct=ct,mode=oct(mode),ext=ext,ptr=[hex(p) for p in ptr if p!=0xffffffff],_ptr=ptr,lv=lv,st=st,u2=b[102:104].hex(),rest=b[104:128].hex())
    def ls(s,n):
        i=s.inode(n); d=s.fdata(i['size'],i['_ptr'],i['lv']); out=[]
        for k in range(0,len(d),32):
            e=d[k:k+32]; ino=struct.unpack('<I',e[:4])[0]; ln=e[4]
            if ino==0: continue
            if ln<=27: out.append((ino,e[5:5+ln],None))
            else: out.append((ino,'LONG',e[5:32].hex()))
        return out
if __name__=='__main__':
    q=Q6(sys.argv[1]); print(q.roots['Inode'][0],q.bs,q.nb)
    print('itab',len(q.walk(*q.roots['Inode'][:3])), q.walk(*q.roots['Inode'][:3])[:12])
    print('bm',q.walk(*q.roots['Bitmap'][:3])[:10],len(q.walk(*q.roots['Bitmap'][:3])))
    for n in (1,2,3,4):
        print(n,{k:v for k,v in q.inode(n).items() if k!='_ptr'})
    print(q.ls(1)); print(q.ls(2))
    bm=q.fdata(*q.roots['Bitmap'][:3]); print(bm[:32].hex())
    # runs of used blocks
    used=[];i=0
    bits=[(bm[b>>3]>>(b&7))&1 for b in range(q.nb)]
    start=None
    for b in range(q.nb+1):
        v=bits[b] if b<q.nb else 0
        if v and start is None: start=b
        if not v and start is not None: used.append((hex(start),b-start)); start=None
    print('used runs',used[:40],len(used))

#!/usr/bin/env python3
"""Minimal QNX4 reader: lists and extracts a disk image (MBR with type-77 partition)."""
import struct,os,sys,stat as st
BS=512
class R:
    def __init__(s,path):
        s.f=open(path,'rb'); m=s.f.read(512); s.ps=None
        for i in range(4):
            e=m[446+16*i:462+16*i]
            if e[4] in (77,78,79): s.ps=struct.unpack('<I',e[8:12])[0]; s.ptype=e[4]
        assert s.ps is not None
        s.root=s.ent(s.blk(1)[:64])
    def blk(s,b,n=1):      # 0-based partition block
        s.f.seek((s.ps+b)*BS); return s.f.read(BS*n)
    def ent(s,b):
        st=b[63]
        if st&0x08 and not st&0x01: # link entry
            nm=b[:48].split(b'\0')[0]; ib,ix=struct.unpack('<IB',b[48:53]); return {'name':nm,'link':(ib,ix),'status':st}
        nm=b[:16].split(b'\0')[0]
        size,xb,xs,xblk,ft,mt,at,ct,nx,mode,uid,gid,nl=struct.unpack('<IIIIIIIIHHHHH',b[16:16+4*8+2*5])
        return {'name':nm,'size':size,'x0':(xb,xs),'xblk':xblk,'nx':nx,'mode':mode,'uid':uid,'gid':gid,'nlink':nl,'status':st,'mtime':mt}
    def extents(s,e):
        out=[e['x0']] if e['nx'] else []
        left=e['nx']-1; xb=e['xblk']
        while left>0 and xb:
            b=s.blk(xb-1); nxt=struct.unpack('<I',b[0:4])[0]; n=b[12]  # xblk: next,prev,num...
            # layout: xblk_next(4) xblk_prev(4) num_xtnts(1) spare(3) num_blocks(4) xtnts[60] ...
            n=b[8]
            for i in range(n):
                out.append(struct.unpack('<II',b[16+8*i:24+8*i]))
            left-=n; xb=nxt
        return out
    def read(s,e):
        o=bytearray(); 
        for xb,xn in s.extents(e):
            o+=s.blk(xb-1,xn)
        return bytes(o[:e['size']])
    def ls(s,e):
        d=s.read(e)
        out=[]
        for i in range(0,len(d),64):
            b=d[i:i+64]
            if len(b)<64 or b[63]&0x0b==0 or not b[0]: continue
            x=s.ent(b)
            if 'link' in x:
                ib,ix=x['link']; t=s.ent(s.blk(ib-1)[64*ix:64*ix+64]); t['name']=x['name']; x=t
            out.append(x)
        return out
    def walk(s,e=None,p=''):
        e=e or s.root
        for x in s.ls(e):
            n=x['name'].decode(errors='replace')
            if n in('.','..'): continue
            yield p+'/'+n,x
            if st.S_ISDIR(x['mode']): yield from s.walk(x,p+'/'+n)
if __name__=='__main__':
    r=R(sys.argv[1]); print('part',r.ps,r.ptype,r.root)
    if sys.argv[2]=='ls':
        tot=0;n=0;junk=0
        for p,x in r.walk():
            n+=1
            if st.S_ISREG(x['mode']): tot+=x['size']
            if os.path.basename(p).startswith('._'): junk+=1
            if len(sys.argv)>3 and sys.argv[3] in p: print(p,oct(x['mode']),x.get('size'),x['nx'])
        print('files',n,'bytes',tot,'junk',junk)
    elif sys.argv[2]=='x':
        dst=sys.argv[3]; 
        for p,x in r.walk():
            if os.path.basename(p).startswith('._'): continue
            q=dst+p
            try:
              if st.S_ISDIR(x['mode']): os.makedirs(q,exist_ok=True); continue
              if st.S_ISLNK(x['mode']): 
                 t=r.read(x).split(b'\0')[0].decode(); os.path.lexists(q) or os.symlink(t,q); continue
              if st.S_ISREG(x['mode']):
                 os.makedirs(os.path.dirname(q),exist_ok=True)
                 open(q,'wb').write(r.read(x)); os.chmod(q,x['mode']&0o777|0o200)
              else: print('skip',p,oct(x['mode']))
            except Exception as ex: print('ERR',p,ex)

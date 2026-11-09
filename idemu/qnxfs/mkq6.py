#!/usr/bin/env python3
"""Write a QNX6 image using a real mkqnx6fs image as template (keeps boot, sb layout, inode table + bitmap blocks)."""
import struct,os,sys,stat as st,time
def crc(data):
    c=0
    tab=crc.tab
    for x in data: c=((c<<8)&0xffffffff)^tab[((c>>24)^x)&0xff]
    return c
crc.tab=[]
for i in range(256):
    c=i<<24
    for _ in range(8): c=((c<<1)^0x04C11DB7)&0xffffffff if c&0x80000000 else (c<<1)&0xffffffff
    crc.tab.append(c)
MT=int(time.mktime((2017,1,1,0,0,0,0,0,0)))
BS=1024; PP=BS//4
class N:
    __slots__=('name','mode','src','size','kids','ino','blocks','pcnt')
    def __init__(s,name,mode,src=None,size=0):
        s.name=name;s.mode=mode;s.src=src;s.size=size;s.kids={} if st.S_ISDIR(mode) else None;s.ino=0
def lchk(name):
    c=0
    for b in name:
        c=((c>>1)+b)&0xffffffff
        # matches: crc = ((crc >> 1) + *(name++)) ^ ((crc & 1) ? 0x80000000 : 0)  (old crc's low bit)
    return c
def lfile_checksum(name):
    crc_=0
    for b in name:
        sb=b-256 if b>127 else b
        crc_=(((crc_>>1)+sb)&0xffffffff) ^ (0x80000000 if crc_&1 else 0)
    return crc_
def build(tree,template,out):
    tpl=open(template,'rb').read()
    sb=bytearray(tpl[0x2000:0x2200]); nb=struct.unpack('<I',sb[60:64])[0]; ni=struct.unpack('<I',sb[52:56])[0]
    assert struct.unpack('<I',sb[48:52])[0]==BS
    base=0x3000
    f=open(out,'wb'); f.write(tpl)
    wb=lambda n,data:(f.seek(base+n*BS),f.write(data))
    # read inode table block list from the template
    def rd(n): return tpl[base+n*BS:base+(n+1)*BS]
    size=struct.unpack('<Q',sb[72:80])[0]; p0=struct.unpack('<I',sb[80:84])[0]
    itab=[]
    for l1 in struct.unpack('<256I',rd(p0)):
        if l1==0xffffffff: continue
        itab.extend(x for x in struct.unpack('<256I',rd(l1)) if x!=0xffffffff)
    bmsize=struct.unpack('<Q',sb[152:160])[0]; bmp0=struct.unpack('<I',sb[160:164])[0]
    bml=[x for x in struct.unpack('<256I',rd(bmp0)) if x!=0xffffffff]
    # used blocks in the template: run from 0
    next_blk=nb-struct.unpack('<I',sb[64:68])[0]
    print('template used blocks',next_blk)
    def alloc(n):
        nonlocal next_blk
        a=next_blk; next_blk+=n; return a
    def ptrs(nblocks,first):
        """return (ptr16,level) for contiguous data; allocates and writes indirect blocks"""
        if nblocks<=16:
            p=[first+i for i in range(nblocks)]+[0xffffffff]*(16-nblocks); return p,0
        if nblocks<=16*PP:
            nl1=(nblocks+PP-1)//PP; t=alloc(nl1); p=[]
            for i in range(nl1):
                ch=[first+i*PP+j for j in range(min(PP,nblocks-i*PP))]; wb(t+i,struct.pack('<%dI'%PP,*(ch+[0xffffffff]*(PP-len(ch))))); p.append(t+i)
            return p+[0xffffffff]*(16-len(p)),1
        nl1=(nblocks+PP-1)//PP; t=alloc(nl1)
        for i in range(nl1):
            ch=[first+i*PP+j for j in range(min(PP,nblocks-i*PP))]; wb(t+i,struct.pack('<%dI'%PP,*(ch+[0xffffffff]*(PP-len(ch)))))
        nl2=(nl1+PP-1)//PP; t2=alloc(nl2); p=[]
        for i in range(nl2):
            ch=[t+i*PP+j for j in range(min(PP,nl1-i*PP))]; wb(t2+i,struct.pack('<%dI'%PP,*(ch+[0xffffffff]*(PP-len(ch))))); p.append(t2+i)
        return p+[0xffffffff]*(16-len(p)),2
    inotab={}
    next_ino=3
    longs=[]
    def inoent(sz,mode,ext,ptr,lv,status):
        return struct.pack('<QIIIIIIHH16IBB',sz,0,0,MT,MT,MT,MT,mode,ext,*ptr,lv,status).ljust(128,b'\0')
    dirs=[]; files=[]
    def assign(n):
        nonlocal next_ino
        for k in n.kids.values():
            k.ino=next_ino; next_ino+=1
            if st.S_ISDIR(k.mode): assign(k)
            else: files.append(k)
        dirs.append(n)
    tree.ino=1
    assign(tree)
    if next_ino>ni: raise SystemExit('too many inodes')
    # parents
    parent={1:1}
    def setp(n):
        for k in n.kids.values():
            if st.S_ISDIR(k.mode): parent[k.ino]=n.ino; setp(k)
    setp(tree)
    for d in dirs:
        ents=bytearray()
        def add(ino,name):
            if len(name)<=27:
                ents.extend(struct.pack('<IB',ino,len(name))+name.ljust(27,b'\0'))
            else:
                idx=len(longs); longs.append(name)
                ents.extend(struct.pack('<IB3xII',ino,0xff,idx,lfile_checksum(name)).ljust(32,b'\0'))
        add(d.ino,b'.'); add(parent[d.ino],b'..')
        if d is tree: add(2,b'.boot')
        for k in d.kids.values(): add(k.ino,k.name)
        nb_=max(1,(len(ents)+BS-1)//BS)
        first=alloc(nb_); wb(first,bytes(ents).ljust(nb_*BS,b'\0'))
        p,lv=ptrs(nb_,first)
        ext=2+sum(1 for k in d.kids.values() if st.S_ISDIR(k.mode))+(1 if d is tree else 0)
        inotab[d.ino]=inoent(nb_*BS,d.mode,ext,p,lv,1)
    for k in files:
        n=(k.size+BS-1)//BS
        if k.size==0:
            inotab[k.ino]=inoent(0,k.mode,1,[0xffffffff]*16,0,3); continue
        first=alloc(n); f.seek(base+first*BS)
        if isinstance(k.src,str):
            with open(k.src,'rb') as g:
                while True:
                    c=g.read(1<<20)
                    if not c: break
                    f.write(c)
        else: f.write(k.src)
        p,lv=ptrs(n,first)
        inotab[k.ino]=inoent(k.size,k.mode,1,p,lv,3)
    # long names
    if longs:
        first=alloc(len(longs))
        for i,nm in enumerate(longs):
            wb(first+i,struct.pack('<H',len(nm))+nm.ljust(BS-2,b'\0'))
        p,lv=ptrs(len(longs),first)
        sb[232:240]=struct.pack('<Q',len(longs)*BS); sb[240:304]=struct.pack('<16I',*p); sb[304]=lv
    if next_blk>nb: raise SystemExit('disk too small: %d>%d'%(next_blk,nb))
    # inode table: keep 1,2 of the template
    tblocks={}
    for ino,e in inotab.items():
        if ino==2: continue
        o=(ino-1)*128; tb=itab[o//BS]
        if tb not in tblocks: tblocks[tb]=bytearray(rd(tb))
        tblocks[tb][o%BS:o%BS+128]=e
    for tb,b in tblocks.items(): wb(tb,b)
    # bitmap: 1=used
    bm=bytearray(bmsize); full=next_blk//8; bm[:full]=b'\xff'*full
    if next_blk%8: bm[full]=(1<<(next_blk%8))-1
    bm=bm.ljust(len(bml)*BS,b'\0')
    for i,b in enumerate(bml): wb(b,bm[i*BS:(i+1)*BS])
    # superblock 1 (active: serial 2)
    sb[56:60]=struct.pack('<I',ni-(next_ino-1)); sb[64:68]=struct.pack('<I',nb-next_blk); sb[8:16]=struct.pack('<Q',2)
    sb[4:8]=struct.pack('<I',crc(bytes(sb[8:512])))
    f.seek(0x2000); f.write(sb); f.close()
    print('qnx6: %d files %d dirs %d longnames, used %.1f MB of %.1f MB'%(len(files),len(dirs),len(longs),next_blk*BS/1e6,nb*BS/1e6))
def from_host(n,path,skip=lambda p:False):
    for x in sorted(os.listdir(path)):
        if x.startswith('._') or x=='.DS_Store': continue
        p=os.path.join(path,x)
        if skip(p): continue
        b=x.encode()
        if os.path.isdir(p):
            k=n.kids.get(b) or N(b,0o40775); n.kids[b]=k; from_host(k,p,skip)
        elif os.path.isfile(p):
            n.kids[b]=N(b,0o100755 if os.access(p,os.X_OK) else 0o100644,p,os.path.getsize(p))

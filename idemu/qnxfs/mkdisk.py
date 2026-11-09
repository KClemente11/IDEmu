#!/usr/bin/env python3
"""Build a QNX4 disk image (MBR + type 77 partition at LBA 1) from a manifest of entries.
   Files are allocated contiguously (1 extent), so no xtnt blocks are needed."""
import struct,time,stat as st,os
BS=512
MT=int(time.mktime((2017,1,1,0,0,0,0,0,0)))
class Node:
    __slots__=('name','mode','src','size','kids','parent','blk','nblk','loc','tgt','mtime')
    def __init__(s,name,mode,src=None,size=0,mtime=MT):
        s.name=name;s.mode=mode;s.src=src;s.size=size;s.kids={} if st.S_ISDIR(mode) else None;s.parent=None;s.blk=0;s.nblk=0;s.loc=None;s.mtime=mtime
class Tree:
    def __init__(s):
        s.root=Node(b'/',0o40775); s.n=0
    def mkdir(s,path,mode=0o40777):
        c=s.root
        for seg in path.strip('/').split('/'):
            if not seg: continue
            b=seg.encode()
            if b not in c.kids or not st.S_ISDIR(c.kids[b].mode):
                k=Node(b,mode); k.parent=c; c.kids[b]=k
            c=c.kids[b]
        return c
    def add(s,path,mode,src,size,mtime=MT):
        d,_,n=path.rstrip('/').rpartition('/')
        c=s.mkdir(d) if d else s.root
        b=n.encode()
        if len(b)>48: raise ValueError('name too long: '+path)
        if st.S_ISDIR(mode):
            s.mkdir(path,mode); return
        k=Node(b,mode,src,size,mtime); k.parent=c; c.kids[b]=k
    def rm(s,path):
        d,_,n=path.rstrip('/').rpartition('/')
        c=s.root
        for seg in d.strip('/').split('/'):
            if seg: c=c.kids.get(seg.encode()); 
            if c is None: return
        c.kids.pop(n.encode(),None)
    def get(s,path):
        c=s.root
        for seg in path.strip('/').split('/'):
            if not seg: continue
            c=(c.kids or {}).get(seg.encode())
            if c is None: return None
        return c
def inode(name,size,xb,xn,mode,nlink,status,mtime=MT):
    return struct.pack('<16sIIIIIIIIHHHHH4sBB',name,size,xb,xn,0,mtime,mtime,mtime,mtime,1 if xn else 0,mode,0,0,nlink,b'\0'*4,0,status)
def link(name,blk,ndx):
    b=name.ljust(48,b'\0')+struct.pack('<IB',blk,ndx)+b'\0'*10+bytes([8]); return b
def write(tree,out,total_sectors,reader=None):
    parts=total_sectors-1
    bmbytes=(parts+7)//8; bmblk=(bmbytes+BS-1)//BS
    # walk tree
    dirs=[];files=[]; longs=0
    def walk(n):
        nonlocal longs
        for k in n.kids.values():
            if len(k.name)>16: longs+=1
            if st.S_ISDIR(k.mode): walk(k)
            else: files.append(k)
        dirs.append(n)
    walk(tree.root)
    next_blk=3  # 1-based; 1 boot, 2 super
    bm_at=next_blk; next_blk+=bmblk
    def alloc(nb):
        nonlocal next_blk
        a=next_blk; next_blk+=nb; return a
    # inode file: 8 entries/block, first entry reserved
    inoblk=((longs+1+7)//8+16+15)//16*16
    tree.root.size=max(4096,((len(tree.root.kids)+8)*64+4095)//4096*4096); tree.root.nblk=tree.root.size//BS; tree.root.blk=alloc(tree.root.nblk)
    ino_at=alloc(inoblk)
    for d in dirs:
        if d is tree.root: continue
        ents=len(d.kids)+2+(6 if d is tree.root else 0)
        d.size=max(4096,((ents*64+4095)//4096)*4096); d.nblk=d.size//BS; d.blk=alloc(d.nblk)
    for f in files:
        f.nblk=(f.size+BS-1)//BS; f.blk=alloc(f.nblk) if f.size else 0
    if next_blk>parts: raise SystemExit('disk full: need %d blocks, have %d'%(next_blk,parts))
    print('used %.1f MB of %.1f MB; %d files %d dirs %d longnames'%(next_blk*BS/1e6,parts*BS/1e6,len(files),len(dirs),longs))
    # locations: each entry gets (block,index) where its inode sits
    inotab=bytearray(inoblk*BS)
    inotab[0:64]=struct.pack('<16sI',b'IamTHE.inodeFILE',parts+1)+b'\0'*44
    inotab[64*7:64*7]=b''
    ino_next=1
    tree.root.loc=(2,0)
    dirimg={}
    for d in dirs[::-1]: pass
    def fill(d):
        nonlocal ino_next
        buf=bytearray(d.size); i=0
        # "." and ".."
        p=d.parent or d
        buf[0:64]=link(b'.\0I\x03QNX\0\x08',d.loc[0],d.loc[1]); buf[64:128]=link(b'..',p.loc[0],p.loc[1]); i=2
        if d is tree.root:
            bm=inode(b'.bitmap',bmbytes if False else bmblk*BS,bm_at,bmblk,0o100444,1,1)
            buf[128:192]=bm; buf[192:256]=link(b'.inodes',2,1); buf[256:320]=link(b'.boot',2,2); buf[320:384]=link(b'.altboot',2,3); i=6
        for k in d.kids.values():
            xb=k.blk; xn=k.nblk
            if st.S_ISDIR(k.mode):
                size=k.size; nl=2+sum(1 for c in k.kids.values() if st.S_ISDIR(c.mode))
            else:
                size=k.size; nl=1
            if len(k.name)<=16:
                buf[i*64:i*64+64]=inode(k.name,size,xb,xn,k.mode,nl,1,k.mtime)
                k.loc=(d.blk+i//8,i%8)
            else:
                j=ino_next; ino_next+=1
                inotab[j*64:j*64+64]=inode(b'',size,xb,xn,k.mode,nl,0x11,k.mtime)
                k.loc=(ino_at+j//8,j%8)
                buf[i*64:i*64+64]=link(k.name,k.loc[0],k.loc[1])
            i+=1
        dirimg[id(d)]=buf
        for k in d.kids.values():
            if st.S_ISDIR(k.mode): fill(k)
    fill(tree.root)
    with open(out,'wb') as f:
        f.truncate(total_sectors*BS)
        # MBR
        m=bytearray(512); m[446+4]=77; m[446:447]=b'\x80'
        # chs dummy like a real table; LBA 1
        m[446+8:446+12]=struct.pack('<I',1); m[446+12:446+16]=struct.pack('<I',parts)
        # keep original partition slot (4th) as dinit/fdisk wrote
        tbl=bytes(m[446:462]); m[446:462]=bytes(16); m[494:510]=tbl; m[510]=0x55; m[511]=0xaa
        f.seek(0); f.write(m)
        off=lambda b:(b-1+1)*BS   # 1-based partition block -> absolute byte (partition starts at LBA1)
        # superblock
        rootn=tree.root
        sb=inode(b'/',rootn.size,rootn.blk,rootn.nblk,0o40775,2+sum(1 for c in rootn.kids.values() if st.S_ISDIR(c.mode)),1)
        sb+=inode(b'',inoblk*BS,ino_at,inoblk,0o100444,1,0x11)
        sb+=inode(b'',0,0,0,0o100600,1,0x11)+inode(b'',0,0,0,0o100600,1,0x11)
        f.seek(off(2)); f.write(sb.ljust(BS,b'\0'))
        # bitmap: bit0 of byte0 = block 1
        bm=bytearray(b'\xff'*(bmblk*BS))
        used=next_blk-1
        bm[used//8:bmbytes]=bytes(bmbytes-used//8)
        if used%8: bm[used//8]=(1<<(used%8))-1
        # bits beyond the end of the partition stay 1
        if parts%8: bm[bmbytes-1]|=(0xff<<(parts%8))&0xff
        f.seek(off(bm_at)); f.write(bm)
        f.seek(off(ino_at)); f.write(inotab)
        for d in dirs:
            f.seek(off(d.blk)); f.write(dirimg[id(d)])
        for k in files:
            if not k.size: continue
            f.seek(off(k.blk)); s=k.src
            if isinstance(s,(bytes,bytearray)): f.write(s)
            elif isinstance(s,str):
                with open(s,'rb') as g:
                    while True:
                        c=g.read(1<<20)
                        if not c: break
                        f.write(c)
            else: f.write(s())  # callable

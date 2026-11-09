import struct,sys
def load(path):
    d=open(path,'rb').read()
    shoff=struct.unpack_from('<Q',d,0x28)[0]; shentsize,shnum,shstrndx=struct.unpack_from('<HHH',d,0x3a)
    secs=[]
    for i in range(shnum):
        n,t,f,a,o,sz,l,inf,al,es=struct.unpack_from('<IIQQQQIIQQ',d,shoff+i*shentsize); secs.append((n,t,f,a,o,sz,l,inf,es))
    # relocations
    rel={}
    for n,t,f,a,o,sz,l,inf,es in secs:
        if t==4: # RELA
            for j in range(sz//24):
                off,info,add=struct.unpack_from('<QQq',d,o+j*24)
                if info&0xffffffff in (8,): rel[off]=add
    # vaddr->fileoff via PT_LOAD
    phoff=struct.unpack_from('<Q',d,0x20)[0]; phn=struct.unpack_from('<H',d,0x38)[0]
    loads=[]
    for i in range(phn):
        t,fl,o,va,pa,fs,ms,al=struct.unpack_from('<IIQQQQQQ',d,phoff+i*56)
        if t==1: loads.append((va,o,fs))
    def f2o(va):
        for v,o,fs in loads:
            if v<=va<v+fs: return o+va-v
    def ptr(va):
        return rel.get(va)
    def cstr(va):
        o=f2o(va); e=d.index(b'\0',o); return d[o:e].decode()
    # dynsym
    syms={}
    for n,t,f,a,o,sz,l,inf,es in secs:
        if t==11:
            so=secs[l][4]
            for j in range(sz//24):
                nm,info,oth,shn,val,size=struct.unpack_from('<IBBHQQ',d,o+j*24)
                e=d.index(b'\0',so+nm); syms[d[so+nm:e].decode()]=val
    out={}
    for name,va in syms.items():
        if not name.endswith('_interface'): continue
        nmv=ptr(va); 
        if nmv is None: continue
        iname=cstr(nmv); ver,mc=struct.unpack_from('<ii',d,f2o(va+8)); mp=ptr(va+16); ec=struct.unpack_from('<i',d,f2o(va+24))[0]; ep=ptr(va+32)
        def msgs(p,c):
            r=[]
            for k in range(c):
                r.append((cstr(ptr(p+k*24)),cstr(ptr(p+k*24+8))))
            return r
        out[iname]=(ver,msgs(mp,mc) if mc else [],msgs(ep,ec) if ec else [])
    return out
for p in sys.argv[1:]:
    for k,(v,m,e) in load(p).items():
        print(k,'v',v); print('  req',list(enumerate(m))); print('  evt',list(enumerate(e)))

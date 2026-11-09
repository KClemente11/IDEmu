def lzo1x_decompress(src, pos=0, maxout=1<<26):
    out=bytearray(); ip=pos
    def cp(dist,n):
        if dist>len(out) or dist<=0: raise ValueError('bad dist')
        s=len(out)-dist
        if dist>=n: out.extend(out[s:s+n])
        else:
            for _ in range(n): out.append(out[len(out)-dist])
    try:
        state='loop'
        if src[ip]>17:
            t=src[ip]-17; ip+=1
            if t<4: state='match_next'
            else:
                out+=src[ip:ip+t]; ip+=t; state='first_lit'
        else: t=0
        while True:
            if state=='loop':
                t=src[ip]; ip+=1
                if t>=16: state='match'; continue
                if t==0:
                    while src[ip]==0: t+=255; ip+=1
                    t+=15+src[ip]; ip+=1
                t+=3; out+=src[ip:ip+t]; ip+=t; state='first_lit'
            elif state=='first_lit':
                t=src[ip]; ip+=1
                if t>=16: state='match'; continue
                dist=0x801+(t>>2)+(src[ip]<<2); ip+=1
                cp(dist,3); state='match_done'
            elif state=='match':
                if t>=64:
                    dist=1+((t>>2)&7)+(src[ip]<<3); ip+=1; cp(dist,(t>>5)+1)
                elif t>=32:
                    n=t&31
                    if n==0:
                        while src[ip]==0: n+=255; ip+=1
                        n+=31+src[ip]; ip+=1
                    v=src[ip]|(src[ip+1]<<8); ip+=2
                    cp(1+(v>>2),n+2)
                elif t>=16:
                    n=t&7; hi=(t&8)<<11
                    if n==0:
                        while src[ip]==0: n+=255; ip+=1
                        n+=7+src[ip]; ip+=1
                    v=src[ip]|(src[ip+1]<<8); ip+=2
                    dist=hi+(v>>2)
                    if dist==0: return bytes(out),ip
                    cp(dist+0x4000,n+2)
                else:
                    dist=1+(t>>2)+(src[ip]<<2); ip+=1; cp(dist,2)
                state='match_done'
            if state=='match_done':
                t=src[ip-2]&3
                state='loop' if t==0 else 'match_next'
            if state=='match_next':
                out+=src[ip:ip+t]; ip+=t
                t=src[ip]; ip+=1; state='match'
            if len(out)>maxout: return bytes(out),-ip
    except (IndexError,ValueError):
        return bytes(out),-ip

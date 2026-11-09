#!/usr/bin/env python3
"""Varredura de blocos MOST do HMI: registra dispositivos (POST /api/v850/devices), descobre o que o HMI assina e acha, por tentativa e erro guiada pelo
`logs/renderer.log` ("invalid message ... Read failed at byte N", "[Svc] FB.INST.FKT"), um Status neutro (zeros) aceito para cada propriedade.

Uso (emulador rodando, `python3 -m idemu gui` na porta 8765):  python3 tools/hmi_sweep.py e5/1 e5/3 c0/3 71/0
Resultado em $IDEMU_SWEEP_OUT (padrao /tmp/sweep_results.json), no formato de idemu/data/hmi_property_defaults.json ("fb:inst:fkt" -> hex).
CUIDADO: propriedades-evento (ex.: 0xE0/0x200 CNewCCMessage) aceitam payload longo e então derrubam o HMI; o script avisa se o HMI reiniciou.
"""
import sys,time,json,urllib.request,re
import os
L=os.environ.get('IDEMU_RENDERER_LOG', os.path.expanduser('~/Desktop/IDEmu/environments/f30-bmw/logs/renderer.log'))
OUT=os.environ.get('IDEMU_SWEEP_OUT', '/tmp/sweep_results.json')
def api(path,d=None):
    r=urllib.request.Request('http://localhost:8765/api/'+path,data=json.dumps(d).encode() if d is not None else None,headers={'Content-Type':'application/json'})
    return json.loads(urllib.request.urlopen(r).read())
def nl(): return sum(1 for _ in open(L,'rb'))
def runs(): 
    return sum(1 for l in open(L,'rb') if b'genericMain entered' in l)
def scan(n):
    bad={};oor=set()
    lines=open(L,'rb').read().split(b'\n')[n:]
    for i,l in enumerate(lines):
        m=re.search(rb'invalid message: FBlockID:(\w+) InstanceID:(\w+) FuncID:(\w+)\. Read failed at byte (\d+)',l)
        if m: bad[(int(m.group(1),16),int(m.group(2),16),int(m.group(3),16))]=int(m.group(4))
        m=re.search(rb'\[Svc\] ([0-9A-F]{2})\.([0-9A-F]{2})\.([0-9A-F]{3})\.',l)
        if m: oor.add((int(m.group(1),16),int(m.group(2),16),int(m.group(3),16)))
    return bad,oor
def pub(fb,inst,fkt,h): return api('v850/publish',{'fblock':fb,'inst':inst,'fkt':fkt,'data':h})['delivered']
def main(devs,maxsize=48):
    res=json.load(open(OUT)) if __import__('os').path.exists(OUT) else {}
    r0=runs()
    api('v850/devices',{'devices':devs}); time.sleep(30)
    subs=api('v850')['bridge']['subscriptions']
    want=set((d[0],d[1]) for d in devs)
    tg={}
    for k,v in subs.items():
        fb=int(k[:2],16); inst=int(k[2:],16)
        if (fb,inst) in want:
            for f in v: tg[(fb,inst,f)]=1
    print('subs',{'%02x/%d'%(a,b):len([1 for t in tg if t[:2]==(a,b)]) for (a,b) in want if any(t[:2]==(a,b) for t in tg)},flush=True)
    pend=dict(tg); good={}; oorset=set()
    for rnd in range(16):
        if not pend: break
        n=nl()
        for t,s in pend.items(): pub(t[0],t[1],t[2],'00'*s)
        time.sleep(8)
        if runs()>r0: print('HMI REINICIOU durante rodada',rnd,'pendentes',['%02x/%d:%x=%d'%(t+(s,)) for t,s in pend.items()],flush=True); break
        bad,oor=scan(n)
        for t in list(pend):
            if t in oor and t not in bad: oorset.add(t); pend.pop(t); continue
            if t in bad: 
                if pend[t]>=maxsize: oorset.add(t); pend.pop(t)
                else: pend[t]=max(pend[t]+1,bad[t]+1)
            else: good[t]=pend.pop(t)
        print('rnd',rnd,'pend',len(pend),'good',len(good),'oor',len(oorset),flush=True)
    for t,s in good.items(): res['%02x:%d:%03x'%t]='00'*s
    json.dump(res,open(OUT,'w'),indent=1)
    print('GOOD',{'%02x/%d:%x'%t:s for t,s in good.items()}); print('PENDING',{'%02x/%d:%x'%t:s for t,s in pend.items()}); print('OOR/skip',['%02x/%d:%x'%t for t in oorset]); print('runs',r0,runs())
if __name__=='__main__':
    devs=[[int(x.split('/')[0],16),int(x.split('/')[1])] for x in sys.argv[1:]]
    main(devs)

#!/usr/bin/env python3
# c.py 'comando'  -> executa no guest e imprime a saída
import sys,os,time,random,subprocess,re
cmd=sys.argv[1]; to=int(os.environ.get('T','40'))
m='__M%d'%random.randint(0,10**6)
fd=os.open('/tmp/mgu/t1/cmd.fifo',os.O_WRONLY)
os.write(fd,b'\x03\n'); time.sleep(.3)
os.write(fd,(cmd+'\necho '+m+'END\n').encode())
for _ in range(to):
    time.sleep(1)
    d=open('/tmp/mgu/t1/s2.log','rb').read().decode('latin1')
    if re.search(r'^'+m+'END',d,re.M): break
i=d.rfind('echo '+m+'END'); j=d.rfind(m+'END')
out=d[d.find('\n',d.rfind(cmd.split('\n')[0][:30]))+1:j] if True else ''
print('\n'.join(l for l in out.split('\n') if 'serial8250' not in l and 'echo '+m not in l))

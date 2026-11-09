#!/usr/bin/env python3
# Liga-se ao console (ttyS2) do QEMU por socket unix: grava a saída em s2.log e injeta linhas escritas em cmd.fifo.
import socket,os,sys,time,select,threading
sp='/tmp/idemu-con.sock'; log=open('/tmp/mgu/t1/s2.log','ab',buffering=0)
fifo='/tmp/mgu/t1/cmd.fifo'
if not os.path.exists(fifo): os.mkfifo(fifo)
for _ in range(600):
    try: s=socket.socket(socket.AF_UNIX); s.connect(sp); break
    except Exception: time.sleep(.1)
def pump():
    while True:
        try:
            d=os.read(fd,4096)
            if d: s.sendall(d)
        except Exception: time.sleep(.2)
fd=os.open(fifo,os.O_RDWR)
threading.Thread(target=pump,daemon=True).start()
while True:
    d=s.recv(65536)
    if not d: break
    log.write(d)

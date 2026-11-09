#!/usr/bin/env python3
# inp.py "d 100 200" "u" ...: manda comandos para o input.sock do mguhost; "s0.2" espera 0,2 s
import os,socket,sys,time
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..','mgu22')
s=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
for a in sys.argv[1:]:
    if a[0]=='s': time.sleep(float(a[1:])); continue
    s.sendto(a.encode(),open(OUT+'/run.path').read()+'/input.sock')

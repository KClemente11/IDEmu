#!/usr/bin/env python3
"""Console do CIC: console.py [-w seg] 'linha' ... envia as linhas ao /dev/ser1 e imprime a saída."""
import os, socket, sys, time
D = os.environ.get('CIC_DIR', '/tmp/cic')
def main():
    a = sys.argv[1:]; wait = 1.5
    if a[:1] == ['-w']: wait = float(a[1]); a = a[2:]
    s = socket.socket(socket.AF_UNIX); s.connect(D + '/ser1.sock'); s.settimeout(0.3)
    def rd(t):
        end = time.time() + t; out = b''
        while time.time() < end:
            try:
                x = s.recv(65536)
                if not x: break
                out += x; end = time.time() + min(t, 0.6)
            except socket.timeout: pass
        return out
    print(rd(wait).decode('latin1'), end='')
    for l in a:
        s.sendall(l.encode() + b'\r'); print(rd(wait).decode('latin1'), end='')
main()

#!/usr/bin/env python3
"""Cliente mínimo do protocolo GDB remoto (RSP) para o QEMU sh4: breakpoints, passo a passo, memória.
Uso como módulo:  g = Gdb(1234); g.bp(addr); g.cont(); g.regs(); g.mem(addr, n); g.step()"""
import socket, struct, time

REGN = ['r%d' % i for i in range(16)] + ['pc', 'pr', 'gbr', 'vbr', 'mach', 'macl', 'sr', 'fpul', 'fpscr']


class Gdb:
    def __init__(self, port=1234, host='127.0.0.1', retries=100):
        for _ in range(retries):
            try:
                self.s = socket.create_connection((host, port), timeout=60)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('sem gdbstub')
        self.buf = b''
        self.noack = False
        self.cmd('QStartNoAckMode')
        self.noack = True

    def _send(self, data):
        cs = sum(data.encode()) & 255
        self.s.sendall(('$%s#%02x' % (data, cs)).encode())

    def _recv(self):
        while True:
            i = self.buf.find(b'$')
            j = self.buf.find(b'#', i + 1) if i >= 0 else -1
            if i >= 0 and j >= 0 and len(self.buf) >= j + 3:
                pkt = self.buf[i + 1:j].decode('latin1')
                self.buf = self.buf[j + 3:]
                if not self.noack:
                    self.s.sendall(b'+')
                return pkt
            d = self.s.recv(65536)
            if not d:
                raise EOFError('gdbstub fechou')
            self.buf += d

    def cmd(self, c):
        self._send(c)
        if not self.noack:
            while True:
                if self.buf[:1] in (b'+', b'-'):
                    self.buf = self.buf[1:]; break
                self.buf += self.s.recv(4096)
        return self._recv()

    def regs(self):
        r = self.cmd('g')
        v = [struct.unpack('<I', bytes.fromhex(r[i * 8:i * 8 + 8]))[0] for i in range(len(REGN))]
        return dict(zip(REGN, v))

    def mem(self, addr, n):
        out = b''
        while n > 0:
            k = min(n, 1024)
            r = self.cmd('m%x,%x' % (addr, k))
            if r.startswith('E'):
                raise IOError('mem %x: %s' % (addr, r))
            out += bytes.fromhex(r); addr += k; n -= k
        return out

    def u32(self, addr):
        return struct.unpack('<I', self.mem(addr, 4))[0]

    def bp(self, addr):
        return self.cmd('Z0,%x,2' % addr)

    def unbp(self, addr):
        return self.cmd('z0,%x,2' % addr)

    def cont(self):
        self._send('c')
        return self._recv()

    def step(self):
        return self.cmd('s')


def _setreg(self, name, val):
    """grava um registrador (pacote P)."""
    return self.cmd('P%x=%s' % (REGN.index(name), struct.pack('<I', val & 0xffffffff).hex()))


def _wmem(self, addr, data):
    """grava memória (pacote M)."""
    for i in range(0, len(data), 512):
        r = self.cmd('M%x,%x:%s' % (addr + i, len(data[i:i + 512]), data[i:i + 512].hex()))
        if r != 'OK':
            raise IOError('wmem %x: %s' % (addr + i, r))


Gdb.setreg = _setreg
Gdb.wmem = _wmem


def _detach(self):
    """remove os breakpoints dados e solta o alvo (pacote D), deixando a VM rodando."""
    try:
        self.cmd('D')
    except Exception:
        pass
    try:
        self.s.close()
    except Exception:
        pass
Gdb.detach = _detach

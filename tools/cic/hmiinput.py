#!/usr/bin/env python3
"""Entrada do controlador iDrive no HMI do CIC (patch do HmiMain no IFS2 + hypercall do QEMU).

O HMI recebe o controlador (rotor, botões) como mensagens MOST do FBlock CentralControlSystem (0xE5), que chegam do Root pelo canal MTP.
No emulador o MOST não existe (dev-mlb sem hardware); então os telegramas MTP são injetados no próprio HmiMain:

* a thread receptora do MTP do HmiMain roda um laço (CSvcMTPHandler, 0x08d086e8) que chama recv(this, buf, 0x10000) (0x08d08534) e
  processa o telegrama lido; a chamada (bsrf em 0x08d08766, deslocamento no literal de 0x08d0887c) passa a ir para um stub;
* o stub pergunta ao QEMU (trapa #0xC3, r0 = 0x1DE30000|op) quem é: na 1ª chamada cria uma 2ª thread que roda o mesmo laço e segue para o
  recv original; na 2ª thread, em vez de ler do Root, o stub espera telegramas do QEMU (nanosleep de 20 ms entre consultas) e devolve-os
  em buf como se tivessem vindo do Root. Assim o telegrama injetado segue exatamente o caminho de um telegrama real.
* o QEMU (src/cic/cic.c) recebe os telegramas pelo socket CIC_INPUT ("t <hex>") e os entrega pelo hypercall:
  op 0 = classificar (r4 = this, r5 = buf; devolve 2 = criar a thread, 0 = thread real, 1 = thread de injeção), op 1 = próximo telegrama
  (devolve o tamanho, 0 = nenhum), op 2 = palavra de 32 bits do telegrama atual no deslocamento r4.
* no envio (bsrf em 0x08d084fa para sendMsg), os telegramas MOST do HMI para o FBlock 0xE5 são copiados para o QEMU (op 3 = início com
  r4 = tamanho, op 4 = byte r5 no deslocamento r4, op 5 = fim), que os repassa ao IDEmu (CIC_OUTPUT): é assim que o controlador virtual
  responde, por exemplo, ao RotaryEncoderConfig.Set do HMI.
"""
import struct

ANCHOR_VA = 0x08d086e8                       # laço da thread receptora (CSvcMTPHandler)
ANCHOR = bytes.fromhex('862f962fa62fb62fc62fd62fe62f224f56c756dc0c3cfc7f436b55d455d10301')
CAVE_VA = 0x08d871a4                         # CA4ADataProxyDispatch::onA4AOpenSession (A4A não existe no emulador): 928 bytes
CAVE = bytes.fromhex('862f962fa62fb62fc62fd62fe62fcbff224f5ec75ddc0c3cb291183ff36e436d')
CAVE_SIZE = 0x3a0
LIT_VA = 0x08d0887c                          # literal do bsrf da chamada ao recv (alvo = 0x08d0876a + literal)
LIT_BASE = 0x08d0876a
RECV_VA = 0x08d08534
TXLIT_VA = 0x08d08530                        # literal do bsrf da chamada a CGMTPQNXChannelClient::sendMsg (alvo = 0x08d084fe + literal)
TXLIT_BASE = 0x08d084fe
SEND_VA = 0x08d0c1e4
PLT = {'pthread_create': 0x081f11f8, 'pthread_attr_init': 0x081f1268, 'pthread_attr_setstacksize': 0x081f2634,
       'nanosleep': 0x081f1f34}
MAGIC = 0x1DE30000
TRAPA = 0xC3


class Asm:
    """mini-montador SH-4 (só o que o stub usa)."""
    def __init__(self, base):
        self.base = base; self.code = []; self.labels = {}; self.fix = []; self.lits = []

    def pc(self): return self.base + 2 * len(self.code)
    def label(self, n): self.labels[n] = self.pc()
    def w(self, v): self.code.append(v & 0xffff)

    def movl_push(self, m): self.w(0x2f06 | m << 4)                     # mov.l Rm,@-r15
    def movl_pop(self, n): self.w(0x60f6 | n << 8)                      # mov.l @r15+,Rn
    def sts_pr_push(self): self.w(0x4f22)
    def lds_pr_pop(self): self.w(0x4f26)
    def mov(self, m, n): self.w(0x6003 | n << 8 | m << 4)
    def movi(self, imm, n): self.w(0xe000 | n << 8 | (imm & 0xff))
    def addi(self, imm, n): self.w(0x7000 | n << 8 | (imm & 0xff))
    def add(self, m, n): self.w(0x300c | n << 8 | m << 4)
    def movl_st(self, m, n): self.w(0x2002 | n << 8 | m << 4)          # mov.l Rm,@Rn
    def movl_std(self, m, disp, n): self.w(0x1000 | n << 8 | m << 4 | (disp // 4))   # mov.l Rm,@(disp,Rn)
    def trapa(self, imm): self.w(0xc300 | imm)
    def movb_ld0(self, disp, m): self.w(0x8400 | m << 4 | disp)      # mov.b @(disp,Rm),R0
    def movb_r0(self, m, n): self.w(0x000c | n << 8 | m << 4)          # mov.b @(R0,Rm),Rn
    def cmppl(self, n): self.w(0x4015 | n << 8)                         # T = Rn > 0
    def cmpeqi(self, imm): self.w(0x8800 | (imm & 0xff))
    def tst(self, m, n): self.w(0x2008 | n << 8 | m << 4)
    def cmpgt(self, m, n): self.w(0x3007 | n << 8 | m << 4)             # T = Rn > Rm
    def jsr(self, m): self.w(0x400b | m << 8)
    def rts(self): self.w(0x000b)
    def nop(self): self.w(0x0009)
    def bt(self, l): self.fix.append((len(self.code), 'b8', l)); self.w(0x8900)
    def bf(self, l): self.fix.append((len(self.code), 'b8', l)); self.w(0x8b00)
    def bra(self, l): self.fix.append((len(self.code), 'b12', l)); self.w(0xa000)
    def lit(self, v, n):                                               # mov.l @(disp,PC),Rn com o valor v no pool
        self.fix.append((len(self.code), 'lit', v)); self.w(0xd000 | n << 8)

    def build(self):
        while len(self.code) % 2: self.nop()                          # pool alinhado em 4
        pool = {}
        for _, k, v in self.fix:
            if k == 'lit' and v not in pool:
                pool[v] = self.base + 2 * len(self.code); self.code += [v & 0xffff, v >> 16]
        for i, k, v in self.fix:
            a = self.base + 2 * i
            if k == 'lit':
                d = (pool[v] - ((a & ~3) + 4)) // 4; assert 0 <= d < 256
                self.code[i] |= d
            else:
                d = (self.labels[v] - (a + 4)) // 2
                if k == 'b8': assert -128 <= d < 128; self.code[i] |= d & 0xff
                else: assert -2048 <= d < 2048; self.code[i] |= d & 0xfff
        return b''.join(struct.pack('<H', x) for x in self.code)


def stub():
    a = Asm(CAVE_VA)
    for r in (8, 9, 10, 11): a.movl_push(r)
    a.sts_pr_push()
    a.mov(4, 8); a.mov(5, 9); a.mov(6, 10)                             # r8 = this, r9 = buf, r10 = tamanho máximo
    a.lit(MAGIC | 0, 0); a.trapa(TRAPA)                                # classificar (r4 = this, r5 = buf)
    a.cmpeqi(1); a.bt('inj')
    a.cmpeqi(2); a.bf('orig')
    # 1ª chamada: cria a thread de injeção (mesmo laço, mesmo this) com pilha de 128 KB
    a.addi(-128, 15)                                                   # @r15 = pthread_t, @(8,r15) = pthread_attr_t
    a.mov(15, 4); a.addi(8, 4); a.lit(PLT['pthread_attr_init'], 1); a.jsr(1); a.nop()
    a.mov(15, 4); a.addi(8, 4); a.lit(0x20000, 5); a.lit(PLT['pthread_attr_setstacksize'], 1); a.jsr(1); a.nop()
    a.mov(15, 4); a.mov(15, 5); a.addi(8, 5); a.lit(ANCHOR_VA, 6); a.mov(8, 7)
    a.lit(PLT['pthread_create'], 1); a.jsr(1); a.nop()
    a.addi(64, 15); a.addi(64, 15)
    a.label('orig')                                                    # thread real: recv original
    a.mov(8, 4); a.mov(9, 5); a.mov(10, 6); a.lit(RECV_VA, 1); a.jsr(1); a.nop()
    # descarta os erros do Root para o FBlock 0xE5 (sem MOST ele responde "FBlock indisponível" a tudo o que o HMI manda ao
    # controlador, e o HMI daria o controlador como ausente): tipo 2, FBlock E5, OpType 0x0F
    a.mov(0, 11); a.cmppl(11); a.bf('ret')
    a.movb_ld0(2, 9); a.cmpeqi(2); a.bf('ret')
    a.movb_ld0(6, 9); a.cmpeqi(0xe5); a.bf('ret')
    a.movb_ld0(10, 9); a.cmpeqi(0x0f); a.bf('ret')
    a.bra('orig'); a.nop()
    a.label('ret')
    a.mov(11, 0)
    a.bra('out'); a.nop()
    a.label('inj')                                                     # thread de injeção: espera um telegrama do QEMU
    a.lit(MAGIC | 1, 0); a.trapa(TRAPA)
    a.tst(0, 0); a.bf('got')
    a.addi(-8, 15); a.movi(0, 1); a.movl_st(1, 15); a.lit(20000000, 1); a.movl_std(1, 4, 15)
    a.mov(15, 4); a.movi(0, 5); a.lit(PLT['nanosleep'], 1); a.jsr(1); a.nop()
    a.addi(8, 15)
    a.bra('inj'); a.nop()
    a.label('got')
    a.mov(0, 11); a.movi(0, 10)
    a.label('copy')                                                    # copia o telegrama de 4 em 4 bytes para buf
    a.mov(10, 4); a.lit(MAGIC | 2, 0); a.trapa(TRAPA)
    a.mov(9, 1); a.add(10, 1); a.movl_st(0, 1)
    a.addi(4, 10); a.cmpgt(10, 11); a.bt('copy')
    a.mov(11, 0)
    a.label('out')
    a.lds_pr_pop()
    for r in (11, 10, 9): a.movl_pop(r)
    a.rts(); a.movl_pop(8)
    # ---- envio (r4 = canal, r5 = buf, r6 = tamanho): copia para o QEMU os telegramas MOST para 0xE5 e chama o sendMsg original
    a.label('tx')
    for r in (8, 9, 10, 11): a.movl_push(r)
    a.sts_pr_push()
    a.mov(4, 8); a.mov(5, 9); a.mov(6, 10)
    a.movi(12, 1); a.cmpgt(1, 10); a.bf('txcall')                     # tamanho > 12
    a.movb_ld0(2, 9); a.cmpeqi(2); a.bf('txcall')
    a.movb_ld0(6, 9); a.cmpeqi(0xe5); a.bf('txcall')
    a.mov(10, 4); a.lit(MAGIC | 3, 0); a.trapa(TRAPA)
    a.movi(0, 11)
    a.label('txb')
    a.mov(11, 0); a.movb_r0(9, 5); a.mov(11, 4); a.lit(MAGIC | 4, 0); a.trapa(TRAPA)
    a.addi(1, 11); a.cmpgt(11, 10); a.bt('txb')
    a.lit(MAGIC | 5, 0); a.trapa(TRAPA)
    a.label('txcall')
    a.mov(8, 4); a.mov(9, 5); a.mov(10, 6); a.lit(SEND_VA, 1); a.jsr(1); a.nop()
    a.lds_pr_pop()
    for r in (11, 10, 9): a.movl_pop(r)
    a.rts(); a.movl_pop(8)
    code = a.build()
    assert len(code) <= CAVE_SIZE
    return code, a.labels['tx']


def patch_ifs2(data):
    """aplica o patch no IFS2 (bytes); devolve os bytes alterados."""
    assert data.count(ANCHOR) == 1, 'HmiMain: laço do MTP não achado no IFS2'
    o = data.index(ANCHOR)
    off = lambda va: o + (va - ANCHOR_VA)
    assert data[off(CAVE_VA):off(CAVE_VA) + len(CAVE)] == CAVE, 'HmiMain: área do stub não confere'
    assert struct.unpack_from('<I', data, off(LIT_VA))[0] == (RECV_VA - LIT_BASE) & 0xffffffff, 'HmiMain: chamada do recv não confere'
    assert struct.unpack_from('<I', data, off(TXLIT_VA))[0] == (SEND_VA - TXLIT_BASE) & 0xffffffff, 'HmiMain: chamada do sendMsg não confere'
    b = bytearray(data)
    code, tx = stub()
    b[off(CAVE_VA):off(CAVE_VA) + len(code)] = code
    struct.pack_into('<I', b, off(LIT_VA), (CAVE_VA - LIT_BASE) & 0xffffffff)
    struct.pack_into('<I', b, off(TXLIT_VA), (tx - TXLIT_BASE) & 0xffffffff)
    return bytes(b)


IFS2_OFF, IFS2_LEN = 0x740000, 73662464     # segmento IFS2 na flash NOR (run.FLASH_SEGS)


def patch_flash_file(path):
    """aplica o patch numa flash.img já montada (idempotente). Devolve 'ok' (já tinha), 'patched' ou levanta erro."""
    with open(path, 'r+b') as f:
        f.seek(IFS2_OFF)
        data = f.read(IFS2_LEN)
        o = data.find(ANCHOR)
        assert o >= 0, 'HmiMain: laço do MTP não achado na flash'
        code, _ = stub()
        c = o + (CAVE_VA - ANCHOR_VA)
        if data[c:c + len(code)] == code:
            return 'ok'
        new = patch_ifs2(data)
        f.seek(IFS2_OFF)
        f.write(new)
    return 'patched'


if __name__ == '__main__':
    import sys
    sys.path.insert(0, __import__('os').path.dirname(__file__))
    from dis import dis
    for a, w, t in dis(stub()[0], CAVE_VA):
        print('%08x  %04x  %s' % (a, w, t))

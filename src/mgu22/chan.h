// Canal guest <-> host do iDrive 8: dois anéis em memória travada do processo guest. O host encontra o
// cabeçalho varrendo a RAM do guest (arquivo compartilhado com o QEMU) e traduz cada página pelo PFN.
#ifndef IDEMU_CHAN_H
#define IDEMU_CHAN_H
#define CH_MAGIC "IDEMU-MGU-CHAN-1"
#define CH_RING_A (16u << 20)  // guest -> host
#define CH_RING_B (8u << 20)   // host -> guest
#define CH_PAGE 4096u
#define CH_MAXTABLE 64
typedef struct ch_hdr {
  char magic[16];
  unsigned version, pages_a, pages_b, ntable;
  unsigned long nonce;
  unsigned pid, tid, role;  // role: 0 = GL, 1 = comandos do host para um daemon do guest
  unsigned table_pfn[CH_MAXTABLE];  // páginas com a tabela u32 pfn[pages_a + pages_b]
  volatile unsigned long a_wr __attribute__((aligned(64)));
  volatile unsigned long a_rd __attribute__((aligned(64)));
  volatile unsigned long b_wr __attribute__((aligned(64)));
  volatile unsigned long b_rd __attribute__((aligned(64)));
} ch_hdr;
_Static_assert(sizeof(ch_hdr) <= CH_PAGE, "cabecalho");
#endif

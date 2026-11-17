// Canal guest <-> host do iDrive 8: dois anéis em memória travada do processo guest. O host encontra o
// cabeçalho varrendo a RAM do guest (arquivo compartilhado com o QEMU) e traduz cada página pelo PFN.
#ifndef IDEMU_CHAN_H
#define IDEMU_CHAN_H
#define CH_MAGIC "IDEMU-MGU-CHAN-1"
#define CH_RING_A (16u << 20)  // guest -> host
#define CH_RING_B (8u << 20)   // host -> guest
#define CH_PAGE 4096u
#define CH_MAXTABLE 64
/* The wire layout is Linux AArch64 LP64, including on a Windows LLP64 host. */
typedef __UINT64_TYPE__ ch_u64;
typedef struct ch_hdr {
  char magic[16];
  unsigned version, pages_a, pages_b, ntable;
  ch_u64 nonce;
  unsigned pid, tid, role;  // role: 0 = GL, 1 = comandos do host para um daemon do guest
  unsigned table_pfn[CH_MAXTABLE];  // páginas com a tabela u32 pfn[pages_a + pages_b]
  volatile ch_u64 a_wr __attribute__((aligned(64)));
  volatile ch_u64 a_rd __attribute__((aligned(64)));
  volatile ch_u64 b_wr __attribute__((aligned(64)));
  volatile ch_u64 b_rd __attribute__((aligned(64)));
} ch_hdr;
_Static_assert(sizeof(ch_hdr) == 576, "channel wire size");
_Static_assert(__builtin_offsetof(ch_hdr, nonce) == 32, "channel nonce offset");
_Static_assert(__builtin_offsetof(ch_hdr, table_pfn) == 52, "channel page table offset");
_Static_assert(__builtin_offsetof(ch_hdr, a_wr) == 320, "channel write offset");
_Static_assert(__builtin_offsetof(ch_hdr, b_rd) == 512, "channel read offset");
#endif

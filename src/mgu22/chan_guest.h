// Lado guest do canal (chan.h). Depende das declarações feitas por quem inclui.
#ifndef LOG
#define LOG(...)
#endif
typedef struct Ch {
  ch_hdr *h; char *a, *b;
  ul awr, brd;  // cópias locais
  int unpack_align, unpack_row, unpack_img, unpack_skip_px, unpack_skip_rows, unpack_skip_img, pack_align, pack_row;
} Ch;
static inline void rel(volatile ul *p, ul v) { __atomic_store_n(p, v, __ATOMIC_RELEASE); }
static inline ul acq(volatile ul *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
static void wait_tick(int *n) {
  if (++*n < 200) { __asm__("yield"); return; }
  if (*n < 800) { sched_yield(); return; }
  struct { long s, ns; } t = { 0, 30000 }; nanosleep(&t, 0);
}
static Ch *ch_open(unsigned role) {
  u32 pa = CH_RING_A / CH_PAGE, pb = CH_RING_B / CH_PAGE, nt = ((pa + pb) * 4 + CH_PAGE - 1) / CH_PAGE;
  ul total = (1 + nt + pa + pb) * (ul)CH_PAGE;
  char *m = mmap(0, total, 3, 0x02 | 0x20 | 0x8000 | 0x2000, -1, 0);  // PRIVATE|ANON|POPULATE|LOCKED
  if (m == (char *)-1) { LOG("mmap do canal falhou\n"); return 0; }
  for (ul i = 0; i < total; i += CH_PAGE) m[i] = 0;
  int fd = open("/proc/self/pagemap", 0);
  u32 *tbl = (u32 *)(m + CH_PAGE);
  ch_hdr *h = (ch_hdr *)m;
  ul first = (ul)m / CH_PAGE;
  for (u32 i = 0; i < 1 + nt + pa + pb; i++) {
    ul e = 0; pread(fd, &e, 8, (first + i) * 8);
    if (!(e >> 63)) LOG("pagina %u ausente\n", i);
    u32 pfn = (u32)(e & ((1ul << 55) - 1));
    if (i >= 1 && i < 1 + nt) h->table_pfn[i - 1] = pfn;
    if (i >= 1 + nt) tbl[i - 1 - nt] = pfn;
  }
  close(fd);
  h->version = 1; h->role = role; h->pages_a = pa; h->pages_b = pb; h->ntable = nt; h->pid = getpid(); h->tid = syscall(178);
  h->nonce = (ul)m ^ ((ul)h->tid << 40);
  Ch *c = malloc(sizeof(Ch)); memset(c, 0, sizeof *c);
  c->h = h; c->a = m + (1 + nt) * (ul)CH_PAGE; c->b = c->a + CH_RING_A; c->unpack_align = c->pack_align = 4;
  __atomic_thread_fence(__ATOMIC_SEQ_CST);
  memcpy(h->magic, CH_MAGIC, 16);
  __atomic_thread_fence(__ATOMIC_SEQ_CST);
  return c;
}
static void get(Ch *c, void *p, ul n) {
  char *d = p; int k = 0;
  while (n) {
    ul wr = acq(&c->h->b_wr); ul av = wr - c->brd;
    if (!av) { wait_tick(&k); continue; }
    k = 0;
    ul pos = c->brd % CH_RING_B, ch = CH_RING_B - pos; if (ch > av) ch = av; if (ch > n) ch = n;
    memcpy(d, c->b + pos, ch); d += ch; n -= ch; c->brd += ch; rel(&c->h->b_rd, c->brd);
  }
}

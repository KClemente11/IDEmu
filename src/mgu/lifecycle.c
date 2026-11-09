// idemu-lifecycle: oferece o serviço SOME/IP LifecycleRSE (0xB016, instância 1) ao vsomeipd pelo protocolo local do vsomeip.
// O serviço pertence ao head unit; o RSE não sai do modo de baixo consumo sem ele. Campos: powerStateDetailedLeft (get 17, evento 0x8001),
// powerStateDetailedRight (get 18, 0x8002), focusIndicatorHMI (get 21, set 37, 0x8005). Formato dos quadros capturado com libspy.so.
typedef unsigned char u8; typedef unsigned short u16; typedef unsigned int u32; typedef unsigned long size_t; typedef long ssize_t;
extern int socket(int,int,int); extern int connect(int,const void*,u32); extern int bind(int,const void*,u32); extern int listen(int,int); extern int accept(int,void*,void*);
extern ssize_t read(int,void*,size_t); extern ssize_t write(int,const void*,size_t); extern int close(int); extern int poll(void*,unsigned long,int);
extern int unlink(const char*); extern int chmod(const char*,u32); extern int fprintf(void*,const char*,...); extern void *stderr; extern int snprintf(char*,size_t,const char*,...);
extern void *memcpy(void*,const void*,size_t); extern void *memset(void*,int,size_t); extern size_t strlen(const char*); extern int usleep(u32);

#define SVC 0xB016
#define INST 1
static int rm = -1, lsn = -1; static u16 me;
static u8 pw_left = 99, pw_right = 99, focus = 1;
struct pf { int fd; short ev, rev; };

static int unix_connect(const char *path) {
  int s = socket(1, 1, 0); struct { u16 f; char p[108]; } a; memset(&a, 0, sizeof a); a.f = 1; memcpy(a.p, path, strlen(path));
  if (connect(s, &a, sizeof a)) { close(s); return -1; } return s;
}
static void wr(int fd, const void *p, size_t n) { const u8 *s = p; while (n) { ssize_t r = write(fd, s, n); if (r <= 0) return; s += r; n -= r; } }
static void frame(int fd, u8 cmd, u16 client, const u8 *pl, u32 n) {
  u8 b[512]; int k = 0; static const u8 st[4] = {0x67,0x37,0x6d,0x07}, en[4] = {0x07,0x6d,0x37,0x67};
  memcpy(b, st, 4); k = 4; b[k++] = cmd; b[k++] = client & 255; b[k++] = client >> 8; memcpy(b + k, &n, 4); k += 4; if (n) memcpy(b + k, pl, n); k += n; memcpy(b + k, en, 4); k += 4;
  wr(fd, b, k);
}
static void le16(u8 *p, u16 v) { p[0] = v; p[1] = v >> 8; }
static void send_someip(int fd, u16 inst, const u8 *msg, u32 mlen) {          // SEND: [instância u16][0 0][meu id u16][mensagem SOME/IP]
  u8 pl[256]; le16(pl, inst); pl[2] = 0; pl[3] = 0; le16(pl + 4, me); memcpy(pl + 6, msg, mlen); frame(fd, 0x18, me, pl, 6 + mlen);
}
static u32 build_msg(u8 *o, u16 method, u16 client, u16 sess, u8 type, const u8 *pl, u32 n) {
  o[0] = SVC >> 8; o[1] = SVC & 255; o[2] = method >> 8; o[3] = method & 255; u32 len = 8 + n; o[4] = len >> 24; o[5] = len >> 16; o[6] = len >> 8; o[7] = len;
  o[8] = client >> 8; o[9] = client & 255; o[10] = sess >> 8; o[11] = sess & 255; o[12] = 1; o[13] = 1; o[14] = type; o[15] = 0; if (n) memcpy(o + 16, pl, n); return 16 + n;
}
static int peer_conn(u16 id) { char p[64]; snprintf(p, sizeof p, "/tmp/vsomeip-%x", id); int s = unix_connect(p); if (s >= 0) { u8 b[2]; le16(b, me); wr(s, b, 2); } return s; }

static void notify_one(u16 sub, u16 evid, u8 val, u16 sess) {
  int s = peer_conn(sub); if (s < 0) return; u8 m[32]; u32 n = build_msg(m, evid, 0, sess, 0x02, &val, 1); send_someip(s, INST, m, n); close(s);
}
static void handle_cmd(u8 cmd, u16 client, const u8 *pl, u32 n) {
  static u16 sess = 1;
  switch (cmd) {
  case 0x07: frame(rm, 0x08, me, 0, 0); break;                                // PING -> PONG
  case 0x12: if (n >= 11) {                                                   // SUBSCRIBE(client=assinante)
      u16 evg = pl[4] | pl[5] << 8, ev = pl[7] | pl[8] << 8, pend = pl[9] | pl[10] << 8; u8 ack[12];
      memcpy(ack, pl, 4); le16(ack + 4, evg); le16(ack + 6, client); le16(ack + 8, ev); le16(ack + 10, pend);
      int s = peer_conn(client); if (s >= 0) { frame(s, 0x17, me, ack, 12); close(s); }
      fprintf(stderr, "[lc] subscribe de %04x grupo %u evento %04x\n", client, evg, ev);
      usleep(20000); notify_one(client, 0x8001, pw_left, sess++); notify_one(client, 0x8002, pw_right, sess++); notify_one(client, 0x8005, focus, sess++);
    } break;
  case 0x18: if (n >= 6 + 16) {                                               // SEND: requisição
      const u8 *m = pl + 6; u16 meth = m[2] << 8 | m[3], cl = m[8] << 8 | m[9], ss = m[10] << 8 | m[11]; u8 type = m[14]; u16 from = pl[4] | pl[5] << 8;
      u8 val = 0; int have = 0;
      if (meth == 17) { val = pw_left; have = 1; } else if (meth == 18) { val = pw_right; have = 1; } else if (meth == 21) { val = focus; have = 1; }
      else if (meth == 37 && n > 6 + 16) { focus = m[16]; val = focus; have = 1; }
      fprintf(stderr, "[lc] chamada método %u tipo %02x de %04x -> %s\n", meth, type, from, have ? "resposta" : "ignorada");
      if (have && type == 0x00) { int s = peer_conn(from); if (s >= 0) { u8 r[32]; u32 k = build_msg(r, meth, cl, ss, 0x80, &val, 1); send_someip(s, INST, r, k); close(s); } }
    } break;
  default: break;
  }
}

struct conn { int fd, len, gotid; u8 b[8192]; };
static struct conn cn[8]; static int registered;
static void do_register(void) {
  registered = 1; frame(rm, 0x06, me, 0, 0);
  u8 o[9]; le16(o, SVC); le16(o + 2, INST); o[4] = 1; o[5] = 2; o[6] = o[7] = o[8] = 0; frame(rm, 0x10, me, o, 9);
  static const u16 evs[3] = {0x8001, 0x8002, 0x8005};
  for (int e = 0; e < 3; e++) { u8 x[11]; le16(x, SVC); le16(x + 2, INST); le16(x + 4, evs[e]); x[6] = 2; x[7] = 1; x[8] = 0xff; le16(x + 9, 1); frame(rm, 0x1b, me, x, 11); }
  fprintf(stderr, "[lc] servico 0xb016/1 oferecido\n");
}
static void feed(struct conn *c) {
  ssize_t r = read(c->fd, c->b + c->len, sizeof c->b - c->len); if (r <= 0) { close(c->fd); c->fd = -1; return; } c->len += r;
  int off = 0; if (!c->gotid) { if (c->len < 2) return; c->gotid = 1; off = 2; }
  for (;;) {
    if (c->len - off < 11) break; if (!(c->b[off] == 0x67 && c->b[off+1] == 0x37 && c->b[off+2] == 0x6d && c->b[off+3] == 0x07)) { off++; continue; }
    u32 sz; memcpy(&sz, c->b + off + 7, 4); if (c->len - off < (int)(4 + 7 + sz + 4)) break;
    u8 cmd = c->b[off + 4]; if (cmd == 0x05 && !registered) do_register();
    handle_cmd(cmd, c->b[off + 5] | c->b[off + 6] << 8, c->b + off + 11, sz); off += 4 + 7 + sz + 4;
  }
  if (off) { memcpy(c->b, c->b + off, c->len - off); c->len -= off; }
}
int main(void) {
  rm = unix_connect("/tmp/vsomeip-0"); if (rm < 0) { fprintf(stderr, "[lc] sem vsomeipd\n"); return 1; }
  u8 ff[2] = {0xff, 0xff}; wr(rm, ff, 2); const char *name = "LifecycleRSEHU"; frame(rm, 0x00, 0xffff, (const u8*)name, strlen(name));
  { u8 t[64]; int got = 0; while (got < 15) { ssize_t r = read(rm, t + got, sizeof t - got); if (r <= 0) return 2; got += r; } me = t[11] | t[12] << 8; }
  char path[64]; snprintf(path, sizeof path, "/tmp/vsomeip-%x", me); unlink(path);
  lsn = socket(1, 1, 0); struct { u16 f; char p[108]; } a; memset(&a, 0, sizeof a); a.f = 1; memcpy(a.p, path, strlen(path)); if (bind(lsn, &a, sizeof a) || listen(lsn, 8)) return 3; chmod(path, 0666);
  fprintf(stderr, "[lc] cliente %04x, ouvindo %s\n", me, path);
  frame(rm, 0x02, me, 0, 0);
  for (int i = 0; i < 8; i++) cn[i].fd = -1;
  for (;;) {
    struct pf p[10]; int n = 0, map[10]; p[n].fd = lsn; map[n++] = -1; p[n].fd = rm; map[n++] = -2;
    for (int i = 0; i < 8; i++) if (cn[i].fd >= 0) { p[n].fd = cn[i].fd; map[n++] = i; }
    for (int i = 0; i < n; i++) { p[i].ev = 1; p[i].rev = 0; }
    poll(p, n, 500);
    if (p[0].rev & 1) { int f = accept(lsn, 0, 0), i; for (i = 0; i < 8 && cn[i].fd >= 0; i++) ; if (i == 8) close(f); else { cn[i].fd = f; cn[i].len = 0; cn[i].gotid = 0; } }
    if (p[1].rev & 0x19) { u8 t[2048]; ssize_t k = read(rm, t, sizeof t); if (k <= 0) { fprintf(stderr, "[lc] RM fechou\n"); return 4; }
      for (ssize_t j = 0; j + 11 <= k; j++) if (t[j]==0x67&&t[j+1]==0x37&&t[j+2]==0x6d&&t[j+3]==0x07&&t[j+4]==0x07) frame(rm, 0x08, me, 0, 0); }
    for (int k = 2; k < n; k++) if (p[k].rev & 0x19) feed(&cn[map[k]]);
  }
}
__asm__(".globl _start\n_start:\n xor %ebp,%ebp\n and $-16,%rsp\n call main\n mov %eax,%edi\n mov $60,%eax\n syscall\n");

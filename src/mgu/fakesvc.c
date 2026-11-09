// idemu-fakesvc: oferece ao vsomeipd serviços SOME/IP falsos do head unit (iDrive 7), lidos de uma tabela de texto gerada por tools/mgu/gen_fakesvc.py
// a partir de someip-interfaces.json. Cada serviço tem campos (getter, setter, notificador) com um valor fixo; o HMI central (HU_HMI) espera pelos serviços
// Lifecycle, VehicleCondition, Key... para sair de "não disponível". Mesmo protocolo local do vsomeip que src/mgu/lifecycle.c (quadros capturados com libspy.so).
// Uso: idemu-fakesvc [tabela]  (padrão /etc/idemu/fakesvc.tab). Controle ao vivo: linhas "set <campo> <hex>" no FIFO /run/fakesvc.ctl.
typedef unsigned char u8; typedef unsigned short u16; typedef unsigned int u32; typedef unsigned long size_t; typedef long ssize_t;
extern int socket(int,int,int); extern int connect(int,const void*,u32); extern int bind(int,const void*,u32); extern int listen(int,int); extern int accept(int,void*,void*);
extern ssize_t read(int,void*,size_t); extern ssize_t write(int,const void*,size_t); extern int close(int); extern int poll(void*,unsigned long,int);
extern int unlink(const char*); extern int chmod(const char*,u32); extern int fprintf(void*,const char*,...); extern void *stderr; extern int snprintf(char*,size_t,const char*,...);
extern void *memcpy(void*,const void*,size_t); extern void *memset(void*,int,size_t); extern size_t strlen(const char*); extern int usleep(u32);
extern int open(const char*,int,...); extern int mkfifo(const char*,u32); extern int strcmp(const char*,const char*); extern long strtol(const char*,char**,int);

#define MAXS 64
#define MAXF 1024
#define MAXV 96
struct svc { u16 id, inst; u8 major; u32 minor; char name[48]; u16 subs[8]; int nsubs; };
struct fld { int svc; int get, set, notif, grp; u8 val[MAXV]; int vlen; char name[40]; };
static struct svc sv[MAXS]; static int nsv; static struct fld fl[MAXF]; static int nfl;
static int rm = -1, lsn = -1; static u16 me; static u16 sess = 1;
struct pf { int fd; short ev, rev; };

static int unix_connect(const char *path) {
  int s = socket(1, 1, 0); struct { u16 f; char p[108]; } a; memset(&a, 0, sizeof a); a.f = 1; memcpy(a.p, path, strlen(path));
  if (connect(s, &a, sizeof a)) { close(s); return -1; } return s;
}
static void wr(int fd, const void *p, size_t n) { const u8 *s = p; while (n) { ssize_t r = write(fd, s, n); if (r <= 0) return; s += r; n -= r; } }
static void frame(int fd, u8 cmd, u16 client, const u8 *pl, u32 n) {
  u8 b[1024]; int k; static const u8 st[4] = {0x67,0x37,0x6d,0x07}, en[4] = {0x07,0x6d,0x37,0x67};
  memcpy(b, st, 4); k = 4; b[k++] = cmd; b[k++] = client & 255; b[k++] = client >> 8; memcpy(b + k, &n, 4); k += 4; if (n) memcpy(b + k, pl, n); k += n; memcpy(b + k, en, 4); k += 4;
  wr(fd, b, k);
}
static void le16(u8 *p, u16 v) { p[0] = v; p[1] = v >> 8; }
static void send_someip(int fd, u16 inst, const u8 *msg, u32 mlen) {          // SEND: [instância u16][0 0][meu id u16][mensagem SOME/IP]
  u8 pl[512]; le16(pl, inst); pl[2] = 0; pl[3] = 0; le16(pl + 4, me); memcpy(pl + 6, msg, mlen); frame(fd, 0x18, me, pl, 6 + mlen);
}
static u32 build_msg(u8 *o, struct svc *s, u16 method, u16 client, u16 ss, u8 type, const u8 *pl, u32 n) {
  o[0] = s->id >> 8; o[1] = s->id & 255; o[2] = method >> 8; o[3] = method & 255; u32 len = 8 + n; o[4] = len >> 24; o[5] = len >> 16; o[6] = len >> 8; o[7] = len;
  o[8] = client >> 8; o[9] = client & 255; o[10] = ss >> 8; o[11] = ss & 255; o[12] = 1; o[13] = s->major; o[14] = type; o[15] = 0; if (n) memcpy(o + 16, pl, n); return 16 + n;
}
static int peer_conn(u16 id) { char p[64]; snprintf(p, sizeof p, "/tmp/vsomeip-%x", id); int s = unix_connect(p); if (s >= 0) { u8 b[2]; le16(b, me); wr(s, b, 2); } return s; }
static void notify_one(struct svc *s, struct fld *f, u16 sub) {
  if (f->notif < 0) return; int c = peer_conn(sub); if (c < 0) return; u8 m[256]; u32 n = build_msg(m, s, f->notif, 0, sess++, 0x02, f->val, f->vlen); send_someip(c, s->inst, m, n); close(c);
}
static void notify_all(struct svc *s, struct fld *f) { for (int i = 0; i < s->nsubs; i++) notify_one(s, f, s->subs[i]); }
static struct svc *find_svc(u16 id) { for (int i = 0; i < nsv; i++) if (sv[i].id == id) return &sv[i]; return 0; }
static void add_sub(struct svc *s, u16 c) { for (int i = 0; i < s->nsubs; i++) if (s->subs[i] == c) return; if (s->nsubs < 8) s->subs[s->nsubs++] = c; }

static void handle_cmd(u8 cmd, u16 client, const u8 *pl, u32 n) {
  switch (cmd) {
  case 0x07: frame(rm, 0x08, me, 0, 0); break;                                // PING -> PONG
  case 0x12: if (n >= 11) {                                                   // SUBSCRIBE(client = assinante): [svc][inst][grupo][major][evento][pendente]
      struct svc *s = find_svc(pl[0] | pl[1] << 8); if (!s) break;
      u16 evg = pl[4] | pl[5] << 8, ev = pl[7] | pl[8] << 8, pend = pl[9] | pl[10] << 8; u8 ack[12];
      memcpy(ack, pl, 4); le16(ack + 4, evg); le16(ack + 6, client); le16(ack + 8, ev); le16(ack + 10, pend);
      int c = peer_conn(client); if (c >= 0) { frame(c, 0x17, me, ack, 12); close(c); }
      add_sub(s, client); fprintf(stderr, "[fs] subscribe de %04x em %04x/%x grupo %u evento %04x\n", client, s->id, s->inst, evg, ev);
      usleep(20000);
      for (int i = 0; i < nfl; i++) if (&sv[fl[i].svc] == s && fl[i].notif >= 0 && (ev == 0xffff ? fl[i].grp == evg : fl[i].notif == ev)) notify_one(s, &fl[i], client);
    } break;
  case 0x18: if (n >= 6 + 16) {                                               // SEND: requisição
      const u8 *m = pl + 6; u16 svc = m[0] << 8 | m[1], meth = m[2] << 8 | m[3], cl = m[8] << 8 | m[9], ss = m[10] << 8 | m[11]; u8 type = m[14]; u16 from = pl[4] | pl[5] << 8;
      struct svc *s = find_svc(svc); if (!s) break; struct fld *f = 0; int isset = 0; u32 plen = n - 6 - 16;
      for (int i = 0; i < nfl && !f; i++) if (&sv[fl[i].svc] == s) { if (fl[i].get == meth) f = &fl[i]; else if (fl[i].set == meth) { f = &fl[i]; isset = 1; } }
      fprintf(stderr, "[fs] chamada %04x metodo %u tipo %02x de %04x -> %s%s\n", svc, meth, type, from, f ? f->name : "ignorada", isset ? " (set)" : "");
      if (!f) break;
      if (isset && plen > 0 && plen <= MAXV) { memcpy(f->val, m + 16, plen); f->vlen = plen; notify_all(s, f); }
      if (type == 0x00) { int c = peer_conn(from); if (c >= 0) { u8 r[256]; u32 k = build_msg(r, s, meth, cl, ss, 0x80, f->val, f->vlen); send_someip(c, s->inst, r, k); close(c); } }
    } break;
  default: break;
  }
}

struct conn { int fd, len, gotid; u8 b[8192]; };
static struct conn cn[8]; static int registered;
static void do_register(void) {
  registered = 1; frame(rm, 0x06, me, 0, 0);
  for (int i = 0; i < nsv; i++) { u8 o[9]; le16(o, sv[i].id); le16(o + 2, sv[i].inst); o[4] = sv[i].major; memcpy(o + 5, &sv[i].minor, 4); frame(rm, 0x10, me, o, 9); }
  for (int i = 0; i < nfl; i++) if (fl[i].notif >= 0) {
    u8 x[11]; struct svc *s = &sv[fl[i].svc]; le16(x, s->id); le16(x + 2, s->inst); le16(x + 4, fl[i].notif); x[6] = 2; x[7] = 1; x[8] = 0xff; le16(x + 9, fl[i].grp); frame(rm, 0x1b, me, x, 11);
  }
  fprintf(stderr, "[fs] %d servicos oferecidos\n", nsv);
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

// ---- tabela
static int hexv(int c) { return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1; }
static int parse_hex(const char *s, u8 *o, int max) { int n = 0; if (s[0] == '-') return 0; while (hexv(s[0]) >= 0 && hexv(s[1]) >= 0 && n < max) { o[n++] = hexv(s[0]) << 4 | hexv(s[1]); s += 2; } return n; }
static int tok(char **p, char **out) { while (**p == ' ') (*p)++; if (!**p) return 0; *out = *p; while (**p && **p != ' ') (*p)++; if (**p) { **p = 0; (*p)++; } return 1; }
static int numtok(char *t) { return t[0] == '-' ? -1 : (int)strtol(t, 0, 10); }
static void load_table(const char *path) {
  static char buf[262144]; int fd = open(path, 0); if (fd < 0) { fprintf(stderr, "[fs] sem tabela %s\n", path); return; }
  int n = read(fd, buf, sizeof buf - 1); close(fd); if (n < 0) n = 0; buf[n] = 0;
  for (char *l = buf; *l;) {
    char *e = l; while (*e && *e != '\n') e++; if (*e) *e++ = 0;
    char *p = l, *t[8]; int k = 0; while (k < 8 && tok(&p, &t[k])) k++;
    if (k >= 6 && t[0][0] == 'S' && nsv < MAXS) {
      struct svc *s = &sv[nsv++]; memset(s, 0, sizeof *s); s->id = strtol(t[1], 0, 16); s->inst = strtol(t[2], 0, 16); s->major = strtol(t[3], 0, 10); s->minor = strtol(t[4], 0, 10);
      snprintf(s->name, sizeof s->name, "%s", t[5]);
    } else if (k >= 7 && t[0][0] == 'F' && nsv && nfl < MAXF) {
      struct fld *f = &fl[nfl++]; memset(f, 0, sizeof *f); f->svc = nsv - 1; f->get = numtok(t[1]); f->set = numtok(t[2]); f->notif = t[3][0] == '-' ? -1 : (int)strtol(t[3], 0, 16); f->grp = numtok(t[4]);
      f->vlen = parse_hex(t[5], f->val, MAXV); snprintf(f->name, sizeof f->name, "%s", t[6]);
    }
    l = e;
  }
  fprintf(stderr, "[fs] tabela: %d servicos, %d campos\n", nsv, nfl);
}
static void control_line(char *l) {                                           // "set <campo> <hex>"
  char *p = l, *t[4]; int k = 0; while (k < 4 && tok(&p, &t[k])) k++;
  if (k >= 3 && !strcmp(t[0], "set")) for (int i = 0; i < nfl; i++) if (!strcmp(fl[i].name, t[1])) {
    fl[i].vlen = parse_hex(t[2], fl[i].val, MAXV); notify_all(&sv[fl[i].svc], &fl[i]); fprintf(stderr, "[fs] set %s (%d bytes)\n", fl[i].name, fl[i].vlen);
  }
}

int main(int argc, char **argv) {
  load_table(argc > 1 ? argv[1] : "/etc/idemu/fakesvc.tab");
  if (!nsv) return 5;
  rm = unix_connect("/tmp/vsomeip-0"); if (rm < 0) { fprintf(stderr, "[fs] sem vsomeipd\n"); return 1; }
  u8 ff[2] = {0xff, 0xff}; wr(rm, ff, 2); const char *name = "idemu-fakesvc"; frame(rm, 0x00, 0xffff, (const u8*)name, strlen(name));
  { u8 t[64]; int got = 0; while (got < 15) { ssize_t r = read(rm, t + got, sizeof t - got); if (r <= 0) return 2; got += r; } me = t[11] | t[12] << 8; }
  char path[64]; snprintf(path, sizeof path, "/tmp/vsomeip-%x", me); unlink(path);
  lsn = socket(1, 1, 0); struct { u16 f; char p[108]; } a; memset(&a, 0, sizeof a); a.f = 1; memcpy(a.p, path, strlen(path)); if (bind(lsn, &a, sizeof a) || listen(lsn, 8)) return 3; chmod(path, 0666);
  fprintf(stderr, "[fs] cliente %04x, ouvindo %s\n", me, path);
  frame(rm, 0x02, me, 0, 0);
  for (int i = 0; i < 8; i++) cn[i].fd = -1;
  unlink("/run/fakesvc.ctl"); mkfifo("/run/fakesvc.ctl", 0666); chmod("/run/fakesvc.ctl", 0666); int ctl = open("/run/fakesvc.ctl", 0x802 /* O_RDWR|O_NONBLOCK */); char cb[256]; int cl = 0;
  for (;;) {
    struct pf p[11]; int n = 0, map[11]; p[n].fd = lsn; map[n++] = -1; p[n].fd = rm; map[n++] = -2; p[n].fd = ctl; map[n++] = -3;
    for (int i = 0; i < 8; i++) if (cn[i].fd >= 0) { p[n].fd = cn[i].fd; map[n++] = i; }
    for (int i = 0; i < n; i++) { p[i].ev = 1; p[i].rev = 0; }
    poll(p, n, 500);
    if (p[0].rev & 1) { int f = accept(lsn, 0, 0), i; for (i = 0; i < 8 && cn[i].fd >= 0; i++) ; if (i == 8) close(f); else { cn[i].fd = f; cn[i].len = 0; cn[i].gotid = 0; } }
    if (p[1].rev & 0x19) { u8 t[2048]; ssize_t k = read(rm, t, sizeof t); if (k <= 0) { fprintf(stderr, "[fs] RM fechou\n"); return 4; }
      for (ssize_t j = 0; j + 11 <= k; j++) if (t[j]==0x67&&t[j+1]==0x37&&t[j+2]==0x6d&&t[j+3]==0x07&&t[j+4]==0x07) frame(rm, 0x08, me, 0, 0);
      for (ssize_t j = 0; j + 11 <= k; j++) if (t[j]==0x67&&t[j+1]==0x37&&t[j+2]==0x6d&&t[j+3]==0x07&&t[j+4]==0x05 && !registered) do_register(); }
    if (p[2].rev & 1) { ssize_t k = read(ctl, cb + cl, sizeof cb - 1 - cl); if (k > 0) cl += k; cb[cl] = 0;
      for (;;) { int e = -1; for (int j = 0; j < cl; j++) if (cb[j] == '\n') { e = j; break; } if (e < 0) { if (cl > 200) cl = 0; break; }
        cb[e] = 0; control_line(cb); memcpy(cb, cb + e + 1, cl - e - 1); cl -= e + 1; } }
    for (int k = 3; k < n; k++) if (p[k].rev & 0x19) feed(&cn[map[k]]);
  }
}
__asm__(".globl _start\n_start:\n xor %ebp,%ebp\n mov (%rsp),%rdi\n lea 8(%rsp),%rsi\n and $-16,%rsp\n call main\n mov %eax,%edi\n mov $60,%eax\n syscall\n");

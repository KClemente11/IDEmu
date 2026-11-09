// Compositor Wayland mínimo para o HmiMain3D (iDrive 7) no guest: só responde ao protocolo.
// Fala o fio do Wayland direto (sem libwayland-server). Globals: wl_compositor, wl_output, wl_seat,
// ivi_application, ivi_controller (com uma tela). Requisições desconhecidas são ignoradas.
typedef unsigned int u32; typedef int i32; typedef unsigned long size_t; typedef long ssize_t; typedef unsigned char u8;
extern int socket(int,int,int); extern int bind(int,const void*,u32); extern int listen(int,int); extern int accept(int,void*,void*);
extern ssize_t read(int,void*,size_t); extern ssize_t write(int,const void*,size_t); extern int close(int);
extern int poll(void*,unsigned long,int); extern int unlink(const char*); extern int fprintf(void*,const char*,...); extern void *stderr;
extern int mkdir(const char*,u32); extern char *getenv(const char*); extern int chmod(const char*,u32);
extern void *memcpy(void*,const void*,size_t); extern void *memset(void*,int,size_t); extern size_t strlen(const char*);
extern int strcmp(const char*,const char*); extern int strncmp(const char*,const char*,size_t); extern int snprintf(char*,size_t,const char*,...);
extern ssize_t recvmsg(int,void*,int); extern int usleep(u32);
extern int open(const char*,int,...); extern int atoi(const char*); extern int ioctl(int,unsigned long,...); extern int clock_gettime(int,void*); extern long strtol(const char*,char**,int);

#define MAXC 8
#define MAXO 4096
enum { T_NONE, T_DISPLAY, T_REGISTRY, T_CALLBACK, T_COMPOSITOR, T_SURFACE, T_REGION, T_OUTPUT, T_SEAT, T_IVIAPP, T_IVISURF,
       T_CTRL, T_CLAYER, T_CSURF, T_CSCREEN, T_POINTER, T_KEYBOARD };
static const char *tn[] = {"none","display","registry","callback","compositor","surface","region","output","seat","ivi_application","ivi_surface","ivi_controller","clayer","csurface","cscreen","pointer","keyboard"};
typedef struct { int fd; u8 type[MAXO]; u32 frame_cb[64]; int nframe; u8 inbuf[65536]; int inlen; int ctrl_id; u32 ptr_id, surf_id, kbd_id; int entered, kentered; } Client;
static Client cl[MAXC];
static int W = 1920, H = 1080;

static void put(u8 **p, u32 v) { memcpy(*p, &v, 4); *p += 4; }
static void putstr(u8 **p, const char *s) { u32 l = strlen(s) + 1; put(p, l); memcpy(*p, s, l); u32 pad = (4 - l % 4) % 4; memset(*p + l, 0, pad); *p += l + pad; }
static void send_ev(Client *c, u32 obj, u32 op, const u8 *args, u32 alen) {
  u8 b[512]; u8 *p = b; put(&p, obj); put(&p, ((alen + 8) << 16) | op); memcpy(p, args, alen); p += alen;
  { static int ne; if (c == cl + 1 && ne++ < 150) fprintf(stderr, "[wl] ev c1 obj %u op %u len %u\n", obj, op, alen); }
  ssize_t wr = write(c->fd, b, p - b); if (wr != p - b) fprintf(stderr, "[wl] write c%d falhou %ld\n", (int)(c - cl), (long)wr);
}
static void ev_u(Client *c, u32 obj, u32 op, u32 a) { send_ev(c, obj, op, (u8*)&a, 4); }
static void delete_id(Client *c, u32 id) { ev_u(c, 1, 1, id); c->type[id] = T_NONE; }
static void send_global(Client *c, u32 reg, u32 name, const char *iface, u32 ver) {
  u8 a[256]; u8 *p = a; put(&p, name); putstr(&p, iface); put(&p, ver); send_ev(c, reg, 0, a, p - a);
}
static void output_events(Client *c, u32 id, u32 ver) {
  u8 a[256]; u8 *p = a; put(&p, 0); put(&p, 0); put(&p, 527); put(&p, 297); put(&p, 0); putstr(&p, "IDEmu"); putstr(&p, "virtual"); put(&p, 0); send_ev(c, id, 0, a, p - a);
  p = a; put(&p, 3); put(&p, W); put(&p, H); put(&p, 60000); send_ev(c, id, 1, a, p - a);
  if (ver >= 2) { ev_u(c, id, 3, 1); send_ev(c, id, 2, 0, 0); }
}
static u32 rd(const u8 **p) { u32 v; memcpy(&v, *p, 4); *p += 4; return v; }
static const char *rdstr(const u8 **p, u32 *len) { u32 l = rd(p); const char *s = (const char *)*p; *p += (l + 3) & ~3u; *len = l; return s; }
static int g_next_srv = 0xff000000;

static void handle(Client *c, u32 obj, u32 op, const u8 *a, u32 alen) {
  int t = obj < MAXO ? c->type[obj] : 0; const u8 *p = a; u32 id;
  { static int nl; if (nl++ < 400) fprintf(stderr, "[wl] req c%d obj %u (%s) op %u len %u\n", (int)(c - cl), obj, t < 17 ? tn[t] : "?", op, alen); }
  switch (t) {
  case T_DISPLAY:
    if (op == 0) { id = rd(&p); c->type[id] = T_CALLBACK; ev_u(c, id, 0, 1); delete_id(c, id); }
    else if (op == 1) { id = rd(&p); c->type[id] = T_REGISTRY;
      send_global(c, id, 1, "wl_compositor", 4); send_global(c, id, 2, "wl_output", 2); send_global(c, id, 3, "wl_seat", 4);
      send_global(c, id, 4, "ivi_application", 1); send_global(c, id, 5, "ivi_controller", 1); }
    break;
  case T_REGISTRY:
    if (op == 0) { u32 name = rd(&p), l; const char *s = rdstr(&p, &l); u32 ver = rd(&p); id = rd(&p);
      static const int map[] = {0, T_COMPOSITOR, T_OUTPUT, T_SEAT, T_IVIAPP, T_CTRL};
      c->type[id] = name < 6 ? map[name] : 0;
      fprintf(stderr, "[wl] bind %s v%u -> id %u\n", s, ver, id);
      if (name == 2) output_events(c, id, ver);
      if (name == 3) ev_u(c, id, 0, 3);                               // capabilities: pointer|keyboard
      if (name == 5) {                                                // ivi_controller: anuncia a tela 0
        c->ctrl_id = id; u8 b[16]; u8 *q = b; put(&q, 0); put(&q, g_next_srv); send_ev(c, id, 0, b, q - b); c->type[g_next_srv & (MAXO - 1)] = T_CSCREEN; g_next_srv++; }
    } break;
  case T_COMPOSITOR:
    if (op == 0) { id = rd(&p); c->type[id] = T_SURFACE; } else if (op == 1) { id = rd(&p); c->type[id] = T_REGION; }
    break;
  case T_SURFACE:
    { static int nop[16]; if (op < 16 && (nop[op]++ < 5 || nop[op] % 500 == 0)) fprintf(stderr, "[wl] surface %u op %u (#%d)\n", obj, op, nop[op]); }
    if (op == 3) { id = rd(&p); c->type[id] = T_CALLBACK; if (c->nframe < 64) c->frame_cb[c->nframe++] = id; }
    else if (op == 0) delete_id(c, obj);
    break;
  case T_REGION: if (op == 0) delete_id(c, obj); break;
  case T_SEAT:
    if (op == 0) { id = rd(&p); c->type[id] = T_POINTER; c->ptr_id = id; c->entered = 0; } else if (op == 1) { id = rd(&p); c->type[id] = T_KEYBOARD; c->kbd_id = id; c->kentered = 0; }
    break;
  case T_IVIAPP:
    if (op == 0) { u32 sid = rd(&p); u32 surf = rd(&p); id = rd(&p); c->type[id] = T_IVISURF;
      fprintf(stderr, "[wl] ivi surface_create ivi_id=%u wl_surface=%u -> %u\n", sid, surf, id); c->surf_id = surf; c->entered = 0;
      u8 b[8]; u8 *q = b; put(&q, W); put(&q, H); send_ev(c, id, 0, b, q - b);             // configure(w,h)
      if (c->ctrl_id) ev_u(c, c->ctrl_id, 2, sid); }                                          // ivi_controller.surface(id)
    break;
  case T_IVISURF: if (op == 0) delete_id(c, obj); break;
  case T_CTRL:
    if (op == 1) { u32 lid = rd(&p); i32 w = rd(&p), h = rd(&p); id = rd(&p); c->type[id] = T_CLAYER; fprintf(stderr, "[wl] layer_create %u %dx%d -> %u\n", lid, w, h, id); }
    else if (op == 2) { u32 sid = rd(&p); id = rd(&p); c->type[id] = T_CSURF; fprintf(stderr, "[wl] ctrl surface_create %u -> %u\n", sid, id); }
    break;
  default: break;
  }
  (void)alen;
}


// ---- entrada do Mac: linhas de texto em /dev/ttyS0 (a porta serial do QEMU ligada ao IDEmu) viram eventos wl_pointer para o HMI.
//   "d X Y" toque desce, "m X Y" move, "u" sobe. X,Y em pixels da tela (1920x1080). O RAMSES só trata ponteiro (não há wl_touch).
static u32 now_ms(void) { struct { long s, ns; } t; clock_gettime(1, &t); return (u32)(t.s * 1000 + t.ns / 1000000); }
static u32 g_serial = 1; static int g_px, g_py, g_down;
static void ptr_send(u32 op, const u8 *a, u32 alen) {
  for (int i = 0; i < MAXC; i++) if (cl[i].fd >= 0 && cl[i].ptr_id && cl[i].surf_id) send_ev(&cl[i], cl[i].ptr_id, op, a, alen);
}
static void ptr_enter(Client *c) {
  u8 a[16]; u8 *q = a; put(&q, g_serial++); put(&q, c->surf_id); put(&q, g_px * 256); put(&q, g_py * 256); send_ev(c, c->ptr_id, 0, a, q - a); c->entered = 1;
}
static void ptr_motion(void) {
  for (int i = 0; i < MAXC; i++) if (cl[i].fd >= 0 && cl[i].ptr_id && cl[i].surf_id && !cl[i].entered) ptr_enter(&cl[i]);
  u8 a[12]; u8 *q = a; put(&q, now_ms()); put(&q, g_px * 256); put(&q, g_py * 256); ptr_send(2, a, q - a);
}
static void ptr_button(int down) {
  u8 a[16]; u8 *q = a; put(&q, g_serial++); put(&q, now_ms()); put(&q, 0x110); put(&q, down ? 1 : 0); ptr_send(3, a, q - a);
}
static void key_send(int code, int down) {                                      // wl_keyboard: enter (1ª vez), modifiers e key (código de tecla do Linux)
  for (int i = 0; i < MAXC; i++) if (cl[i].fd >= 0 && cl[i].kbd_id && cl[i].surf_id) {
    Client *c = &cl[i]; u8 a[24]; u8 *q;
    if (!c->kentered) { q = a; put(&q, g_serial++); put(&q, c->surf_id); put(&q, 0); send_ev(c, c->kbd_id, 1, a, q - a);
      q = a; put(&q, g_serial++); put(&q, 0); put(&q, 0); put(&q, 0); put(&q, 0); send_ev(c, c->kbd_id, 4, a, q - a); c->kentered = 1; }
    q = a; put(&q, g_serial++); put(&q, now_ms()); put(&q, code); put(&q, down ? 1 : 0); send_ev(c, c->kbd_id, 3, a, q - a);
  }
}
// "c DESLOCAMENTO HEX" grava bytes em /run/coding.bin (o Mac manda a codificação do iDrive 7 pela mesma serial do toque); "c end" cria /run/coding.ok
static int hexv(int c) { return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1; }
static void coding_line(char *l) {
  extern long lseek(int, long, int); extern int creat(const char*, u32);
  while (*l == ' ') l++;
  if (!strncmp(l, "end", 3)) { int f = creat("/run/coding.ok", 0644); if (f >= 0) close(f); return; }
  char *e; long off = strtol(l, &e, 16); static int cf = -1; if (cf < 0) cf = open("/run/coding.bin", 0x241 /* O_WRONLY|O_CREAT|O_TRUNC */, 0644); if (cf < 0) return;
  while (*e == ' ') e++;
  u8 b[96]; int n = 0; while (n < 96 && hexv(e[0]) >= 0 && hexv(e[1]) >= 0) { b[n++] = (u8)(hexv(e[0]) * 16 + hexv(e[1])); e += 2; }
  lseek(cf, off, 0); if (n) write(cf, b, n);
}
static void input_line(char *l) {
  char *e; int x, y;
  if (l[0] == 'c') { coding_line(l + 1); return; }
  if (l[0] == 'k') { char *e; int code = (int)strtol(l + 1, &e, 10); int v = (int)strtol(e, 0, 10); key_send(code, v); return; }
  if (l[0] == 'u') { if (g_down) { g_down = 0; ptr_button(0); } return; }
  if (l[0] != 'd' && l[0] != 'm') return;
  x = (int)strtol(l + 1, &e, 10); y = (int)strtol(e, 0, 10); g_px = x < 0 ? 0 : x >= W ? W - 1 : x; g_py = y < 0 ? 0 : y >= H ? H - 1 : y;
  ptr_motion();
  if (l[0] == 'd' && !g_down) { g_down = 1; ptr_button(1); }
}
static int input_open(void) {
  const char *dev = getenv("IDEMU_INPUT"); if (!dev) dev = "/dev/ttyS0";
  int f = open(dev, 0x902 /* O_RDWR|O_NOCTTY|O_NONBLOCK */);
  if (f < 0) { fprintf(stderr, "[wl] entrada: nao abriu %s\n", dev); return -1; }
  u32 t[16]; memset(t, 0, sizeof t);
  if (ioctl(f, 0x5401, t) == 0) { t[0] = 0; t[1] = 0; t[3] = 0; t[2] = (t[2] & ~0x30u) | 0x30 | 0x80 | 0x800; ioctl(f, 0x5402, t); }   // TCGETS/TCSETS: modo cru
  fprintf(stderr, "[wl] entrada em %s\n", dev); return f;
}

int main(void) {
  { const char *sz = getenv("IDEMU_WL_SIZE"); if (sz) { int w = atoi(sz); const char *x = sz; while (*x && *x != 'x') x++; int h = *x ? atoi(x + 1) : 0; if (w > 0 && h > 0) { W = w; H = h; } } }   // ex. 1920x720 (HU_HMI)
  const char *dir = getenv("XDG_RUNTIME_DIR"); char path[256]; if (!dir) dir = "/run/wayland";
  mkdir(dir, 0755); snprintf(path, sizeof path, "%s/wayland-0", dir); unlink(path);
  int s = socket(1, 1, 0); struct { unsigned short fam; char p[108]; } sa; memset(&sa, 0, sizeof sa); sa.fam = 1; memcpy(sa.p, path, strlen(path));
  if (bind(s, &sa, sizeof sa) || listen(s, 4)) { fprintf(stderr, "[wl] bind falhou\n"); return 1; }
  chmod(path, 0777); fprintf(stderr, "[wl] ouvindo em %s\n", path);
  for (int i = 0; i < MAXC; i++) cl[i].fd = -1;
  int inp = input_open(); char ibuf[256]; int ilen = 0;
  { extern int creat(const char*, u32); int rf = creat("/run/wl.ready", 0644); if (rf >= 0) close(rf); }      // o init espera por isto (entrada pronta) antes de seguir
  for (;;) {
    struct { int fd; short ev, rev; } pf[MAXC + 2]; int n = 0; pf[n].fd = s; pf[n].ev = 1; pf[n].rev = 0; n++;
    int ipos = -1; if (inp >= 0) { ipos = n; pf[n].fd = inp; pf[n].ev = 1; pf[n].rev = 0; n++; }
    for (int i = 0; i < MAXC; i++) if (cl[i].fd >= 0) { pf[n].fd = cl[i].fd; pf[n].ev = 1; pf[n].rev = 0; n++; }
    int r = poll(pf, n, 16);
    // frame callbacks: responde a cada ciclo (~60 Hz)
    for (int i = 0; i < MAXC; i++) if (cl[i].fd >= 0) for (int k = 0; k < cl[i].nframe; k++) { ev_u(&cl[i], cl[i].frame_cb[k], 0, 1000); delete_id(&cl[i], cl[i].frame_cb[k]); }
    for (int i = 0; i < MAXC; i++) cl[i].nframe = 0;
    if (r <= 0) continue;
    if (ipos >= 0 && (pf[ipos].rev & 1)) {
      ssize_t m = read(inp, ibuf + ilen, sizeof ibuf - 1 - ilen); if (m > 0) ilen += m; ibuf[ilen] = 0;
      for (;;) { int e = -1; for (int j = 0; j < ilen; j++) if (ibuf[j] == '\n') { e = j; break; }
        if (e < 0) { if (ilen > 200) ilen = 0; break; } ibuf[e] = 0; input_line(ibuf); memcpy(ibuf, ibuf + e + 1, ilen - e - 1); ilen -= e + 1; }
    }
    if (pf[0].rev & 1) { int f = accept(s, 0, 0); int i; for (i = 0; i < MAXC && cl[i].fd >= 0; i++); if (i == MAXC) close(f); else { memset(&cl[i], 0, sizeof cl[i]); cl[i].fd = f; cl[i].type[1] = T_DISPLAY; fprintf(stderr, "[wl] cliente %d\n", i); } }
    int k = ipos >= 0 ? 2 : 1;
    for (int i = 0; i < MAXC; i++) if (cl[i].fd >= 0) {
      if (k < n && (pf[k].rev & 0x19)) {
        // recvmsg para consumir descritores (SCM_RIGHTS) se houver
        u8 cm[256]; struct { void *name; u32 nl; void *iov; size_t il; void *ctl; size_t cl_; int fl; } mh; struct { void *b; size_t l; } iv = { cl[i].inbuf + cl[i].inlen, sizeof cl[i].inbuf - cl[i].inlen };
        memset(&mh, 0, sizeof mh); mh.iov = &iv; mh.il = 1; mh.ctl = cm; mh.cl_ = sizeof cm;
        ssize_t m = recvmsg(cl[i].fd, &mh, 0);
        if (m <= 0) { close(cl[i].fd); cl[i].fd = -1; fprintf(stderr, "[wl] cliente %d saiu\n", i); k++; continue; }
        { static int nr; if (i == 1 && nr++ < 60) fprintf(stderr, "[wl] recv c1 %ld bytes (inlen %d)\n", (long)m, cl[i].inlen); }
        cl[i].inlen += m;
        u8 *b = cl[i].inbuf; int off = 0;
        while (cl[i].inlen - off >= 8) { u32 obj, w; memcpy(&obj, b + off, 4); memcpy(&w, b + off + 4, 4); u32 sz = w >> 16, op = w & 0xffff;
          if (sz < 8 || sz > 4096) { off = cl[i].inlen; break; } if ((u32)(cl[i].inlen - off) < sz) break;
          handle(&cl[i], obj, op, b + off + 8, sz - 8); off += sz; }
        memcpy(b, b + off, cl[i].inlen - off); cl[i].inlen -= off;
      }
      k++;
    }
  }
}

__asm__(".globl _start\n_start:\n xor %ebp,%ebp\n and $-16,%rsp\n call main\n mov %eax,%edi\n mov $60,%eax\n syscall\n");

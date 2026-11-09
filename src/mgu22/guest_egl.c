// libEGL.so.1 + GLES do IDEmu (iDrive 8). O Ramses do firmware chama estas funções; cada chamada vira mensagem
// no canal (chan.h) e é executada no host por mguhost, sobre o ANGLE. Sem headers: declara só o que usa.
#include "chan.h"
#include "gen_ops.h"
typedef unsigned long ul; typedef long sl; typedef unsigned u32;
extern void *mmap(void *, ul, int, int, int, long); extern int munmap(void *, ul);
extern int open(const char *, int, ...); extern int close(int); extern long pread(int, void *, ul, long);
extern ul strlen(const char *); extern void *memcpy(void *, const void *, ul); extern void *memset(void *, int, ul); extern int strcmp(const char *, const char *);
extern char *strstr(const char *, const char *); extern char *strdup(const char *);
extern void *malloc(ul); extern void free(void *); extern long sysconf(int); extern int getpid(void); extern long syscall(long, ...);
extern int sched_yield(void); extern int nanosleep(const void *, void *); extern int fprintf(void *, const char *, ...); extern void *stderr;
extern int fflush(void *); extern int clock_gettime(int, void *);
extern int wl_proxy_get_version(void *); extern void *wl_proxy_marshal_flags(void *, u32, const void *, u32, u32, ...); extern int wl_display_flush(void *);
#define LOG(...) do { fprintf(stderr, "[idemu-egl] " __VA_ARGS__); fflush(stderr); } while (0)
#include "chan_guest.h"
static __thread Ch *tls_ch;
static inline Ch *cur(void) { if (!tls_ch) tls_ch = ch_open(0); return tls_ch; }
static void put(Ch *c, const void *p, ul n) {
  const char *s = p;
  while (n) {
    ul rd = acq(&c->h->a_rd); ul fr = CH_RING_A - (c->awr - rd);
    if (!fr) { rel(&c->h->a_wr, c->awr); int k = 0; while (acq(&c->h->a_rd) == rd) wait_tick(&k); continue; }
    ul pos = c->awr % CH_RING_A, ch = CH_RING_A - pos; if (ch > fr) ch = fr; if (ch > n) ch = n;
    memcpy(c->a + pos, s, ch); s += ch; n -= ch; c->awr += ch;
  }
}
static inline void pub(Ch *c) { rel(&c->h->a_wr, c->awr); }
static void msg(Ch *c, u32 op, u32 n, const ul *v) { u32 hd[2] = { op, n }; put(c, hd, 8); if (n) put(c, v, n * 8ul); }
static inline ul fbits(float f) { union { float f; u32 u; } x; x.f = f; return x.u; }
#include "gen_guest.inc"
#define V(...) ul v[] = { __VA_ARGS__ }
static inline ul I(int x) { return (ul)(long)x; }
// --- formatos de pixel
static int px_size(u32 fmt, u32 type) {
  int ch = 4, sz = 1;
  switch (fmt) {
    case 0x1903: case 0x8D94: case 0x1906: case 0x1909: case 0x1902: case 0x1901: ch = 1; break;
    case 0x8227: case 0x8228: case 0x190A: case 0x84F9: ch = 2; break;
    case 0x1907: case 0x8D98: ch = 3; break;
    default: ch = 4;
  }
  switch (type) {
    case 0x1400: case 0x1401: sz = 1; break;
    case 0x1402: case 0x1403: case 0x140B: case 0x8D61: sz = 2; break;
    case 0x1404: case 0x1405: case 0x1406: sz = 4; break;
    case 0x8363: case 0x8033: case 0x8034: return 2;
    case 0x8368: case 0x8C3B: case 0x8C3E: case 0x84FA: return 4;
    case 0x8DAD: return 8;
  }
  return ch * sz;
}
static ul img_size(Ch *c, int w, int h, int d, u32 fmt, u32 type) {
  if (w <= 0 || h <= 0 || d <= 0) return 0;
  int al = c->unpack_align ? c->unpack_align : 4;
  ul b = px_size(fmt, type), row = (c->unpack_row > 0 ? c->unpack_row : w) * b; row = (row + al - 1) / al * al;
  ul ih = c->unpack_img > 0 ? c->unpack_img : h;
  // os SKIP deslocam o começo: o host aplica os mesmos valores, então o pacote precisa incluir esse trecho
  return (c->unpack_skip_img + d - 1) * ih * row + (c->unpack_skip_rows + h - 1) * row + (c->unpack_skip_px + w) * b;
}
void glPixelStorei(u32 p, int v0) {
  Ch *c = cur();
  if (p == 0x0CF5) c->unpack_align = v0; else if (p == 0x0CF2) c->unpack_row = v0; else if (p == 0x806E) c->unpack_img = v0;
  else if (p == 0x0CF4) c->unpack_skip_px = v0; else if (p == 0x0CF3) c->unpack_skip_rows = v0; else if (p == 0x806D) c->unpack_skip_img = v0;
  else if (p == 0x0D05) c->pack_align = v0; else if (p == 0x0D02) c->pack_row = v0;
  V(p, I(v0)); msg(c, OP_PixelStorei, 2, v); pub(c);
}
void glBufferData(u32 t, long size, const void *data, u32 usage) {
  Ch *c = cur(); V(t, size, data != 0, usage); msg(c, OP_BufferData, 4, v); if (data) put(c, data, size); pub(c);
}
void glTexImage2D(u32 t, int l, int ifmt, int w, int h, int b, u32 f, u32 ty, const void *px) {
  Ch *c = cur(); ul n = px ? img_size(c, w, h, 1, f, ty) : 0;
  V(t, I(l), I(ifmt), I(w), I(h), I(b), f, ty, n); msg(c, OP_TexImage2D, 9, v); if (n) put(c, px, n); pub(c);
}
void glTexSubImage2D(u32 t, int l, int x, int y, int w, int h, u32 f, u32 ty, const void *px) {
  Ch *c = cur(); ul n = img_size(c, w, h, 1, f, ty);
  V(t, I(l), I(x), I(y), I(w), I(h), f, ty, n); msg(c, OP_TexSubImage2D, 9, v); if (n) put(c, px, n); pub(c);
}
void glTexSubImage3D(u32 t, int l, int x, int y, int z, int w, int h, int d, u32 f, u32 ty, const void *px) {
  Ch *c = cur(); ul n = img_size(c, w, h, d, f, ty);
  V(t, I(l), I(x), I(y), I(z), I(w), I(h), I(d), f, ty, n); msg(c, OP_TexSubImage3D, 11, v); if (n) put(c, px, n); pub(c);
}
void glCompressedTexSubImage2D(u32 t, int l, int x, int y, int w, int h, u32 f, int size, const void *d) {
  Ch *c = cur(); V(t, I(l), I(x), I(y), I(w), I(h), f, I(size)); msg(c, OP_CompressedTexSubImage2D, 8, v); put(c, d, size); pub(c);
}
void glCompressedTexSubImage3D(u32 t, int l, int x, int y, int z, int w, int h, int dd, u32 f, int size, const void *d) {
  Ch *c = cur(); V(t, I(l), I(x), I(y), I(z), I(w), I(h), I(dd), f, I(size)); msg(c, OP_CompressedTexSubImage3D, 10, v); put(c, d, size); pub(c);
}
#define GENDEL(N) \
  void glGen##N(int n, u32 *o) { Ch *c = cur(); V(I(n)); msg(c, OP_Gen##N, 1, v); pub(c); get(c, o, n * 4ul); } \
  void glDelete##N(int n, const u32 *o) { Ch *c = cur(); V(I(n)); msg(c, OP_Delete##N, 1, v); put(c, o, n * 4ul); pub(c); }
GENDEL(Buffers) GENDEL(Framebuffers) GENDEL(Renderbuffers) GENDEL(Samplers) GENDEL(Textures) GENDEL(VertexArrays)
void glDrawBuffers(int n, const u32 *b) { Ch *c = cur(); V(I(n)); msg(c, OP_DrawBuffers, 1, v); put(c, b, n * 4ul); pub(c); }
void glInvalidateFramebuffer(u32 t, int n, const u32 *b) { Ch *c = cur(); V(t, I(n)); msg(c, OP_InvalidateFramebuffer, 2, v); put(c, b, n * 4ul); pub(c); }
void glGetIntegerv(u32 p, int *o) {
  Ch *c = cur(); V(p); msg(c, OP_GetIntegerv, 1, v); pub(c); ul n; get(c, &n, 8); get(c, o, n * 4);
}
void glGetInternalformativ(u32 t, u32 f, u32 p, int cnt, int *o) {
  Ch *c = cur(); V(t, f, p, I(cnt)); msg(c, OP_GetInternalformativ, 4, v); pub(c); get(c, o, cnt * 4ul);
}
void glGetProgramiv(u32 pr, u32 p, int *o) { Ch *c = cur(); V(pr, p); msg(c, OP_GetProgramiv, 2, v); pub(c); get(c, o, 4); }
void glGetShaderiv(u32 s, u32 p, int *o) { Ch *c = cur(); V(s, p); msg(c, OP_GetShaderiv, 2, v); pub(c); get(c, o, 4); }
static void getlog(Ch *c, int bs, int *len, char *buf) {
  ul n; get(c, &n, 8); static char skip[256]; ul m = n;
  if (buf && bs > 0) { ul k = n < (ul)bs ? n : (ul)bs; get(c, buf, k); m = n - k; }
  while (m) { ul k = m > 256 ? 256 : m; get(c, skip, k); m -= k; }
  if (len) *len = n ? (int)(n - 1) : 0;
}
void glGetProgramInfoLog(u32 p, int bs, int *len, char *b) { Ch *c = cur(); V(p); msg(c, OP_GetProgramInfoLog, 1, v); pub(c); getlog(c, bs, len, b); }
void glGetShaderInfoLog(u32 s, int bs, int *len, char *b) { Ch *c = cur(); V(s); msg(c, OP_GetShaderInfoLog, 1, v); pub(c); getlog(c, bs, len, b); }
void glGetProgramBinary(u32 p, int bs, int *len, u32 *fmt, void *bin) {
  Ch *c = cur(); V(p, I(bs)); msg(c, OP_GetProgramBinary, 2, v); pub(c);
  ul n, f; get(c, &n, 8); get(c, &f, 8); if (len) *len = (int)n; if (fmt) *fmt = (u32)f; if (n) get(c, bin, n);
}
void glProgramBinary(u32 p, u32 f, const void *b, int n) { Ch *c = cur(); V(p, f, I(n)); msg(c, OP_ProgramBinary, 3, v); put(c, b, n); pub(c); }
void glShaderSource(u32 s, int cnt, const char *const *str, const int *lens) {
  Ch *c = cur(); ul tot = 0; for (int i = 0; i < cnt; i++) tot += lens && lens[i] >= 0 ? (ul)lens[i] : strlen(str[i]);
  V(s, tot); msg(c, OP_ShaderSource, 2, v);
  for (int i = 0; i < cnt; i++) put(c, str[i], lens && lens[i] >= 0 ? (ul)lens[i] : strlen(str[i]));
  pub(c);
}
void glReadPixels(int x, int y, int w, int h, u32 f, u32 t, void *px) {
  Ch *c = cur(); V(I(x), I(y), I(w), I(h), f, t); msg(c, OP_ReadPixels, 6, v); pub(c);
  ul n; get(c, &n, 8); if (n) get(c, px, n);
  (void)img_size;
}
#define UV(N, T, SZ) void glUniform##N(int l, int cnt, const T *d) { Ch *c = cur(); V(I(l), I(cnt)); msg(c, OP_Uniform##N, 2, v); put(c, d, cnt * (ul)(SZ)); pub(c); }
UV(1fv, float, 4) UV(2fv, float, 8) UV(3fv, float, 12) UV(4fv, float, 16) UV(1iv, int, 4) UV(2iv, int, 8) UV(3iv, int, 12) UV(4iv, int, 16)
#define UM(N, SZ) void glUniformMatrix##N(int l, int cnt, unsigned char tr, const float *d) { Ch *c = cur(); V(I(l), I(cnt), tr); msg(c, OP_UniformMatrix##N, 3, v); put(c, d, cnt * (ul)(SZ)); pub(c); }
UM(2fv, 16) UM(3fv, 36) UM(4fv, 64)
// --- strings: cacheadas; extensões que o host tem mas o guest não pode usar saem da lista
static struct { u32 n; const char *s; } sc[8]; static int nsc;
static const char *fetchstr(Ch *c) { ul n; get(c, &n, 8); char *s = malloc(n + 1); if (n) get(c, s, n); s[n] = 0; return s; }
const unsigned char *glGetString(u32 name) {
  for (int i = 0; i < nsc; i++) if (sc[i].n == name) return (const unsigned char *)sc[i].s;
  Ch *c = cur(); V(name); msg(c, OP_GetString, 1, v); pub(c); const char *s = fetchstr(c);
  if (nsc < 8) { sc[nsc].n = name; sc[nsc].s = s; nsc++; }
  return (const unsigned char *)s;
}
const unsigned char *glGetStringi(u32 name, u32 i) {
  Ch *c = cur(); V(name, i); msg(c, OP_GetStringi, 2, v); pub(c); const char *s = fetchstr(c);
  if (!strcmp(s, "GL_KHR_debug")) return (const unsigned char *)"GL_IDEMU_none";
  return (const unsigned char *)s;
}
// --- EGL: tudo no host; o guest só guarda o wl_display e a wl_surface para o commit
#define EGL_OK 0x3000
static __thread int egl_err = EGL_OK;
static void *g_wl;
typedef struct Sf { u32 id; void *win; } Sf;
static volatile u32 next_id = 1;
static u32 newid(void) { return __atomic_fetch_add(&next_id, 1, __ATOMIC_RELAXED); }
int eglGetError(void) { int e = egl_err; egl_err = EGL_OK; return e; }
void *eglGetDisplay(void *native) { g_wl = native; return (void *)1; }
int eglInitialize(void *d, int *maj, int *min) { if (maj) *maj = 1; if (min) *min = 5; return 1; }
int eglTerminate(void *d) { return 1; }
int eglBindAPI(u32 a) { return a == 0x30A0; }
int eglSwapInterval(void *d, int i) { return 1; }
const char *eglQueryString(void *d, int name) {
  switch (name) {
    case 0x3053: return "IDEmu"; case 0x3054: return "1.5 IDEmu";
    case 0x3055: return "EGL_KHR_surfaceless_context EGL_KHR_create_context"; case 0x308D: return "OpenGL_ES";
  }
  egl_err = 0x300C; return 0;
}
int eglChooseConfig(void *d, const int *attr, void **cfg, int size, int *num) {
  Ch *c = cur(); int n = 0; if (attr) while (attr[n] != 0x3038) n += 2;
  V(I(n), I(size)); msg(c, OP_EGLChooseConfig, 2, v); if (n) put(c, attr, n * 4ul); pub(c);
  ul cnt; get(c, &cnt, 8);
  for (ul i = 0; i < cnt; i++) { ul id; get(c, &id, 8); if (cfg && (int)i < size) cfg[i] = (void *)id; }
  if (num) *num = (int)cnt;
  return 1;
}
int eglGetConfigAttrib(void *d, void *cfg, int a, int *val) {
  Ch *c = cur(); V((ul)cfg, I(a)); msg(c, OP_EGLGetConfigAttrib, 2, v); pub(c); ul r[2]; get(c, r, 16);
  if (val) *val = (int)r[1]; if (!r[0]) egl_err = 0x3004; return (int)r[0];
}
void *eglCreateContext(void *d, void *cfg, void *share, const int *attr) {
  Ch *c = cur(); int n = 0; if (attr) while (attr[n] != 0x3038) n += 2;
  V((ul)cfg, (ul)share, I(n)); msg(c, OP_EGLCreateContext, 3, v); if (n) put(c, attr, n * 4ul); pub(c);
  ul id; get(c, &id, 8); if (!id) egl_err = 0x3009;
  return (void *)id;
}
int eglDestroyContext(void *d, void *ctx) { Ch *c = cur(); V((ul)ctx); msg(c, OP_EGLDestroyContext, 1, v); pub(c); return 1; }
void *eglCreateWindowSurface(void *d, void *cfg, void *win, const int *attr) {
  Ch *c = cur(); int w = *(int *)((char *)win + 8), h = *(int *)((char *)win + 12);
  Sf *s = malloc(sizeof(Sf)); s->id = newid(); s->win = win;
  V(s->id, (ul)cfg, I(w), I(h)); msg(c, OP_EGLCreateSurface, 4, v); pub(c);
  ul ok; get(c, &ok, 8); if (!ok) { egl_err = 0x3009; return 0; }
  LOG("superficie %u %dx%d\n", s->id, w, h);
  return s;
}
int eglDestroySurface(void *d, void *sf) { Sf *s = sf; Ch *c = cur(); V(s->id); msg(c, OP_EGLDestroySurface, 1, v); pub(c); return 1; }
int eglMakeCurrent(void *d, void *dr, void *rd, void *ctx) {
  Ch *c = cur(); Sf *sd = dr, *sr = rd;
  V(sd ? sd->id : 0, sr ? sr->id : 0, (ul)ctx); msg(c, OP_EGLMakeCurrent, 3, v); pub(c);
  ul ok; get(c, &ok, 8); if (!ok) egl_err = 0x3006;
  return (int)ok;
}
int eglSwapBuffers(void *d, void *sf) {
  Sf *s = sf; Ch *c = cur(); V(s->id); msg(c, OP_EGLSwap, 1, v); pub(c); ul ok; get(c, &ok, 8);
  void *surf = *(void **)((char *)s->win + 56);
  if (surf) { wl_proxy_marshal_flags(surf, 6, 0, wl_proxy_get_version(surf), 0); if (g_wl) wl_display_flush(g_wl); }
  return 1;
}
typedef void (*fn)(void);
fn eglGetProcAddress(const char *name) {
#define X(n) if (!strcmp(name, #n)) return (fn)n;
#include "gen_names.inc"
#undef X
  LOG("eglGetProcAddress(%s) sem implementacao\n", name);
  return 0;
}

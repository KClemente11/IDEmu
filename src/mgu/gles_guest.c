// libGLESv2.so.2 / libEGL.so.1 do guest (iDrive 7): serializa as chamadas EGL/GLES3 do RAMSES para o host por /dev/ttyS1.
// As funções só com argumentos escalares vêm de gl_stubs.inc (gen_gl.py); as demais estão aqui.
#include "proto.h"
#include "gl_ids.h"
typedef unsigned int u32; typedef unsigned char u8; typedef unsigned long u64; typedef long i64; typedef unsigned long size_t; typedef long ssize_t;
extern int open(const char*, int, ...); extern ssize_t read(int, void*, size_t); extern ssize_t write(int, const void*, size_t);
extern int tcgetattr(int, void*); extern int tcsetattr(int, int, const void*); extern void cfmakeraw(void*);
extern void *memcpy(void*, const void*, size_t); extern size_t strlen(const char*); extern void *dlsym(void*, const char*);
extern int usleep(u32); extern void *malloc(size_t); extern void free(void*);
#define A_F(x) ({ union { float f; u32 u; } _u; _u.f = (x); (unsigned long)_u.u; })
#define EXPORT __attribute__((visibility("default")))
typedef unsigned int GLenum, GLuint, GLbitfield; typedef int GLint, GLsizei; typedef unsigned char GLboolean; typedef float GLfloat; typedef long GLsizeiptr, GLintptr; typedef char GLchar;

static int fd = -1; static u8 ob[1 << 18]; static u32 ol; static u32 next_id = 1; static u32 unpack_align = 4, unpack_rowlen = 0;
// ---- transporte: anel em memória compartilhada (preferido) ou a serial /dev/ttyS1 ----
extern void *mmap(void*, size_t, int, int, int, long); extern int snprintf(char*, size_t, const char*, ...); extern int sched_yield(void);
static struct shm_hdr *H; static u8 *gdat, *hdat; static u64 gt, hh, last_pub;      // cópias locais de g_tail e h_head
#define PAUSE() __asm__ volatile("pause" ::: "memory")
static int shm_find(void) {
  char p[96], b[16];
  for (int s = 0; s < 32; s++) for (int f = 0; f < 8; f++) {
    snprintf(p, sizeof p, "/sys/bus/pci/devices/0000:00:%02x.%x/vendor", s, f); int v = open(p, 0); if (v < 0) continue;
    int n = (int)read(v, b, 15); close(v); if (n < 6 || b[2] != '1' || b[3] != 'b' || b[4] != '3' || b[5] != '6') continue;
    snprintf(p, sizeof p, "/sys/bus/pci/devices/0000:00:%02x.%x/device", s, f); v = open(p, 0); if (v < 0) continue;
    n = (int)read(v, b, 15); close(v); if (n < 6 || b[2] != '1' || b[3] != 'd' || b[4] != '3' || b[5] != 'a') continue;
    snprintf(p, sizeof p, "/sys/bus/pci/devices/0000:00:%02x.%x/resource0", s, f); int r = open(p, 2 | 04000000 /*O_SYNC*/); if (r < 0) continue;
    void *m = mmap(0, SHM_SIZE, 3, 1, r, 0); close(r); if (m == (void*)-1L) continue;
    H = (struct shm_hdr*)m; gdat = (u8*)m + G_OFF; hdat = (u8*)m + H_OFF;
    gt = H->g_tail; hh = H->h_tail; H->h_head = hh; last_pub = gt;     // continua de onde o fluxo parou; o host descarta o que ficou pela metade (epoch)
    H->g_start = gt; __atomic_thread_fence(__ATOMIC_SEQ_CST); H->epoch++; H->magic = SHM_MAGIC; __atomic_thread_fence(__ATOMIC_SEQ_CST);
    return 1;
  }
  return 0;
}
static void io_init(void) {
  if (fd >= 0 || H) return;
  if (shm_find()) { fd = 0; return; }
  fd = open("/dev/ttyS1", 2); u8 t[128]; tcgetattr(fd, t); cfmakeraw(t); tcsetattr(fd, 0, t);
}
static void publish(void) { if (gt != last_pub) { __atomic_thread_fence(__ATOMIC_SEQ_CST); H->g_tail = gt; last_pub = gt; } }
static void flush(void) {
  io_init();
  if (H) { publish(); return; }
  u32 o = 0; while (o < ol) { ssize_t n = write(fd, ob + o, ol - o); if (n <= 0) { usleep(1000); continue; } o += n; } ol = 0;
}
static void raw(const void *p, u32 n) {
  if (!H && fd < 0) io_init();
  if (H) {
    const u8 *s = p;
    while (n) {
      u64 used = gt - H->g_head;
      if (used >= G_SIZE) {                         // anel cheio: publica o que há e espera o host consumir
        publish(); for (u32 i = 0; (gt - H->g_head) >= G_SIZE; i++) { if (i < 4000) PAUSE(); else sched_yield(); }
        continue;
      }
      u32 c = G_SIZE - (u32)used; if (c > n) c = n; u32 off = (u32)(gt & (G_SIZE - 1)), seg = G_SIZE - off; if (seg > c) seg = c;
      memcpy(gdat + off, s, seg); if (c > seg) memcpy(gdat, s + seg, c - seg);
      gt += c; s += c; n -= c;
    }
    if (gt - last_pub >= 65536) publish();
    return;
  }
  const u8 *s = p; while (n) { u32 c = sizeof ob - ol; if (c > n) c = n; memcpy(ob + ol, s, c); ol += c; s += c; n -= c; if (ol == sizeof ob) flush(); }
}
static void p32(u32 v) { raw(&v, 4); }
static void p64(u64 v) { raw(&v, 8); }
static void hdr(u32 op, u32 len) { p32(op); p32(len); }
static void rd(void *p, u32 n) {
  flush(); u8 *d = p;
  if (H) {
    while (n) {
      u64 av = H->h_tail - hh;
      if (!av) { for (u32 i = 0; !(H->h_tail - hh); i++) { if (i < 20000) PAUSE(); else sched_yield(); } continue; }
      __atomic_thread_fence(__ATOMIC_SEQ_CST);
      u32 c = av > n ? n : (u32)av, off = (u32)(hh & (H_SIZE - 1)), seg = H_SIZE - off; if (seg > c) seg = c;
      memcpy(d, hdat + off, seg); if (c > seg) memcpy(d + seg, hdat, c - seg);
      hh += c; d += c; n -= c; __atomic_thread_fence(__ATOMIC_SEQ_CST); H->h_head = hh;
    }
    return;
  }
  while (n) { ssize_t r = read(fd, d, n); if (r <= 0) { usleep(1000); continue; } d += r; n -= r; }
}
static u32 rd32(void) { u32 v; rd(&v, 4); return v; }

static void simple(u32 fn, int n, ...) {
  __builtin_va_list ap; __builtin_va_start(ap, n); hdr(OP_SIMPLE, 8 + 8 * n); p32(fn); p32(n);
  unsigned long a[12];
  for (int i = 0; i < n; i++) { a[i] = __builtin_va_arg(ap, unsigned long); p64(a[i]); }
  __builtin_va_end(ap);
  if (fn == F_PixelStorei) { if (a[0] == 0x0CF5) unpack_align = a[1]; else if (a[0] == 0x0CF2) unpack_rowlen = a[1]; }
}
#include "gl_stubs.inc"

// ---- tamanho dos dados de pixel ----
static int comps(GLenum f) { switch (f) { case 0x1908: case 0x8D99: return 4; case 0x1907: case 0x8D98: return 3; case 0x8227: case 0x8228: case 0x190A: case 0x84F9: return 2; default: return 1; } }
static int pixb(GLenum f, GLenum t) {
  int c = comps(f);
  switch (t) {
  case 0x1401: case 0x1400: return c;
  case 0x1403: case 0x1402: case 0x140B: return 2 * c;
  case 0x8363: case 0x8033: case 0x8034: return 2;
  case 0x1405: case 0x1404: case 0x1406: return 4 * c;
  case 0x84FA: case 0x8368: case 0x8C3B: case 0x8C3E: return 4;
  case 0x8DAD: return 8;
  }
  return 4 * c;
}
static u32 dlen(int w, int h, int d, GLenum f, GLenum t) {
  u32 pb = pixb(f, t), rl = unpack_rowlen ? unpack_rowlen : w, a = unpack_align ? unpack_align : 1;
  u32 stride = (rl * pb + a - 1) / a * a; return stride * (u32)h * (u32)d;
}

// ---- nomes ----
enum { K_TEX, K_BUF, K_FBO, K_RBO, K_SAMP, K_VAO };
static void gen(int kind, GLsizei n, GLuint *out) {
  hdr(OP_GEN, 8 + 4 * n); p32(kind); p32(n); for (int i = 0; i < n; i++) { out[i] = next_id++; p32(out[i]); }
}
static void del(int kind, GLsizei n, const GLuint *ids) { hdr(OP_DELETE, 8 + 4 * n); p32(kind); p32(n); raw(ids, 4 * n); }
EXPORT void glGenTextures(GLsizei n, GLuint *o) { gen(K_TEX, n, o); }
EXPORT void glGenBuffers(GLsizei n, GLuint *o) { gen(K_BUF, n, o); }
EXPORT void glGenFramebuffers(GLsizei n, GLuint *o) { gen(K_FBO, n, o); }
EXPORT void glGenRenderbuffers(GLsizei n, GLuint *o) { gen(K_RBO, n, o); }
EXPORT void glGenSamplers(GLsizei n, GLuint *o) { gen(K_SAMP, n, o); }
EXPORT void glGenVertexArrays(GLsizei n, GLuint *o) { gen(K_VAO, n, o); }
EXPORT void glDeleteTextures(GLsizei n, const GLuint *o) { del(K_TEX, n, o); }
EXPORT void glDeleteBuffers(GLsizei n, const GLuint *o) { del(K_BUF, n, o); }
EXPORT void glDeleteFramebuffers(GLsizei n, const GLuint *o) { del(K_FBO, n, o); }
EXPORT void glDeleteRenderbuffers(GLsizei n, const GLuint *o) { del(K_RBO, n, o); }
EXPORT void glDeleteSamplers(GLsizei n, const GLuint *o) { del(K_SAMP, n, o); }
EXPORT void glDeleteVertexArrays(GLsizei n, const GLuint *o) { del(K_VAO, n, o); }
EXPORT GLuint glCreateShader(GLenum t) { GLuint id = next_id++; hdr(OP_CREATE_SHADER, 8); p32(id); p32(t); return id; }
EXPORT GLuint glCreateProgram(void) { GLuint id = next_id++; hdr(OP_CREATE_PROGRAM, 4); p32(id); return id; }
EXPORT void glDeleteShader(GLuint s) { hdr(OP_DELETE_SHADER, 4); p32(s); }
EXPORT void glDeleteProgram(GLuint s) { hdr(OP_DELETE_PROGRAM, 4); p32(s); }

EXPORT void glShaderSource(GLuint sh, GLsizei count, const GLchar *const *str, const GLint *len) {
  u32 tot = 0; for (int i = 0; i < count; i++) tot += (len && len[i] >= 0) ? (u32)len[i] : (u32)strlen(str[i]);
  hdr(OP_SHADER_SOURCE, 8 + tot); p32(sh); p32(tot);
  for (int i = 0; i < count; i++) raw(str[i], (len && len[i] >= 0) ? (u32)len[i] : (u32)strlen(str[i]));
}
EXPORT void glBufferData(GLenum tg, GLsizeiptr size, const void *data, GLenum usage) {
  hdr(OP_BUFFER_DATA, 4 + 8 + 4 + 4 + (data ? (u32)size : 0)); p32(tg); p64(size); p32(usage); p32(data != 0); if (data) raw(data, size);
}
EXPORT void glBufferSubData(GLenum tg, GLintptr off, GLsizeiptr size, const void *data) {
  hdr(OP_BUFFER_SUBDATA, 4 + 8 + 8 + (u32)size); p32(tg); p64(off); p64(size); raw(data, size);
}
EXPORT void glTexImage2D(GLenum tg, GLint lv, GLint ifmt, GLsizei w, GLsizei h, GLint border, GLenum f, GLenum t, const void *px) {
  u32 n = px ? dlen(w, h, 1, f, t) : 0;
  hdr(OP_TEX_IMAGE, 40 + n); p32(tg); p32(lv); p32(ifmt); p32(w); p32(h); p32(1); p32(border); p32(f); p32(t); p32(n); if (n) raw(px, n);
}
EXPORT void glTexSubImage2D(GLenum tg, GLint lv, GLint xo, GLint yo, GLsizei w, GLsizei h, GLenum f, GLenum t, const void *px) {
  u32 n = dlen(w, h, 1, f, t);
  hdr(OP_TEX_SUBIMAGE, 48 + n); p32(tg); p32(lv); p32(xo); p32(yo); p32(0); p32(w); p32(h); p32(1); p32(f); p32(t); p32(0); p32(n); raw(px, n);
}
EXPORT void glTexSubImage3D(GLenum tg, GLint lv, GLint xo, GLint yo, GLint zo, GLsizei w, GLsizei h, GLsizei d, GLenum f, GLenum t, const void *px) {
  u32 n = dlen(w, h, d, f, t);
  hdr(OP_TEX_SUBIMAGE, 48 + n); p32(tg); p32(lv); p32(xo); p32(yo); p32(zo); p32(w); p32(h); p32(d); p32(f); p32(t); p32(1); p32(n); raw(px, n);
}
EXPORT void glCompressedTexSubImage2D(GLenum tg, GLint lv, GLint xo, GLint yo, GLsizei w, GLsizei h, GLenum f, GLsizei sz, const void *px) {
  hdr(OP_COMPRESSED_SUBIMAGE, 44 + sz); p32(tg); p32(lv); p32(xo); p32(yo); p32(0); p32(w); p32(h); p32(1); p32(f); p32(sz); p32(0); raw(px, sz);
}
EXPORT void glCompressedTexSubImage3D(GLenum tg, GLint lv, GLint xo, GLint yo, GLint zo, GLsizei w, GLsizei h, GLsizei d, GLenum f, GLsizei sz, const void *px) {
  hdr(OP_COMPRESSED_SUBIMAGE, 44 + sz); p32(tg); p32(lv); p32(xo); p32(yo); p32(zo); p32(w); p32(h); p32(d); p32(f); p32(sz); p32(1); raw(px, sz);
}
static void uni(int kind, GLint loc, GLsizei count, GLboolean tr, const void *v, int per) {
  u32 n = 4 * per * count; hdr(OP_UNIFORMV, 20 + n); p32(kind); p32(loc); p32(count); p32(tr); p32(n); raw(v, n);
}
EXPORT void glUniform1fv(GLint l, GLsizei c, const GLfloat *v) { uni(1, l, c, 0, v, 1); }
EXPORT void glUniform2fv(GLint l, GLsizei c, const GLfloat *v) { uni(2, l, c, 0, v, 2); }
EXPORT void glUniform3fv(GLint l, GLsizei c, const GLfloat *v) { uni(3, l, c, 0, v, 3); }
EXPORT void glUniform4fv(GLint l, GLsizei c, const GLfloat *v) { uni(4, l, c, 0, v, 4); }
EXPORT void glUniform1iv(GLint l, GLsizei c, const GLint *v) { uni(101, l, c, 0, v, 1); }
EXPORT void glUniform2iv(GLint l, GLsizei c, const GLint *v) { uni(102, l, c, 0, v, 2); }
EXPORT void glUniform3iv(GLint l, GLsizei c, const GLint *v) { uni(103, l, c, 0, v, 3); }
EXPORT void glUniform4iv(GLint l, GLsizei c, const GLint *v) { uni(104, l, c, 0, v, 4); }
EXPORT void glUniformMatrix2fv(GLint l, GLsizei c, GLboolean t, const GLfloat *v) { uni(202, l, c, t, v, 4); }
EXPORT void glUniformMatrix3fv(GLint l, GLsizei c, GLboolean t, const GLfloat *v) { uni(203, l, c, t, v, 9); }
EXPORT void glUniformMatrix4fv(GLint l, GLsizei c, GLboolean t, const GLfloat *v) { uni(204, l, c, t, v, 16); }
EXPORT void glDrawBuffers(GLsizei n, const GLenum *b) { hdr(OP_DRAW_BUFFERS, 4 + 4 * n); p32(n); raw(b, 4 * n); }

// ---- consultas (síncronas) ----
EXPORT void glGetIntegerv(GLenum pn, GLint *out) {
  if (!out) return;
  if (pn == 0x821D || pn == 0x87FE) { out[0] = 0; return; }              // NUM_EXTENSIONS, NUM_PROGRAM_BINARY_FORMATS
  if (pn == 0x821B) { out[0] = 3; return; } if (pn == 0x821C) { out[0] = 0; return; }   // MAJOR/MINOR_VERSION
  hdr(OP_GET_INTEGERV, 4); p32(pn); GLint v[16]; rd(v, 64);
  int n = (pn == 0x0BA2 || pn == 0x0C10 || pn == 0x0C22) ? 4 : (pn == 0x846E || pn == 0x846D || pn == 0x0D3A || pn == 0x0B70) ? 2 : 1;
  for (int i = 0; i < n; i++) out[i] = v[i];
}
EXPORT void glGetShaderiv(GLuint s, GLenum pn, GLint *o) { hdr(OP_GET_SHADERIV, 8); p32(s); p32(pn); *o = rd32(); }
EXPORT void glGetProgramiv(GLuint s, GLenum pn, GLint *o) { hdr(OP_GET_PROGRAMIV, 8); p32(s); p32(pn); *o = rd32(); }
static void getlog(u32 op, GLuint s, GLsizei max, GLsizei *len, GLchar *buf) {
  hdr(op, 8); p32(s); p32(max); u32 n = rd32(); u8 tmp[4096]; if (n > sizeof tmp) n = sizeof tmp; rd(tmp, n);
  u32 c = n < (u32)max - 1 ? n : (u32)(max > 0 ? max - 1 : 0); if (max > 0) { memcpy(buf, tmp, c); buf[c] = 0; } if (len) *len = c;
}
EXPORT void glGetShaderInfoLog(GLuint s, GLsizei m, GLsizei *l, GLchar *b) { getlog(OP_GET_SHADER_LOG, s, m, l, b); }
EXPORT void glGetProgramInfoLog(GLuint s, GLsizei m, GLsizei *l, GLchar *b) { getlog(OP_GET_PROGRAM_LOG, s, m, l, b); }
static GLint getloc(u32 op, GLuint p, const GLchar *n) { u32 l = strlen(n); hdr(op, 8 + l); p32(p); p32(l); raw(n, l); return (GLint)rd32(); }
EXPORT GLint glGetAttribLocation(GLuint p, const GLchar *n) { return getloc(OP_GET_ATTRIB_LOC, p, n); }
EXPORT GLint glGetUniformLocation(GLuint p, const GLchar *n) { return getloc(OP_GET_UNIFORM_LOC, p, n); }
EXPORT GLenum glCheckFramebufferStatus(GLenum t) { hdr(OP_CHECK_FB, 4); p32(t); return rd32(); }
EXPORT void glReadPixels(GLint x, GLint y, GLsizei w, GLsizei h, GLenum f, GLenum t, void *px) {
  hdr(OP_READ_PIXELS, 24); p32(x); p32(y); p32(w); p32(h); p32(f); p32(t); u32 n = rd32(); rd(px, n);
}
EXPORT void glFinish(void) { hdr(OP_FINISH, 0); rd32(); }
EXPORT void glFlush(void) {}
EXPORT GLenum glGetError(void) { return 0; }
EXPORT const u8 *glGetString(GLenum n) {
  switch (n) { case 0x1F00: return (const u8*)"IDEmu"; case 0x1F01: return (const u8*)"IDEmu virtual GPU"; case 0x1F02: return (const u8*)"OpenGL ES 3.0 IDEmu";
  case 0x8B8C: return (const u8*)"OpenGL ES GLSL ES 3.00"; case 0x1F03: return (const u8*)"GL_EXT_color_buffer_float GL_OES_texture_float"; }
  return (const u8*)"";
}
EXPORT const u8 *glGetStringi(GLenum n, GLuint i) { (void)n; (void)i; return 0; }
EXPORT void glGetProgramBinary(GLuint p, GLsizei m, GLsizei *len, GLenum *fmt, void *bin) { (void)p; (void)m; (void)fmt; (void)bin; if (len) *len = 0; }
EXPORT void glProgramBinary(GLuint p, GLenum f, const void *b, GLsizei l) { (void)p; (void)f; (void)b; (void)l; }
EXPORT void glEGLImageTargetTexture2DOES(GLenum t, void *img) { (void)t; (void)img; }

// ---- EGL ----
typedef void *EGLDisplay; typedef void *EGLSurface; typedef void *EGLContext; typedef void *EGLConfig; typedef int EGLint; typedef unsigned int EGLBoolean;
static u32 egl_surf_count = 0; static int cur_w = 1920, cur_h = 1080;
static void *wl_dpy; static void wl_flush(void);
EXPORT EGLDisplay eglGetDisplay(void *d) { if (d) wl_dpy = d; return (EGLDisplay)1; }
EXPORT EGLDisplay eglGetPlatformDisplay(EGLint p, void *d, const long *a) { (void)p; (void)d; (void)a; return (EGLDisplay)1; }
EXPORT EGLBoolean eglInitialize(EGLDisplay d, EGLint *maj, EGLint *min) { (void)d; if (maj) *maj = 1; if (min) *min = 4; return 1; }
EXPORT EGLBoolean eglTerminate(EGLDisplay d) { (void)d; return 1; }
EXPORT EGLBoolean eglBindAPI(unsigned a) { (void)a; return 1; }
EXPORT EGLBoolean eglReleaseThread(void) { return 1; }
EXPORT EGLint eglGetError(void) { return 0x3000; }
EXPORT const char *eglQueryString(EGLDisplay d, EGLint n) {
  (void)d; switch (n) { case 0x3053: return "IDEmu"; case 0x3054: return "1.4 IDEmu"; case 0x308D: return "OpenGL_ES";
  case 0x3055: return "EGL_KHR_image_base EGL_KHR_surfaceless_context EGL_WL_bind_wayland_display EGL_EXT_platform_wayland EGL_KHR_platform_wayland"; }
  return "";
}
EXPORT EGLBoolean eglChooseConfig(EGLDisplay d, const EGLint *a, EGLConfig *c, EGLint sz, EGLint *num) { (void)d; (void)a; if (c && sz > 0) c[0] = (EGLConfig)1; if (num) *num = 1; return 1; }
EXPORT EGLBoolean eglGetConfigAttrib(EGLDisplay d, EGLConfig c, EGLint at, EGLint *v) {
  (void)d; (void)c; switch (at) { case 0x3024: case 0x3023: case 0x3022: case 0x3021: *v = 8; break; case 0x3025: *v = 24; break; case 0x3026: *v = 8; break; case 0x3027: *v = 0x3038; break;
  case 0x3040: *v = 0x4 | 0x40; break; case 0x3033: *v = 4; break; default: *v = 0; } return 1;
}
EXPORT EGLContext eglCreateContext(EGLDisplay d, EGLConfig c, EGLContext s, const EGLint *a) { (void)d; (void)c; (void)s; (void)a; static long n = 100; return (EGLContext)(n++); }
EXPORT EGLBoolean eglDestroyContext(EGLDisplay d, EGLContext c) { (void)d; (void)c; return 1; }
EXPORT EGLSurface eglCreateWindowSurface(EGLDisplay d, EGLConfig c, void *win, const EGLint *a) {
  (void)d; (void)c; (void)a; int w = 1920, h = 1080; if (win) { w = ((int*)win)[2]; h = ((int*)win)[3]; }       // struct wl_egl_window: version(8) width height
  u32 id = ++egl_surf_count; cur_w = w; cur_h = h; hdr(OP_INIT_SURFACE, 12); p32(id); p32(w); p32(h); flush(); return (EGLSurface)(long)id;
}
EXPORT EGLSurface eglCreatePbufferSurface(EGLDisplay d, EGLConfig c, const EGLint *a) { (void)d; (void)c; (void)a; return (EGLSurface)(long)++egl_surf_count; }
EXPORT EGLBoolean eglDestroySurface(EGLDisplay d, EGLSurface s) { (void)d; (void)s; return 1; }
EXPORT EGLBoolean eglMakeCurrent(EGLDisplay d, EGLSurface a, EGLSurface b, EGLContext c) { (void)d; (void)a; (void)b; (void)c; wl_flush(); return 1; }
// o EGL do Mesa descarrega o wl_display no swap (é assim que o pedido wl_surface.frame chega ao compositor); sem isso o Ramses nunca recebe o callback e para de renderizar
static void wl_flush(void) { static int (*fl)(void *); if (!fl) fl = (int (*)(void *))dlsym((void *)0, "wl_display_flush"); if (fl && wl_dpy) fl(wl_dpy); }
EXPORT EGLBoolean eglSwapBuffers(EGLDisplay d, EGLSurface s) { (void)d; wl_flush(); hdr(OP_SWAP, 4); p32((u32)(long)s); rd32(); return 1; }
EXPORT EGLBoolean eglSwapInterval(EGLDisplay d, EGLint i) { (void)d; (void)i; return 1; }
EXPORT EGLBoolean eglQuerySurface(EGLDisplay d, EGLSurface s, EGLint at, EGLint *v) { (void)d; (void)s; *v = at == 0x3057 ? cur_w : at == 0x3056 ? cur_h : 0; return 1; }
EXPORT EGLContext eglGetCurrentContext(void) { return (EGLContext)100; }
EXPORT EGLDisplay eglGetCurrentDisplay(void) { return (EGLDisplay)1; }
EXPORT EGLSurface eglGetCurrentSurface(EGLint w) { (void)w; return (EGLSurface)1; }
EXPORT EGLBoolean eglWaitClient(void) { return 1; }
EXPORT EGLBoolean eglWaitNative(EGLint e) { (void)e; return 1; }
EXPORT EGLBoolean eglBindWaylandDisplayWL(EGLDisplay d, void *w) { (void)d; (void)w; return 1; }
EXPORT EGLBoolean eglUnbindWaylandDisplayWL(EGLDisplay d, void *w) { (void)d; (void)w; return 1; }
EXPORT void *eglCreateImageKHR(EGLDisplay d, EGLContext c, unsigned t, void *b, const EGLint *a) { (void)d; (void)c; (void)t; (void)b; (void)a; return 0; }
EXPORT EGLBoolean eglDestroyImageKHR(EGLDisplay d, void *i) { (void)d; (void)i; return 1; }
EXPORT void *eglGetProcAddress(const char *n) { return dlsym((void*)0, n); }

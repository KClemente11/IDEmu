// glhost7: renderizador no Mac para o iDrive 7. Recebe o fluxo EGL/GLES3 do guest (gles_guest.c) por um socket
// unix do QEMU (ttyS1), executa em OpenGL 4.1 core (CGL, fora da tela) e grava cada quadro em <saida>/frame.rgba.
// Uso: glhost7 <socket do QEMU> <pasta de saída>
// Windows (glhost7.exe): o mesmo fluxo em OpenGL 4.1 core por WGL; só o anel de memória compartilhada (shm:nome). Ver win32_host7.h.
#ifdef _WIN32
#include "win32_host7.h"
#include <ctype.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <sys/stat.h>
#else
#define GL_SILENCE_DEPRECATION 1
#include <OpenGL/OpenGL.h>
#include <OpenGL/gl3.h>
#include <stdio.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/mman.h>
#endif
#include <setjmp.h>
#include <signal.h>
#include <errno.h>
#include "proto.h"
#include "gl_ids.h"
#ifdef _WIN32
// O setjmp() do MinGW guarda o quadro para o longjmp() desenrolar a pilha por SEH, e esse desenrolar derruba o glhost7 (violação de acesso
// dentro da ntdll, sem aviso) na primeira mensagem do guest. Sem o quadro o longjmp() só restaura os registradores; o QEMU faz o mesmo
// (include/system/os-win32.h). Fica depois de todos os #include: os cabeçalhos do MinGW redefinem setjmp.
#undef setjmp
#define setjmp(env) _setjmp((env), NULL)
#endif

typedef unsigned char u8; typedef unsigned int u32; typedef unsigned long long u64; typedef long long i64;
static int sock = -1;
static GLuint *idmap;                                 // id do guest -> id real (um espaço só: o contador do guest é único)
#define IDMAX (1 << 22)
static GLuint M(u32 id) { return id < IDMAX ? idmap[id] : 0; }
static GLuint winfbo, wintex, winrb; static int winw, winh; static int cur_prog;
static GLuint vao0; static u8 stype[IDMAX / 4];
static u64 frames, cmds; static int verbose;
static char outdir[512]; static u8 *frame; static int *shm_hdr; static u8 *shm; static size_t shm_size;
static u64 unknown_ops[64]; static u64 n_draws, n_clears; static u64 replay_swaps;
// perfil (GLHOST7_PROF=1): por operação, quantidade, bytes de carga, tempo gasto no GL e respostas síncronas
static int prof; static u64 p_cnt[64], p_bytes[64], p_ns[64], p_sync[64], p_idle_ns, p_rbytes; static i64 p_last;
#ifdef _WIN32
static u64 nsec(void) { return win_nsec(); }
#else
static u64 nsec(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (u64)t.tv_sec * 1000000000ull + t.tv_nsec; }
#endif
static void prof_dump(void) {
  static const char *nm[] = {"NOP","INIT_SURFACE","SWAP","GEN","DELETE","CREATE_SHADER","CREATE_PROGRAM","DELETE_SHADER","DELETE_PROGRAM","SIMPLE","SHADER_SOURCE","BUFFER_DATA","TEX_IMAGE","TEX_SUBIMAGE","COMPRESSED_SUBIMAGE","UNIFORMV","DRAW_BUFFERS","GET_INTEGERV","GET_SHADERIV","GET_PROGRAMIV","GET_SHADER_LOG","GET_PROGRAM_LOG","GET_ATTRIB_LOC","GET_UNIFORM_LOC","CHECK_FB","READ_PIXELS","FINISH","BUFFER_SUBDATA"};
  u64 tb = 0, ts = 0, tn = 0; fprintf(stderr, "PROF ---- ocioso %.1fs\n", p_idle_ns / 1e9);
  for (int i = 0; i < 28; i++) if (p_cnt[i]) { fprintf(stderr, "PROF %-20s n=%-8llu bytes=%-10llu gl=%.2fs sync=%llu\n", nm[i], p_cnt[i], p_bytes[i], p_ns[i] / 1e9, p_sync[i]); tb += p_bytes[i]; ts += p_sync[i]; tn += p_ns[i]; }
  fprintf(stderr, "PROF total bytes=%llu sync=%llu gl=%.2fs reply_bytes=%llu quadros=%llu\n", tb, ts, tn / 1e9, p_rbytes, frames);
}

static void die(const char *m) { fprintf(stderr, "glhost7: %s\n", m); exit(1); }
// ---- transporte: anel em memória compartilhada (shm:/nome, dispositivo idemu-shm do QEMU) ou socket unix (serial do QEMU) ----
static struct shm_hdr *H; static u8 *gdat, *hdat; static u64 gh, ht; static unsigned my_epoch; static jmp_buf resync;
// ---- snapshot: o fluxo recebido do guest é gravado (GLHOST7_REC=arquivo) e, ao restaurar a VM, reexecutado (--replay arquivo) para recriar o estado do GL no Mac ----
static FILE *rec; static volatile sig_atomic_t stop_rec; static char rec_path[600];
static u8 *rep_buf; static size_t rep_len, rep_pos; static int replaying, at_hdr, adopt;
static void on_usr1(int s) { (void)s; stop_rec = 1; }
static void rec_close(void) {
  if (!rec) return;
  fclose(rec); rec = NULL; char p[640]; snprintf(p, sizeof p, "%s.done", rec_path); FILE *f = fopen(p, "w"); if (f) { fputs("ok\n", f); fclose(f); }
  fprintf(stderr, "glhost7: gravação do fluxo encerrada\n");
}
static void idle_wait(unsigned *n) {                 // espera curta: gira um pouco (latência baixa quando o guest está ativo) e depois dorme
  if (H && at_hdr) H->host_idle = 1;
  if (stop_rec && at_hdr) rec_close();
#ifdef _WIN32
  win_idle(++*n);
#else
  if (++*n < 400) { __asm__ volatile("yield" ::: "memory"); return; }
  if (*n < 4000) { usleep(30); return; }
  usleep(600);
#endif
}
static void shm_open_ring(const char *name) {
#ifdef _WIN32
  void *m = win_open_ring(name, SHM_SIZE);             // o QEMU cria o mapeamento ao subir
  if (!m) die("memória compartilhada não encontrada");
  H = m; gdat = (u8 *)m + G_OFF; hdat = (u8 *)m + H_OFF;
#else
  int fd = -1;
  for (int i = 0; i < 1200 && fd < 0; i++) { fd = shm_open(name, O_RDWR, 0600); if (fd < 0) usleep(100000); }   // o QEMU cria o objeto ao subir
  if (fd < 0) die("memória compartilhada não encontrada");
  void *m = MAP_FAILED; for (int i = 0; i < 600; i++) { m = mmap(NULL, SHM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0); if (m != MAP_FAILED) break; usleep(100000); }
  if (m == MAP_FAILED) die("mmap da memória compartilhada falhou");
  close(fd); H = m; gdat = (u8 *)m + G_OFF; hdat = (u8 *)m + H_OFF;
#endif
  fprintf(stderr, "glhost7: anel %s mapeado\n", name);
}
static int ring_sync(void) {                         // o guest reiniciou o fluxo (processo novo): descarta o que ficou pela metade
  if (replaying) return 0;
  unsigned e = H->epoch; if (e == my_epoch) return 0;
  my_epoch = e; gh = H->g_start; H->g_head = gh; ht = H->h_tail; return 1;
}
static void rdn(void *p, size_t n) {
  if (replaying) {
    if (rep_pos >= rep_len && n == 8) { replaying = 0; longjmp(resync, 2); }          // fim da gravação, na fronteira de uma mensagem
    if (rep_pos + n > rep_len) die("gravação do fluxo truncada");
    memcpy(p, rep_buf + rep_pos, n); rep_pos += n; return;
  }
  if (!H) { u8 *d = p; while (n) { ssize_t r = read(sock, d, n); if (r <= 0) die("socket fechado"); d += r; n -= r; } return; }
  u8 *d = p; unsigned w = 0;
  while (n) {
    if (H->magic != SHM_MAGIC) { idle_wait(&w); continue; }
#ifdef _WIN32
    { static unsigned seen; if (seen != H->epoch) { seen = H->epoch; WIN_TRACE("glhost7: guest stream: epoch %u, start %llu, tail %llu\n", seen, H->g_start, H->g_tail); } }
#endif
    if (ring_sync()) longjmp(resync, 1);
    u64 av = H->g_tail - gh;
    if (!av) { idle_wait(&w); continue; }
    w = 0; __atomic_thread_fence(__ATOMIC_ACQUIRE);
    size_t c = av > n ? n : (size_t)av, off = (size_t)(gh & (G_SIZE - 1)), seg = G_SIZE - off; if (seg > c) seg = c;
    memcpy(d, gdat + off, seg); if (c > seg) memcpy(d + seg, gdat, c - seg);
    gh += c; d += c; n -= c; __atomic_thread_fence(__ATOMIC_RELEASE); H->g_head = gh;
    if (at_hdr) { H->host_idle = 0; at_hdr = 0; }
  }
  if (rec) fwrite((u8 *)p, 1, (u8 *)d - (u8 *)p, rec);
}
static void wrn(const void *p, size_t n) {
  if (replaying) return;
  if (!H) { const u8 *s = p; while (n) { ssize_t r = write(sock, s, n); if (r <= 0) die("escrita falhou"); s += r; n -= r; } return; }
  const u8 *s = p; unsigned w = 0;
  while (n) {
    u64 used = ht - H->h_head;
    if (used >= H_SIZE) { idle_wait(&w); if (ring_sync()) longjmp(resync, 1); continue; }
    w = 0; size_t c = H_SIZE - (size_t)used; if (c > n) c = n; size_t off = (size_t)(ht & (H_SIZE - 1)), seg = H_SIZE - off; if (seg > c) seg = c;
    memcpy(hdat + off, s, seg); if (c > seg) memcpy(hdat, s + seg, c - seg);
    ht += c; s += c; n -= c; __atomic_thread_fence(__ATOMIC_RELEASE); H->h_tail = ht;
  }
}
static void rep32(u32 v) { wrn(&v, 4); p_rbytes += 4; }

static void fmt_for(GLenum ifmt, GLenum *f, GLenum *t) {
  *f = GL_RGBA; *t = GL_UNSIGNED_BYTE;
  switch (ifmt) {
  case GL_R8: *f = GL_RED; break; case GL_RG8: *f = GL_RG; break; case GL_RGB8: case 0x8C41: *f = GL_RGB; break;
  case 0x881A: *t = GL_HALF_FLOAT; break; case 0x8814: *t = GL_FLOAT; break;
  case 0x822D: *f = GL_RED; *t = GL_HALF_FLOAT; break; case 0x822F: *f = GL_RG; *t = GL_HALF_FLOAT; break; case 0x881B: *f = GL_RGB; *t = GL_HALF_FLOAT; break;
  case 0x822E: *f = GL_RED; *t = GL_FLOAT; break; case 0x8230: *f = GL_RG; *t = GL_FLOAT; break; case 0x8815: *f = GL_RGB; *t = GL_FLOAT; break;
  case 0x81A5: *f = GL_DEPTH_COMPONENT; *t = GL_UNSIGNED_SHORT; break; case 0x81A6: *f = GL_DEPTH_COMPONENT; *t = GL_UNSIGNED_INT; break;
  case 0x8CAC: *f = GL_DEPTH_COMPONENT; *t = GL_FLOAT; break; case 0x88F0: *f = GL_DEPTH_STENCIL; *t = GL_UNSIGNED_INT_24_8; break;
  case 0x8D62: *f = GL_RGB; *t = GL_UNSIGNED_SHORT_5_6_5; break; case 0x8056: *t = GL_UNSIGNED_SHORT_4_4_4_4; break; case 0x8057: *t = GL_UNSIGNED_SHORT_5_5_5_1; break;
  case 0x8C3A: *f = GL_RGB; *t = GL_UNSIGNED_INT_10F_11F_11F_REV; break; case 0x8059: *t = GL_UNSIGNED_INT_2_10_10_10_REV; break;
  }
}
// ES unsized/legado -> core. swz[]: swizzle a aplicar depois (0 = nenhum)
static void es_fmt(GLenum *ifmt, GLenum *fmt, int *swz) {
  *swz = 0;
  if (*fmt == 0x1909) { *fmt = GL_RED; if (*ifmt == 0x1909) *ifmt = GL_R8; *swz = 1; }                   // LUMINANCE
  else if (*fmt == 0x1906) { *fmt = GL_RED; if (*ifmt == 0x1906) *ifmt = GL_R8; *swz = 2; }              // ALPHA
  else if (*fmt == 0x190A) { *fmt = GL_RG; if (*ifmt == 0x190A) *ifmt = GL_RG8; *swz = 3; }              // LUMINANCE_ALPHA
}
static void apply_swz(GLenum target, int swz) {
  if (!swz) return;
  GLint s[4] = {GL_RED, GL_RED, GL_RED, GL_ONE};
  if (swz == 2) { s[0] = s[1] = s[2] = GL_ZERO; s[3] = GL_RED; } else if (swz == 3) s[3] = GL_GREEN;
  glTexParameteriv(target, GL_TEXTURE_SWIZZLE_RGBA, s);
}

static char *repl_word(char *s, const char *from, const char *to) {
  size_t fl = strlen(from), tl = strlen(to), n = strlen(s); char *o = malloc(n * 2 + 64); size_t j = 0;
  for (size_t i = 0; i < n;) {
    int idc = (i == 0) || !(isalnum((u8)s[i - 1]) || s[i - 1] == '_');
    if (idc && !strncmp(s + i, from, fl) && !(isalnum((u8)s[i + fl]) || s[i + fl] == '_')) { memcpy(o + j, to, tl); j += tl; i += fl; }
    else o[j++] = s[i++];
  }
  o[j] = 0; free(s); return o;
}
static char *xlat_shader(const char *src, int n, int is_vs) {
  char *t = malloc(n + 1); memcpy(t, src, n); t[n] = 0;
  int es1 = !strstr(t, "#version 3");                                     // GLSL ES 1.00 (sem #version ou #version 100)
  char *o = malloc(n * 2 + 512); int j = 0; const char *p = t, *end = t + n; int done_ver = 0;
  while (p < end) {
    const char *e = memchr(p, '\n', end - p); if (!e) e = end; int l = (int)(e - p);
    if (l >= 8 && !strncmp(p, "#version", 8)) { j += sprintf(o + j, "#version 410 core"); done_ver = 1;
      if (es1 && !is_vs) j += sprintf(o + j, "\nout vec4 idemu_FragColor;"); }
    else if (l >= 10 && !strncmp(p, "#extension", 10) && (memmem(p, l, "GL_OES", 6) || memmem(p, l, "GL_EXT", 6) || memmem(p, l, "GL_KHR", 6) || memmem(p, l, "GL_OVR", 6))) {}
    else { memcpy(o + j, p, l); j += l; }
    if (e < end) o[j++] = '\n'; p = e + 1;
  }
  o[j] = 0; free(t);
  if (!done_ver) { char *q = malloc(strlen(o) + 128); sprintf(q, "#version 410 core\n%s%s", (es1 && !is_vs) ? "out vec4 idemu_FragColor;\n" : "", o); free(o); o = q; }
  if (es1) {
    if (is_vs) { o = repl_word(o, "attribute", "in"); o = repl_word(o, "varying", "out"); }
    else { o = repl_word(o, "varying", "in"); o = repl_word(o, "gl_FragColor", "idemu_FragColor"); o = repl_word(o, "gl_FragData[0]", "idemu_FragColor"); }
    o = repl_word(o, "texture2D", "texture"); o = repl_word(o, "textureCube", "texture"); o = repl_word(o, "texture2DProj", "textureProj");
    o = repl_word(o, "texture2DLod", "textureLod"); o = repl_word(o, "textureCubeLod", "textureLod");
  }
  o = repl_word(o, "sample", "idemu_sample"); o = repl_word(o, "patch", "idemu_patch"); o = repl_word(o, "subroutine", "idemu_subroutine");
  return o;
}

static void save_frame(void) {
  if (!winfbo) return;
  glBindFramebuffer(GL_READ_FRAMEBUFFER, winfbo); glPixelStorei(GL_PACK_ALIGNMENT, 1);
  glReadPixels(0, 0, winw, winh, GL_RGBA, GL_UNSIGNED_BYTE, frame);
  // linha 0 = topo
  u8 *dst = shm + 64; size_t row = (size_t)winw * 4;
  for (int y = 0; y < winh; y++) {                 // vira o quadro (linha 0 = topo) e deixa o alfa opaco: o navegador usa o RGBA direto
    const u32 *a = (const u32 *)(frame + (size_t)(winh - 1 - y) * row); u32 *b = (u32 *)(dst + (size_t)y * row);
    for (int x = 0; x < winw; x++) b[x] = a[x] | 0xff000000u;
  }
  shm_hdr[0] = winw; shm_hdr[1] = winh; __sync_synchronize(); shm_hdr[2] = (int)++frames;
}

static void do_simple(u32 fn, u64 *a, int n) {
  (void)n;
#define I(k) ((GLint)(u32)a[k])
#define U(k) ((GLuint)(u32)a[k])
#define FL(k) ({ union { u32 u; float f; } _x; _x.u = (u32)a[k]; _x.f; })
  switch (fn) {
  case F_ActiveTexture: glActiveTexture(U(0)); break;
  case F_AttachShader: glAttachShader(M(U(0)), M(U(1))); break;
  case F_BindBuffer: glBindBuffer(U(0), M(U(1))); break;
  case F_BindFramebuffer: glBindFramebuffer(U(0), U(1) ? M(U(1)) : winfbo); break;
  case F_BindRenderbuffer: glBindRenderbuffer(U(0), M(U(1))); break;
  case F_BindSampler: glBindSampler(U(0), M(U(1))); break;
  case F_BindTexture: glBindTexture(U(0), M(U(1))); break;
  case F_BindVertexArray: break;
  case F_BlendEquationSeparate: glBlendEquationSeparate(U(0), U(1)); break;
  case F_BlendFuncSeparate: glBlendFuncSeparate(U(0), U(1), U(2), U(3)); break;
  case F_BlitFramebuffer: glBlitFramebuffer(I(0), I(1), I(2), I(3), I(4), I(5), I(6), I(7), U(8), U(9)); break;
  case F_Clear: n_clears++; glClear(U(0)); break;
  case F_ClearColor: glClearColor(FL(0), FL(1), FL(2), FL(3)); break;
  case F_ClearDepthf: glClearDepth(FL(0)); break;
  case F_ClearStencil: glClearStencil(I(0)); break;
  case F_ColorMask: glColorMask(I(0), I(1), I(2), I(3)); break;
  case F_CompileShader: { GLuint s = M(U(0)); glCompileShader(s); break; }
  case F_CullFace: glCullFace(U(0)); break;
  case F_DepthFunc: glDepthFunc(U(0)); break;
  case F_DepthMask: glDepthMask(I(0)); break;
  case F_Disable: glDisable(U(0)); break;
  case F_DrawArrays: n_draws++; glDrawArrays(U(0), I(1), I(2)); break;
  case F_DrawArraysInstanced: n_draws++; glDrawArraysInstanced(U(0), I(1), I(2), I(3)); break;
  case F_DrawElements: n_draws++; glDrawElements(U(0), I(1), U(2), (const void *)a[3]); break;
  case F_DrawElementsInstanced: n_draws++; glDrawElementsInstanced(U(0), I(1), U(2), (const void *)a[3], I(4)); break;
  case F_Enable: glEnable(U(0)); break;
  case F_EnableVertexAttribArray: glEnableVertexAttribArray(U(0)); break;
  case F_DisableVertexAttribArray: glDisableVertexAttribArray(U(0)); break;
  case F_FramebufferRenderbuffer: glFramebufferRenderbuffer(U(0), U(1), U(2), M(U(3))); break;
  case F_FramebufferTexture2D: glFramebufferTexture2D(U(0), U(1), U(2), M(U(3)), I(4)); break;
  case F_FramebufferTextureLayer: glFramebufferTextureLayer(U(0), U(1), M(U(2)), I(3), I(4)); break;
  case F_GenerateMipmap: glGenerateMipmap(U(0)); break;
  case F_LinkProgram: glLinkProgram(M(U(0))); break;
  case F_PixelStorei: glPixelStorei(U(0), I(1)); break;
  case F_RenderbufferStorageMultisample: glRenderbufferStorageMultisample(U(0), I(1), U(2), I(3), I(4)); break;
  case F_Scissor: glScissor(I(0), I(1), I(2), I(3)); break;
  case F_StencilFunc: glStencilFunc(U(0), I(1), U(2)); break;
  case F_StencilFuncSeparate: glStencilFuncSeparate(U(0), U(1), I(2), U(3)); break;
  case F_StencilOp: glStencilOp(U(0), U(1), U(2)); break;
  case F_StencilOpSeparate: glStencilOpSeparate(U(0), U(1), U(2), U(3)); break;
  case F_StencilMask: glStencilMask(U(0)); break;
  case F_TexParameteri: glTexParameteri(U(0), U(1), I(2)); break;
  case F_TexParameterf: glTexParameterf(U(0), U(1), FL(2)); break;
  case F_SamplerParameteri: glSamplerParameteri(M(U(0)), U(1), I(2)); break;
  case F_TexStorage2D: {
    GLenum f, t; fmt_for(U(2), &f, &t); int w = I(3), h = I(4);
    for (int l = 0; l < I(1); l++) { glTexImage2D(U(0), l, U(2), w, h, 0, f, t, NULL); if (w > 1) w >>= 1; if (h > 1) h >>= 1; }
    break; }
  case F_TexStorage3D: {
    GLenum f, t; fmt_for(U(2), &f, &t); int w = I(3), h = I(4), d = I(5);
    for (int l = 0; l < I(1); l++) { glTexImage3D(U(0), l, U(2), w, h, d, 0, f, t, NULL); if (w > 1) w >>= 1; if (h > 1) h >>= 1; if (U(0) == GL_TEXTURE_3D && d > 1) d >>= 1; }
    break; }
  case F_Uniform1i: glUniform1i(I(0), I(1)); break;
  case F_Uniform1f: glUniform1f(I(0), FL(1)); break;
  case F_Uniform2f: glUniform2f(I(0), FL(1), FL(2)); break;
  case F_Uniform3f: glUniform3f(I(0), FL(1), FL(2), FL(3)); break;
  case F_Uniform4f: glUniform4f(I(0), FL(1), FL(2), FL(3), FL(4)); break;
  case F_Uniform2i: glUniform2i(I(0), I(1), I(2)); break;
  case F_Uniform3i: glUniform3i(I(0), I(1), I(2), I(3)); break;
  case F_Uniform4i: glUniform4i(I(0), I(1), I(2), I(3), I(4)); break;
  case F_UseProgram: glUseProgram(M(U(0))); cur_prog = U(0); break;
  case F_VertexAttribDivisor: glVertexAttribDivisor(U(0), U(1)); break;
  case F_VertexAttribPointer: glVertexAttribPointer(U(0), I(1), U(2), I(3), I(4), (const void *)a[5]); break;
  case F_VertexAttrib4f: glVertexAttrib4f(U(0), FL(1), FL(2), FL(3), FL(4)); break;
  case F_Viewport: glViewport(I(0), I(1), I(2), I(3)); break;
  case F_BlendColor: glBlendColor(FL(0), FL(1), FL(2), FL(3)); break;
  case F_Hint: glHint(U(0), U(1)); break;
  case F_LineWidth: glLineWidth(FL(0)); break;
  case F_PolygonOffset: glPolygonOffset(FL(0), FL(1)); break;
  case F_FrontFace: glFrontFace(U(0)); break;
  case F_BlendEquation: glBlendEquation(U(0)); break;
  case F_BlendFunc: glBlendFunc(U(0), U(1)); break;
  case F_DepthRangef: glDepthRange(FL(0), FL(1)); break;
  case F_SampleCoverage: glSampleCoverage(FL(0), I(1)); break;
  case F_ReadBuffer: glReadBuffer(U(0)); break;
  default: fprintf(stderr, "glhost7: SIMPLE %u não tratado\n", fn);
  }
}

static GLuint gen1(int kind) {
  GLuint r = 0;
  switch (kind) { case 0: glGenTextures(1, &r); break; case 1: glGenBuffers(1, &r); break; case 2: glGenFramebuffers(1, &r); break;
  case 3: glGenRenderbuffers(1, &r); break; case 4: glGenSamplers(1, &r); break; case 5: glGenVertexArrays(1, &r); break; }
  return r;
}
static void del1(int kind, GLuint r) {
  switch (kind) { case 0: glDeleteTextures(1, &r); break; case 1: glDeleteBuffers(1, &r); break; case 2: glDeleteFramebuffers(1, &r); break;
  case 3: glDeleteRenderbuffers(1, &r); break; case 4: glDeleteSamplers(1, &r); break; case 5: glDeleteVertexArrays(1, &r); break; }
}

static void init_gl(void) {
#ifdef _WIN32
  const char *err = win_init_gl(); if (err) die(err);
#else
  CGLPixelFormatAttribute at[] = { kCGLPFAOpenGLProfile, (CGLPixelFormatAttribute)kCGLOGLPVersion_GL4_Core, kCGLPFAAccelerated, kCGLPFAColorSize, (CGLPixelFormatAttribute)24, (CGLPixelFormatAttribute)0 };
  CGLPixelFormatObj pf; GLint n; if (CGLChoosePixelFormat(at, &pf, &n) || !pf) die("sem formato de pixel GL 4.1");
  CGLContextObj ctx; if (CGLCreateContext(pf, NULL, &ctx)) die("CGLCreateContext"); CGLSetCurrentContext(ctx);
#endif
  fprintf(stderr, "glhost7: %s | %s\n", glGetString(GL_RENDERER), glGetString(GL_VERSION));
  glGenVertexArrays(1, &vao0); glBindVertexArray(vao0);
  glEnable(GL_PROGRAM_POINT_SIZE);
}

static void init_surface(u32 id, int w, int h) {
  (void)id;
  if (winfbo) { glDeleteFramebuffers(1, &winfbo); glDeleteTextures(1, &wintex); glDeleteRenderbuffers(1, &winrb); }
  winw = w; winh = h;
  glGenTextures(1, &wintex); glBindTexture(GL_TEXTURE_2D, wintex); glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR); glBindTexture(GL_TEXTURE_2D, 0);
  glGenRenderbuffers(1, &winrb); glBindRenderbuffer(GL_RENDERBUFFER, winrb); glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, w, h);
  glGenFramebuffers(1, &winfbo); glBindFramebuffer(GL_FRAMEBUFFER, winfbo);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, wintex, 0);
  glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, winrb);
  glViewport(0, 0, w, h); glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
  free(frame); frame = malloc((size_t)w * h * 4);
#ifdef _WIN32
  size_t need = 64 + (size_t)w * h * 4; char p[600]; snprintf(p, sizeof p, "%s/frame.rgba", outdir);
  if (!shm || need != shm_size) {                      // mesmo tamanho (o HMI reiniciou): mantém o mapeamento que o app já abriu
    if (shm) UnmapViewOfFile(shm);
    shm_size = need; shm = win_frame_mapping(p, shm_size);
    if (!shm) die("não consegui criar o frame.rgba");
  }
#else
  if (shm) munmap(shm, shm_size);
  shm_size = 64 + (size_t)w * h * 4; char p[600]; snprintf(p, sizeof p, "%s/frame.rgba", outdir);
  int fd = open(p, O_RDWR | O_CREAT | O_TRUNC, 0644); ftruncate(fd, shm_size); shm = mmap(NULL, shm_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0); close(fd);
#endif
  shm_hdr = (int *)shm; shm_hdr[0] = w; shm_hdr[1] = h; shm_hdr[2] = 0; frames = 0;
  fprintf(stderr, "glhost7: superfície %dx%d\n", w, h);
}

int main(int argc, char **argv) {
  if (argc < 3) die("uso: glhost7 <socket|shm:nome> <pasta> [--replay arquivo]");
  strncpy(outdir, argv[2], sizeof outdir - 1); mkdir(outdir, 0755); verbose = getenv("GLHOST7_VERBOSE") != NULL; prof = getenv("GLHOST7_PROF") != NULL;
  idmap = calloc(IDMAX, 4); init_gl();
#ifndef _WIN32
  signal(SIGUSR1, on_usr1);
#endif
  const char *rp = getenv("GLHOST7_REC");
  if (rp && !strncmp(argv[1], "shm:", 4)) { snprintf(rec_path, sizeof rec_path, "%s", rp); rec = fopen(rp, "wb"); if (rec) setvbuf(rec, NULL, _IOFBF, 1 << 20); }
  for (int i = 3; i + 1 < argc; i++) if (!strcmp(argv[i], "--replay")) {            // restaurar: reexecuta o fluxo gravado antes de adotar o anel
    FILE *f = fopen(argv[i + 1], "rb"); if (!f) die("gravação do fluxo não abriu");
    fseek(f, 0, SEEK_END); rep_len = (size_t)ftell(f); fseek(f, 0, SEEK_SET); rep_buf = malloc(rep_len ? rep_len : 1);
    if (fread(rep_buf, 1, rep_len, f) != rep_len) die("gravação do fluxo incompleta"); fclose(f); replaying = 1; adopt = 1;
    fprintf(stderr, "glhost7: reproduzindo %zu bytes do fluxo\n", rep_len);
  }
  if (!strncmp(argv[1], "shm:", 4)) shm_open_ring(argv[1] + 4);
  else {
#ifdef _WIN32
    die("no Windows o canal gráfico é a memória compartilhada: use shm:nome");
#else
    struct sockaddr_un sa; memset(&sa, 0, sizeof sa); sa.sun_family = AF_UNIX; strncpy(sa.sun_path, argv[1], sizeof sa.sun_path - 1);
    sock = socket(AF_UNIX, SOCK_STREAM, 0);
    for (int i = 0;; i++) { if (!connect(sock, (struct sockaddr *)&sa, sizeof sa)) break; if (i > 600) die("não conectou ao QEMU"); usleep(100000); }
    fprintf(stderr, "glhost7: conectado a %s\n", argv[1]);
#endif
  }
  static u8 *buf; static size_t cap; static time_t tlog; buf = malloc(1 << 20); cap = 1 << 20; tlog = time(0);
  if (setjmp(resync) == 2) {                        // fim da reprodução: mostra o último quadro e passa a ler o anel de onde a VM parou
    glFinish(); save_frame();
    for (int i = 0; i < 6000 && H->magic != SHM_MAGIC; i++) usleep(10000);
    my_epoch = H->epoch; gh = H->g_head; ht = H->h_tail;
    char p[700]; snprintf(p, sizeof p, "%s/gl.ready", outdir); FILE *f = fopen(p, "w"); if (f) { fprintf(f, "%llu\n", (unsigned long long)replay_swaps); fclose(f); }
    fprintf(stderr, "glhost7: reprodução concluída (%llu quadros); anel adotado em %llu\n", (unsigned long long)replay_swaps, (unsigned long long)gh);
  }
#ifdef _WIN32
  WIN_TRACE("glhost7: command loop, reading from %llu\n", gh);
#endif
  for (;;) {
    u64 t_a = prof ? nsec() : 0; u32 h[2]; at_hdr = 1; rdn(h, 8); u32 op = h[0], len = h[1];
#ifdef _WIN32
    WIN_TRACE("glhost7: command %llu: op %u, %u bytes\n", cmds + 1, op, len);
#endif
    if (len > cap) { cap = len + 4096; buf = realloc(buf, cap); }
    if (len) rdn(buf, len);
    u64 t_b = prof ? nsec() : 0; if (prof) p_idle_ns += t_b - t_a;
    u32 *w = (u32 *)buf; cmds++;
#ifdef _WIN32
    win_ops = cmds; win_last_op = op; win_last_len = len; win_last_fn = (op == OP_SIMPLE && len >= 4) ? w[0] : ~0u;      // para o relato de falha
#endif
    switch (op) {
    case OP_INIT_SURFACE: init_surface(w[0], w[1], w[2]); break;
    case OP_SWAP: if (replaying) { replay_swaps++; rep32(1); break; } glFlush(); save_frame(); rep32(1); break;
    case OP_GEN: { u32 k = w[0], n = w[1]; for (u32 i = 0; i < n; i++) { u32 id = w[2 + i]; if (id < IDMAX) idmap[id] = gen1(k); if (k == 5) {} } break; }
    case OP_DELETE: { u32 k = w[0], n = w[1]; for (u32 i = 0; i < n; i++) { u32 id = w[2 + i]; if (id < IDMAX && idmap[id]) { del1(k, idmap[id]); idmap[id] = 0; } } break; }
    case OP_CREATE_SHADER: idmap[w[0]] = glCreateShader(w[1]); if (w[0] < IDMAX / 4) stype[w[0]] = (w[1] == GL_VERTEX_SHADER); break;
    case OP_CREATE_PROGRAM: idmap[w[0]] = glCreateProgram(); break;
    case OP_DELETE_SHADER: glDeleteShader(M(w[0])); idmap[w[0]] = 0; break;
    case OP_DELETE_PROGRAM: glDeleteProgram(M(w[0])); idmap[w[0]] = 0; break;
    case OP_SIMPLE: { u64 a[16]; u32 n = w[1]; for (u32 i = 0; i < n && i < 16; i++) memcpy(&a[i], buf + 8 + 8 * i, 8); do_simple(w[0], a, n); break; }
    case OP_SHADER_SOURCE: { char *s = xlat_shader((char *)(buf + 8), w[1], w[0] < IDMAX / 4 ? stype[w[0]] : 0); const char *sp = s; glShaderSource(M(w[0]), 1, &sp, NULL); if (verbose) fprintf(stderr, "---- shader %u\n%s\n", w[0], s); free(s); break; }
    case OP_BUFFER_DATA: { i64 sz; memcpy(&sz, buf + 4, 8); glBufferData(w[0], sz, w[4] ? buf + 20 : NULL, w[3]); break; }
    case OP_BUFFER_SUBDATA: { i64 off, sz; memcpy(&off, buf + 4, 8); memcpy(&sz, buf + 12, 8); glBufferSubData(w[0], off, sz, buf + 20); break; }
    case OP_TEX_IMAGE: {
      GLenum ifmt = w[2], fmt = w[7]; int swz; es_fmt(&ifmt, &fmt, &swz);
      glTexImage2D(w[0], w[1], ifmt, w[3], w[4], w[6], fmt, w[8], w[9] ? buf + 40 : NULL); apply_swz(w[0], swz); break; }
    case OP_TEX_SUBIMAGE: {
      GLenum ifmt = 0, fmt = w[8]; int swz; es_fmt(&ifmt, &fmt, &swz); const u8 *d = buf + 48;
      if (w[10]) glTexSubImage3D(w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7], fmt, w[9], d);
      else glTexSubImage2D(w[0], w[1], w[2], w[3], w[5], w[6], fmt, w[9], d);
      break; }
    case OP_COMPRESSED_SUBIMAGE: { static int warned; if (!warned++) fprintf(stderr, "glhost7: textura comprimida (formato 0x%x) ainda não suportada\n", w[8]); break; }
    case OP_UNIFORMV: {
      u32 k = w[0]; GLint loc = (GLint)w[1]; GLsizei c = w[2]; const void *d = buf + 20;
      switch (k) { case 1: glUniform1fv(loc, c, d); break; case 2: glUniform2fv(loc, c, d); break; case 3: glUniform3fv(loc, c, d); break; case 4: glUniform4fv(loc, c, d); break;
      case 101: glUniform1iv(loc, c, d); break; case 102: glUniform2iv(loc, c, d); break; case 103: glUniform3iv(loc, c, d); break; case 104: glUniform4iv(loc, c, d); break;
      case 202: glUniformMatrix2fv(loc, c, w[3], d); break; case 203: glUniformMatrix3fv(loc, c, w[3], d); break; case 204: glUniformMatrix4fv(loc, c, w[3], d); break; }
      break; }
    case OP_DRAW_BUFFERS: glDrawBuffers(w[0], (const GLenum *)(buf + 4)); break;
    case OP_GET_INTEGERV: {
      GLint v[16] = {0}; u32 pn = w[0];
      switch (pn) {
      case 0x8DFB: glGetIntegerv(0x8B4A, v); v[0] /= 4; break; case 0x8DFD: glGetIntegerv(0x8B49, v); v[0] /= 4; break; case 0x8DFC: glGetIntegerv(0x8B4B, v); v[0] /= 4; if (v[0] < 15) v[0] = 15; break;
      case 0x86A2: v[0] = 0; break; case 0x8B9B: v[0] = GL_RGBA; break; case 0x8B9A: v[0] = GL_UNSIGNED_BYTE; break;
      case GL_FRAMEBUFFER_BINDING: v[0] = 0; break;
      default: glGetIntegerv(pn, v); }
      wrn(v, 64); break; }
    case OP_GET_SHADERIV: { GLint v = 0; glGetShaderiv(M(w[0]), w[1], &v); rep32(v); break; }
    case OP_GET_PROGRAMIV: { GLint v = 0; glGetProgramiv(M(w[0]), w[1], &v); rep32(v); break; }
    case OP_GET_SHADER_LOG: case OP_GET_PROGRAM_LOG: {
      char t[4096]; GLsizei n = 0; if (op == OP_GET_SHADER_LOG) glGetShaderInfoLog(M(w[0]), sizeof t - 1, &n, t); else glGetProgramInfoLog(M(w[0]), sizeof t - 1, &n, t);
      t[n] = 0; if (n) fprintf(stderr, "log(%u): %s\n", w[0], t); rep32(n); wrn(t, n); break; }
    case OP_GET_ATTRIB_LOC: { char t[256]; u32 l = w[1] < 255 ? w[1] : 255; memcpy(t, buf + 8, l); t[l] = 0; rep32(glGetAttribLocation(M(w[0]), t)); break; }
    case OP_GET_UNIFORM_LOC: { char t[256]; u32 l = w[1] < 255 ? w[1] : 255; memcpy(t, buf + 8, l); t[l] = 0; rep32(glGetUniformLocation(M(w[0]), t)); break; }
    case OP_CHECK_FB: rep32(glCheckFramebufferStatus(w[0])); break;
    case OP_READ_PIXELS: { int pw = w[2], ph = w[3]; u32 n = pw * 4 * ph; u8 *t = malloc(n); glPixelStorei(GL_PACK_ALIGNMENT, 4); glReadPixels(w[0], w[1], pw, ph, w[4], w[5], t); rep32(n); wrn(t, n); free(t); break; }
    case OP_FINISH: glFinish(); rep32(1); break;
    default: if (op < 64 && !unknown_ops[op]++) fprintf(stderr, "glhost7: op %u desconhecida\n", op);
    }
    if (prof && op < 64) { u64 t_c = nsec(); p_cnt[op]++; p_bytes[op] += len + 8; p_ns[op] += t_c - t_b; if (op >= 17 && op <= 26 && op != 16) p_sync[op]++; if (op == OP_SWAP) p_sync[op]++;
      if ((i64)(t_c / 1000000000ull) != p_last && (p_last = t_c / 1000000000ull) % 5 == 0) prof_dump(); }
    if (time(0) != tlog && verbose) { tlog = time(0); fprintf(stderr, "glhost7: %llu comandos, %llu quadros, %llu desenhos, %llu clears\n", cmds, frames, n_draws, n_clears); }
  }
}

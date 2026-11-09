// libidemuhmi.so (LD_PRELOAD no Hmi8): correções em memória e entrada do controlador. O Hmi8 exporta os símbolos, então
// dlsym acha tudo. Cada comando chega pelo canal (role 2) e roda na thread do HMI, dentro de onFrameTimer.
#include "chan.h"
typedef unsigned long ul; typedef unsigned u32; typedef unsigned char u8; typedef unsigned short u16;
extern void *mmap(void *, ul, int, int, int, long); extern int mprotect(void *, ul, int); extern int open(const char *, int, ...); extern int close(int); extern long pread(int, void *, ul, long);
extern ul strlen(const char *); extern void *memcpy(void *, const void *, ul); extern void *memset(void *, int, ul); extern void *malloc(ul);
extern int getpid(void); extern long syscall(long, ...); extern int sched_yield(void); extern int nanosleep(const void *, void *); extern int sscanf(const char *, const char *, ...);
extern void *dlsym(void *, const char *); extern int fprintf(void *, const char *, ...); extern int fflush(void *); extern void *stderr;
extern int pthread_create(ul *, void *, void *(*)(void *), void *); extern int pthread_mutex_lock(void *); extern int pthread_mutex_unlock(void *);
#define LOG(...) do { fprintf(stderr, "[idemu-hmi] " __VA_ARGS__); fflush(stderr); } while (0)
#include "chan_guest.h"
static u32 *tramp_next;
static void unprotect(void *p) { mprotect((void *)((ul)p & ~4095ul), 8192, 7); }
static void flush(void *a, ul n) { __builtin___clear_cache((char *)a, (char *)a + n); }
static void *hook(const char *sym, void *repl) {
  u32 *f = dlsym(0, sym); if (!f) { LOG("sem %s\n", sym); return 0; }
  if (!tramp_next) tramp_next = mmap(0, 1 << 16, 7, 0x22, -1, 0);
  u32 *t = tramp_next; tramp_next += 16;
  int lit = 8; ul *lits = (ul *)(t + lit);
  for (int i = 0; i < 4; i++) {
    u32 ins = f[i];
    if ((ins & 0x9f000000) == 0x90000000) {  // adrp
      long imm = (long)(((ins >> 5) & 0x7ffff) << 2 | ((ins >> 29) & 3));
      if (imm & (1l << 20)) imm -= 1l << 21;
      ul pg = ((ul)(f + i) & ~4095ul) + (imm << 12);
      *lits = pg; t[i] = 0x58000000 | (((u32)((u32 *)lits - (t + i)) & 0x7ffff) << 5) | (ins & 31); lits++;
    } else if ((ins & 0x9f000000) == 0x10000000 || (ins & 0xfc000000) == 0x14000000 || (ins & 0xfc000000) == 0x94000000 ||
               (ins & 0x7e000000) == 0x34000000 || (ins & 0x7e000000) == 0x36000000 || (ins & 0xff000010) == 0x54000000 || (ins & 0x3b000000) == 0x18000000) {
      LOG("%s: instrucao relativa ao PC %08x, sem hook\n", sym, ins); return 0;
    } else t[i] = ins;
  }
  t[4] = 0x58000050; t[5] = 0xd65f0200; *(ul *)(t + 6) = (ul)(f + 4);  // ldr x16, +8; ret x16; volta
  flush(t, 64);
  unprotect(f); f[0] = 0x58000050; f[1] = 0xd65f0200; *(ul *)(f + 2) = (ul)repl; flush(f, 16);
  return t;
}
static void ret_const(const char *sym, u32 v) {
  u32 *f = dlsym(0, sym); if (!f) { LOG("sem %s\n", sym); return; }
  unprotect(f); f[0] = 0x52800000 | (v << 5); f[1] = 0xd65f03c0; flush(f, 8);
}
// troca "mov wN, #ms" dentro de uma função: os tempos de espera por centrais que não existem aqui
static void patch_timer(const char *sym, u32 bytes, u32 from, u32 to) {
  u32 *f = dlsym(0, sym); if (!f) { LOG("sem %s\n", sym); return; }
  int n = 0; unprotect(f); unprotect(f + 1024 > f ? f + 256 : f);
  for (u32 i = 0; i < bytes / 4; i++) if ((f[i] & 0xffffffe0) == (0x52800000 | (from << 5))) { f[i] = 0x52800000 | (to << 5) | (f[i] & 31); n++; }
  flush(f, bytes); LOG("%s: %d tempo(s) trocado(s)\n", sym, n);
}
// --- instâncias
static void *ccs[4]; static int nccs;
static void (*o_ccs)(void *, u8, u8, u8, u8);
static void h_ccs(void *t, u8 a, u8 b, u8 c, u8 d) { o_ccs(t, a, b, c, d); if (nccs < 4) ccs[nccs++] = t; LOG("CCS %p %d %d %d %d\n", t, a, b, c, d); }
static int (*o_touch)(void *, void *); static int h_touch(u8 *t, void *e) { t[0x1a] = 1; return o_touch(t, e); }
static int (*o_key)(void *, u32, u8); static int h_key(u8 *t, u32 k, u8 p) { t[0x1a] = 1; return o_key(t, k, p); }
static void *clockdev, *climdev;
static void (*o_clock)(void *); static void h_clock(void *t) { o_clock(t); clockdev = t; LOG("relogio %p\n", t); }
static void (*o_clim)(void *); static void h_clim(void *t) { o_clim(t); climdev = t; LOG("clima %p\n", t); }
// tema: sem o serviço de My Modes o HMI cairia no primeiro da lista (Unicorn, Artmode...)
static char want_color[32] = "Adaptive"; static void *colordev;
struct cxxstr { char *p; ul n; char buf[16]; };
static void (*o_color)(void *, struct cxxstr *);
static void h_color(void *t, struct cxxstr *in) { colordev = t; struct cxxstr x; x.p = want_color; x.n = strlen(want_color); o_color(t, &x); }
static void (*p_time)(void *, void *); static void (*p_temp)(void *, void *);
// botões + e - do clima: sem a central, o pedido volta como estado para o HMI
static void (*p_conv)(void *out, const void *in);  // retorna em x8
static void h_settemp(void *t, void **v) {
  u8 *b = v[0], *e = v[1]; int n = (e - b) / 12; if (n <= 0 || n > 8) return;
  static u8 el[8][32];
  for (int i = 0; i < n; i++) { void *in = b + i * 12; register void *x8 __asm__("x8") = el[i]; register void *x0 __asm__("x0") = in;
    __asm__ volatile("blr %2" : "+r"(x0) : "r"(x8), "r"(p_conv) : "x1","x2","x3","x4","x5","x6","x7","x9","x10","x11","x12","x13","x14","x15","x16","x17","x30","memory"); }
  void *vec[3] = { el, el[n], el[n] }; p_temp(t, vec);
}
static void (*p_rot)(void *, u16, u8, u32, u32, u32, u32);
static void (*p_key)(void *, u32, u8, u8, int);
static void (*p_btn)(void *, u32, u32, u32, u32, u32, u32, u32, u32);
// --- fila: thread do canal -> thread do HMI
#define QN 256
static volatile u32 qh, qt; static char q[QN][32];
static u16 pos = 1000; static u8 seq;
static void run(const char *l) {
  int a = 0, b = 0, c = 0, d = 0, e = 0, f = 0; void *dev = ccs[0];
  if (l[0] == 'T') {       // T ano mes dia hora minuto dia-da-semana
    if (!clockdev || !p_time) return;
    sscanf(l + 1, "%d %d %d %d %d %d", &a, &b, &c, &d, &e, &f);
    u8 w[64]; memset(w, 0, sizeof w); w[0] = 1; *(u16 *)(w + 2) = a; w[4] = 1; w[0x10] = f; w[0x18] = c; w[0x19] = b; w[0x1a] = e; w[0x1b] = d;
    p_time(clockdev, w); return;
  }
  if (l[0] == 'C') {       // C <tema>
    int n = 0; const char *q = l + 1; while (*q == ' ') q++; while (q[n] && n < 31) { want_color[n] = q[n]; n++; } want_color[n] = 0;
    if (colordev) { struct cxxstr x; x.p = want_color; x.n = strlen(want_color); o_color(colordev, &x); } return;
  }
  if (l[0] == 'c') {       // c <décimos de grau esquerda> <direita>
    if (!climdev || !p_temp) return;
    sscanf(l + 1, "%d %d %d", &a, &b, &c);
    static u8 el[4][32]; for (int i = 0; i < 2; i++) { memset(el[i], 0, 32); el[i][0] = c; el[i][0x10] = i + 1; *(float *)(el[i] + 0x18) = (i ? b : a) / 10.0f; }
    void *vec[3] = { el, el + 2, el + 2 }; p_temp(climdev, vec); return;
  }
  if (!dev) { LOG("sem CCS\n"); return; }
  static int seeded; if (!seeded) { seeded = 1; p_rot(dev, pos, seq++, 0, 0, 0, 0); }  // a primeira posição só serve de referência
  switch (l[0]) {
    case 'r': sscanf(l + 1, "%d", &a); pos += a; p_rot(dev, pos, seq++, 0, 0, 0, 0); break;
    case 'p': sscanf(l + 1, "%d %d %d", &a, &b, &c); p_rot(dev, pos, seq++, a, b, c, 0); break;
    case 'b': { u32 o[8]; for (int i = 0; i < 8; i++) o[i] = 5; sscanf(l + 1, "%d %d", &a, &b); if (a >= 0 && a < 8) o[a] = b; p_btn(dev, o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7]); } break;
    case 'k': sscanf(l + 1, "%d %d %d %d", &a, &b, &c, &d); p_key(dev, a, b, c, d); break;
  }
}
static void (*o_frame)(void *, void *);
static void h_frame(void *t, void *x) {
  while (qt != qh) { run(q[qt % QN]); __atomic_store_n(&qt, qt + 1, __ATOMIC_RELEASE); }
  o_frame(t, x);
}
static void *reader(void *x) {
  Ch *c = ch_open(2); char l[32]; int n = 0; LOG("canal de entrada pronto\n");
  for (;;) {
    char b; get(c, &b, 1);
    if (b != '\n') { if (n < 31) l[n++] = b; continue; }
    l[n] = 0; n = 0;
    if (qh - qt < QN) { memcpy(q[qh % QN], l, 32); __atomic_store_n(&qh, qh + 1, __ATOMIC_RELEASE); }
  }
}
__attribute__((constructor)) static void init(void) {
  if (!dlsym(0, "_ZN13CHmiCCSDevice19processRotaryActionEthC_ERotaryPushButton")) {}
  o_ccs = hook("_ZN13CHmiCCSDeviceC2Ebbbb", h_ccs);
  o_touch = hook("_ZN36CHmiDisplayAndEarlyVideoInputHandler12onTouchEventERKSt10shared_ptrI10CTouchDataE", h_touch);
  o_key = hook("_ZN36CHmiDisplayAndEarlyVideoInputHandler13onCCSKeyEventEjb", h_key);
  o_frame = hook("_ZN20CHmiGraphicsMainloop12onFrameTimerEP9CPrcTimer", h_frame);
  ret_const("_ZNK13CHmiCCSDevice10isHMIInUseEv", 1);
  o_clock = hook("_ZN3car4core17CDevCarIcTimeDateC2Ev", h_clock);
  o_color = hook("_ZN3car7mymodes18CommonColorService11setHmiColorERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE", h_color);
  o_clim = hook("_ZN3car7climate16DevClimateMasterC2Ev", h_clim);
  p_conv = dlsym(0, "_ZN3car7climate22DevClimateMasterMapper7convertERKNS0_18CStatusTemperatureE");
  hook("_ZN3car7climate16DevClimateMaster22setAbsoluteTemperatureERKSt6vectorINS0_18CStatusTemperatureESaIS3_EE", h_settemp);
  patch_timer("_ZN18CEarlyVideoService25startEarlyHmiTimeoutTimerEv", 732, 0x7530, 200);
  patch_timer("_ZN22CDevWelcomeGoodbyeSync21startStopTriggerTimerEbPKc", 1000, 0x7530, 500);
  p_time = dlsym(0, "_ZN3car4core17CDevCarIcTimeDate17onPxyShowTimeDateERKN2de3bmw17infotainmenttypes17InfotainmentTypes19ShowTimeDateWrapperE");
  p_temp = dlsym(0, "_ZN3car7climate16DevClimateMaster19onStatusTemperatureERKSt6vectorIN2de3bmw12infotainment7climate18climatemastertypes18ClimateMasterTypes17StatusTemperatureESaIS9_EE");
  p_rot = dlsym(0, "_ZN13CHmiCCSDevice19processRotaryActionEth17ERotaryPushButton17ERotaryDeflection15ERotaryOverFlow25ERotaryAccelerationContol");
  p_key = dlsym(0, "_ZN13CHmiCCSDevice16dispatchKeyEventEjbbi");
  p_btn = dlsym(0, "_ZN13CHmiCCSDevice19processButtonActionE16EButtonOperationS0_S0_S0_S0_S0_S0_S0_");
  LOG("hooks ok rot=%p key=%p frame=%p\n", p_rot, p_key, o_frame);
  ul th; pthread_create(&th, 0, reader, 0);
}

// libfastclock.so (LD_PRELOAD no guest do iDrive 7): clock_gettime e gettimeofday sem chamar o kernel.
// O guest usa o HPET como relógio (o kernel não oferece o TSC) e cada leitura custa um syscall + um acesso MMIO ao QEMU, ≈ 15 µs.
// Aqui o tempo vem do rdtsc, ajustado a cada 500 ms contra o relógio real (um syscall) para não derivar.
// Sem libc: o mesmo código serve ao HMI e aos serviços.
typedef unsigned long u64; typedef long i64; typedef unsigned int u32;
struct ts { i64 sec, nsec; };
struct tv { i64 sec, usec; };
static inline u64 rdtsc(void) { u32 lo, hi; __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi)); return ((u64)hi << 32) | lo; }
static long sys_cg(long id, struct ts *t) { long r; __asm__ volatile("syscall" : "=a"(r) : "0"(228L), "D"(id), "S"(t) : "rcx", "r11", "memory"); return r; }
// estado de calibração, protegido por seqlock (ver rd/wr)
static volatile u64 ver;
static u64 tsc0, mono0, real0, mult = 1ull << 32;     // mult: ns por tick em ponto fixo 32.32
static volatile int lock; static volatile u64 last_ns;
#define MAXAGE 500000000ull                            // re-sincroniza depois de 500 ms
static void resync(void) {
  if (__sync_lock_test_and_set(&lock, 1)) return;
  struct ts m, r; u64 a = rdtsc(); sys_cg(1, &m); sys_cg(0, &r); u64 b = rdtsc(); u64 t = a + (b - a) / 2;
  u64 mn = (u64)m.sec * 1000000000ull + m.nsec, rl = (u64)r.sec * 1000000000ull + r.nsec;
  u64 nm = mult;
  if (tsc0 && t > tsc0 + 50000000ull && mn - mono0 < 4000000000ull) {   // taxa nova = (relógio real) / (ticks), só se plausível (0,8x a 1,25x); < 4 s cabe em 64 bits
    u64 est = ((mn - mono0) << 32) / (t - tsc0);
    if (est > (4ull << 30) / 5 && est < (5ull << 30) / 4) nm = est;
  }
  __sync_synchronize(); ver++; __sync_synchronize();
  tsc0 = t; mono0 = mn; real0 = rl; mult = nm;
  __sync_synchronize(); ver++; __sync_synchronize();
  __sync_lock_release(&lock);
}
static u64 now_ns(int real) {
  for (;;) {
    u64 v = ver, t = rdtsc();
    if (v & 1) continue;
    u64 a = tsc0, m = mono0, r = real0, k = mult; __sync_synchronize();
    if (v != ver) continue;
    if (!a || t - a > MAXAGE) { resync(); continue; }
    u64 d = (u64)(((unsigned __int128)(t - a) * k) >> 32);
    return (real ? r : m) + d;
  }
}
// nunca devolve um valor menor que o anterior (duas threads podem ler com calibrações diferentes)
static u64 mono(int real) {
  u64 n = now_ns(real), prev = __atomic_load_n(&last_ns, __ATOMIC_RELAXED);
  if (!real) { while (n > prev && !__atomic_compare_exchange_n(&last_ns, &prev, n, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {} if (n < prev) n = prev; }
  return n;
}
__attribute__((visibility("default"))) int clock_gettime(int id, struct ts *t) {
  int real = (id == 0 || id == 5);
  if (!(real || id == 1 || id == 4 || id == 6 || id == 7)) return (int)sys_cg(id, t);
  u64 n = mono(real); t->sec = n / 1000000000ull; t->nsec = n % 1000000000ull; return 0;
}
__attribute__((visibility("default"))) int gettimeofday(struct tv *t, void *tz) {
  (void)tz; if (!t) return 0; u64 n = mono(1); t->sec = n / 1000000000ull; t->usec = (n % 1000000000ull) / 1000; return 0;
}

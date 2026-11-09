// LD_PRELOAD: registra em /tmp/spy.<pid>.log os bytes enviados/recebidos em sockets unix (protocolo local do vsomeip).
typedef unsigned long size_t; typedef long ssize_t;
extern void *dlsym(void*, const char*); extern int open(const char*, int, ...); extern int snprintf(char*, size_t, const char*, ...);
extern int getpid(void); extern int getsockopt(int,int,int,void*,unsigned*);
struct iov { void *b; size_t l; }; struct mh { void *n; unsigned nl; struct iov *iov; size_t il; void *c; size_t cl; int f; };
#define RTLD_NEXT ((void*)-1L)
static int lf = -1;
static void logb(const char *tag, int fd, const void *p, long n) {
  if (n <= 0) return; unsigned ty = 0, l = 4; if (getsockopt(fd, 1, 3, &ty, &l) || ty != 1) return;
  static ssize_t (*w)(int, const void*, size_t); if (!w) w = dlsym(RTLD_NEXT, "write");
  if (lf < 0) { char nm[64]; snprintf(nm, sizeof nm, "/tmp/spy.%d.log", getpid()); static int (*op)(const char*, int, ...); if (!op) op = dlsym(RTLD_NEXT, "open"); lf = op(nm, 0x441, 0666); }
  char b[4096]; int k = snprintf(b, sizeof b, "%s fd%d n=%ld:", tag, fd, n); const unsigned char *u = p;
  for (long i = 0; i < n && i < 120 && k < 4000; i++) k += snprintf(b + k, 8, " %02x", u[i]);
  b[k++] = '\n'; w(lf, b, k);
}
ssize_t send(int fd, const void *p, size_t n, int f) { static ssize_t (*r)(int, const void*, size_t, int); if (!r) r = dlsym(RTLD_NEXT, "send"); ssize_t x = r(fd, p, n, f); logb("TX", fd, p, x); return x; }
ssize_t write(int fd, const void *p, size_t n) { static ssize_t (*r)(int, const void*, size_t); if (!r) r = dlsym(RTLD_NEXT, "write"); ssize_t x = r(fd, p, n); if (fd != lf) logb("TX", fd, p, x); return x; }
ssize_t sendmsg(int fd, const struct mh *m, int f) { static ssize_t (*r)(int, const struct mh*, int); if (!r) r = dlsym(RTLD_NEXT, "sendmsg"); ssize_t x = r(fd, m, f); if (x > 0) { long left = x; for (size_t i = 0; i < m->il && left > 0; i++) { long c = m->iov[i].l < (size_t)left ? m->iov[i].l : left; logb("TX", fd, m->iov[i].b, c); left -= c; } } return x; }
ssize_t recv(int fd, void *p, size_t n, int f) { static ssize_t (*r)(int, void*, size_t, int); if (!r) r = dlsym(RTLD_NEXT, "recv"); ssize_t x = r(fd, p, n, f); logb("RX", fd, p, x); return x; }
ssize_t read(int fd, void *p, size_t n) { static ssize_t (*r)(int, void*, size_t); if (!r) r = dlsym(RTLD_NEXT, "read"); ssize_t x = r(fd, p, n); if (fd != lf) logb("RX", fd, p, x); return x; }
ssize_t recvmsg(int fd, struct mh *m, int f) { static ssize_t (*r)(int, struct mh*, int); if (!r) r = dlsym(RTLD_NEXT, "recvmsg"); ssize_t x = r(fd, m, f); if (x > 0) { long left = x; for (size_t i = 0; i < m->il && left > 0; i++) { long c = m->iov[i].l < (size_t)left ? m->iov[i].l : left; logb("RX", fd, m->iov[i].b, c); left -= c; } } return x; }

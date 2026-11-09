// libipc.so.1 falso para o ioclcproxy do RSE: no lugar do ipcServer + HDLC (/dev/ttyS0) + controlador de E/S real,
// ipc_open devolve um socketpair e um processo filho faz o papel do IOC (mensagens de 40 bytes: A5 wur ?? pwf seq16 com cmd len ...).
// Registra tudo em /tmp/ioc.log. Parâmetros por variáveis de ambiente: IOC_WUR, IOC_PWF, IOC_COM.
typedef unsigned long size_t; typedef long ssize_t;
extern int socketpair(int, int, int, int[2]); extern int fork(void); extern ssize_t read(int, void*, size_t); extern ssize_t write(int, const void*, size_t);
extern int close(int); extern int open(const char*, int, ...); extern int snprintf(char*, size_t, const char*, ...); extern int fcntl(int, int, ...);
extern int poll(void*, unsigned long, int); extern void _exit(int); extern char *getenv(const char*); extern int atoi(const char*);
extern int prctl(int, ...); extern int getppid(void);
struct pfd { int fd; short ev, rev; };
static int lf = -1;
static void lg(const char *tag, const unsigned char *p, int n) {
  char b[512]; int k = snprintf(b, sizeof b, "%s n=%d:", tag, n);
  for (int i = 0; i < n && i < 48; i++) k += snprintf(b + k, 8, " %02x", p[i]);
  b[k++] = '\n'; if (lf >= 0) write(lf, b, k);
}
static int cv[3] = { -1, -1, -1 };
static void ctl(void) {
  int f = open("/tmp/ioc.ctl", 0); if (f < 0) return; char b[64]; int n = (int)read(f, b, 63); close(f); if (n <= 0) return; b[n] = 0;
  int k = 0, v = 0, in = 0; for (int i = 0; i <= n && k < 3; i++) { if (b[i] >= '0' && b[i] <= '9') { v = v * 10 + b[i] - '0'; in = 1; } else if (in) { cv[k++] = v; v = 0; in = 0; } }
}
static unsigned char env_u8(const char *n, int d) { char *v = getenv(n); int x = v ? atoi(v) : d; int i = n[4] == 'W' ? 0 : n[4] == 'P' ? 1 : 2; if (cv[i] >= 0) x = cv[i]; return (unsigned char)x; }
static void ioc(int fd) {
  prctl(1, 9); // PR_SET_PDEATHSIG SIGKILL
  lf = open("/tmp/ioc.log", 0x441, 0666);
  unsigned short seq = 0; unsigned char m[40]; int tick = 0;
  for (;;) {
    struct pfd p = { fd, 1, 0 };
    int r = poll(&p, 1, 1000);
    if (r > 0 && (p.rev & 1)) { unsigned char b[300]; ssize_t n = read(fd, b, sizeof b); if (n <= 0) _exit(0); lg("APP->IOC", b, (int)n);
      if (n >= 9 && b[0] == 0xA5) { unsigned char a[40]; for (int i = 0; i < 40; i++) a[i] = 0; a[0] = 0xA5; a[1] = env_u8("IOC_WUR", 10); a[3] = env_u8("IOC_PWF", 5); a[6] = env_u8("IOC_COM", 3);
        if (b[7] == 2) { a[7] = 2; a[8] = 16; a[9 + 7] = 1; } else { a[7] = 0x55; a[8] = 1; a[9] = b[7]; }
        seq++; a[4] = seq & 0xff; a[5] = seq >> 8; write(fd, a, 40); lg("IOC->APP(reply)", a, 40); } }
    if (getppid() == 1) _exit(0);
    ctl();
    for (int i = 0; i < 40; i++) m[i] = 0;
    m[0] = 0xA5; m[1] = env_u8("IOC_WUR", tick < 30 ? 5 : 10); m[2] = 0; m[3] = env_u8("IOC_PWF", 5);
    seq++; m[4] = seq & 0xff; m[5] = seq >> 8; m[6] = env_u8("IOC_COM", 3); m[7] = 0; m[8] = 6; m[9] = 0xff; m[10] = 0x7f; m[11] = 0xff; m[12] = 0xff; m[13] = 0xff; m[14] = 0x7f;
    tick++; write(fd, m, 40); if (tick < 4) lg("IOC->APP", m, 40);
  }
}
int ipc_open(const char *name, int flags) {
  int sv[2]; if (socketpair(1, 5 /*SOCK_SEQPACKET*/, 0, sv)) return -1;
  if (fork() == 0) { close(sv[0]); ioc(sv[1]); _exit(0); }
  close(sv[1]); fcntl(sv[0], 4 /*F_SETFL*/, 0x800 /*O_NONBLOCK*/);
  return sv[0];
}
ssize_t ipc_read(int fd, void *b, size_t n) { return read(fd, b, n); }
ssize_t ipc_write(int fd, const void *b, size_t n) { return write(fd, b, n); }
int ipc_close(int fd) { return close(fd); }
int ipc_shutdown_request(int fd) { return 0; }

// Interposição do CodingBase::getBits para o ioclcproxy: força o service pack (byte 3, 7 bits) em IOC_SP (padrão 3).
extern void *dlsym(void*, const char*);
int _ZNK10CodingBase7getBitsEihi(void *self, int a, unsigned char b, int c) {
  static int (*real)(void*, int, unsigned char, int);
  if (!real) real = dlsym((void*)-1L, "_ZNK10CodingBase7getBitsEihi");
  if (a == 3 && b == 7 && c == 0) { char *v = getenv("IOC_SP"); return v ? atoi(v) : 3; }
  return real(self, a, b, c);
}

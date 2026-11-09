/* IDEmu - transporte io-ipc "virtual" para o V850.
 *
 * O io-ipc original carrega um transporte (ioipc-spi-omap543x.so) que conversa com o V850 por SPI+DMA+GPIO.
 * Esta biblioteca exporta a MESMA interface (init / tx / destroy) mas leva os quadros por uma UART virtual
 * (UART4 = /dev/ser6) até o host, onde o V850 é emulado (idemu/v850.py).  O decodificador (ioipc-ipc-hp-decoder.so)
 * e o io-ipc continuam os originais e não são alterados.
 *
 * Quadro na UART:  A5 5A <tipo:1> <len:2 LE> <dados>
 *   guest->host: 1 = mensagem io-ipc enviada (tx)   0x10 = texto de depuração   0 = hello (cfg do canal)
 *   host->guest: 2 = mensagem io-ipc recebida (rx)
 *
 * Pontes TCP (servidor MOST falso): o guest escuta em 127.0.0.1:5555 (SIPC do `most`, endereço em $IPC_IP_ADDRESS) e em
 * 127.0.0.1:5556 (DSI do papel MOSTSubSystemServer) e tunela cada conexão pela mesma UART (conn = 0..15):
 *   guest->host: 0x20 [conn][porta:2 BE] conectou   0x21 [conn][bytes] recebidos   0x23 [conn] desconectou
 *   host->guest: 0x22 [conn][bytes] para o cliente   0x23 [conn] fechar
 * Servicebroker (DSI): host->guest 0x24 = listar interfaces registradas (resultado em texto 0x10);
 *   0x25 [porta:2][maior:2][menor:2][a:4][nome\0] = registrar a interface TCP `nome` no servicebroker local.
 */
typedef unsigned int u32; typedef unsigned char u8; typedef unsigned short u16;
#define NULL ((void*)0)
extern int open(const char*, int, ...); extern long read(int, void*, unsigned long); extern long write(int, const void*, unsigned long);
extern void *memcpy(void*, const void*, unsigned long); extern void *memset(void*, int, unsigned long);
extern int usleep(unsigned); extern int snprintf(char*, unsigned long, const char*, ...);
extern int pthread_create(void*, const void*, void *(*)(void*), void*);
extern int pthread_mutex_lock(void*); extern int pthread_mutex_unlock(void*); extern int pthread_mutex_init(void*, const void*);
extern int *__get_errno_ptr(void);
extern void *dlopen(const char*, int); extern void *dlsym(void*, const char*);
/* libsocket é resolvida em tempo de execução (o io-ipc não a tem como dependência) */
static int (*socket)(int, int, int); static int (*bind)(int, const void*, unsigned); static int (*listen)(int, int);
static int (*accept)(int, void*, unsigned*); static int (*setsockopt)(int, int, int, const void*, unsigned); static int (*close_)(int);
static long (*recv)(int, void*, unsigned long, int); static long (*send)(int, const void*, unsigned long, int); static int (*shutdown)(int, int);
extern int close(int);
static int sock_init(void) {
    void *h = dlopen("libsocket.so.3", 0x102);   /* RTLD_NOW | RTLD_GLOBAL */
    if (!h) return -1;
    socket = dlsym(h, "socket"); bind = dlsym(h, "bind"); listen = dlsym(h, "listen"); accept = dlsym(h, "accept");
    setsockopt = dlsym(h, "setsockopt"); recv = dlsym(h, "recv"); send = dlsym(h, "send"); shutdown = dlsym(h, "shutdown");
    return (socket && bind && listen && accept && setsockopt && recv && send && shutdown) ? 0 : -2;
}
/* implementados pelo io-ipc */
extern int ioipc_bp_alloc(u32 size, void *desc);
extern int ioipc_bp_wait_alloc(u32 size, void *desc);
extern int ioipc_bp_free(void *desc);

typedef int (*rxcb_t)(void *ctx, void *desc);
typedef void (*stcb_t)(void *ctx, u32 st);
struct ops { void *f0; void *f4; rxcb_t rx; void *fc; stcb_t status; };

static u8 *tc_;                 /* cópia do tchannel */
static int fd_ = -1;
static long long mtx_[4] __attribute__((aligned(8)));       /* mutex de escrita (pthread_mutex_t cabe em 16..24 bytes; zerado = inicializador estático QNX) */
static u8 desc_[5][40] __attribute__((aligned(8)));
static int rxn_;
#define NCONN 16
static volatile int cfd_[NCONN];   /* conexões TCP aceitas (fd ou 0 = livre) */

static void put(int type, const void *d, int n) {
    u8 h[5]; const u8 *p = d;
    if (fd_ < 0) return;
    h[0] = 0xA5; h[1] = 0x5A; h[2] = type; h[3] = n & 255; h[4] = n >> 8;
    pthread_mutex_lock(mtx_);
    write(fd_, h, 5);
    while (n > 0) { long w = write(fd_, p, n); if (w <= 0) break; p += w; n -= w; }
    pthread_mutex_unlock(mtx_);
}
static void dbg(const char *s) { int n = 0; while (s[n]) n++; put(0x10, s, n); }
static void dbgf(const char *f, u32 a, u32 b, u32 c) { char t[160]; snprintf(t, sizeof t, f, a, b, c); dbg(t); }

/* bytes devolvidos ao fluxo (ressincronizacao depois de um quadro corrompido) */
static u8 pb_[0x2000 + 64]; static int pb_n_, pb_i_;
static int rdfull(void *b, int n) {
    u8 *p = b;
    while (n > 0 && pb_i_ < pb_n_) { *p++ = pb_[pb_i_++]; n--; }
    while (n > 0) { long r = read(fd_, p, n); if (r <= 0) { usleep(2000); continue; } p += r; n -= r; }
    return 0;
}
static void hexdump_dbg(const char *tag, const u8 *p, int n) {
    static const char hx[] = "0123456789abcdef"; char t[200]; int i = 0;
    while (i < n) {
        int k = 0, m = n - i > 48 ? 48 : n - i, j;
        for (j = 0; tag[j] && k < 40; j++) t[k++] = tag[j];
        t[k++] = ' ';
        for (j = 0; j < m; j++) { t[k++] = hx[p[i + j] >> 4]; t[k++] = hx[p[i + j] & 15]; }
        t[k] = 0; dbg(t); i += m;
    }
}

struct cargs { int conn, fd, port; };
static void *conn_thread(void *arg) {
    static u8 bufs[NCONN][4004] __attribute__((aligned(8)));
    struct cargs ca = *(struct cargs *)arg; u8 *b = bufs[ca.conn] + 4; long n; int one = 1;
    setsockopt(ca.fd, 6, 1, &one, 4);
    { u8 o[3]; o[0] = ca.conn; o[1] = ca.port >> 8; o[2] = ca.port & 255; put(0x20, o, 3); }
    while ((n = recv(ca.fd, b, 4000, 0)) > 0) { b[-1] = ca.conn; put(0x21, b - 1, n + 1); }
    cfd_[ca.conn] = 0; close(ca.fd);
    { u8 o = ca.conn; put(0x23, &o, 1); }
    return NULL;
}
static void *listen_thread(void *arg) {
    static struct cargs cas[NCONN]; int port = (int)(long)arg;
    u8 sa[16] __attribute__((aligned(4))); int one = 1, s;
    { int r = sock_init(); if (r) { dbgf("tcp: libsocket indisponivel (%d)", r, 0, 0); return NULL; } }
    for (;;) {
        s = socket(2, 1, 0);
        if (s < 0) { dbgf("tcp: socket() falhou errno=%u", *__get_errno_ptr(), 0, 0); usleep(1000000); continue; }
        setsockopt(s, 0xffff, 4, &one, 4);
        memset(sa, 0, 16); sa[0] = 16; sa[1] = 2; sa[2] = port >> 8; sa[3] = port & 255; sa[4] = 127; sa[7] = 1;
        if (bind(s, sa, 16) || listen(s, 4)) { dbgf("tcp: bind/listen falhou errno=%u", *__get_errno_ptr(), 0, 0); close(s); usleep(1000000); continue; }
        dbgf("tcp: escutando 127.0.0.1:%u", port, 0, 0);
        for (;;) {
            int c = accept(s, NULL, NULL), i; void *th[2];
            if (c < 0) { usleep(200000); continue; }
            for (i = 0; i < NCONN && cfd_[i]; i++) ;
            if (i == NCONN) { close(c); continue; }
            cfd_[i] = c; cas[i].conn = i; cas[i].fd = c; cas[i].port = port;
            pthread_create(th, NULL, conn_thread, &cas[i]);
        }
    }
    return NULL;
}

/* --- servicebroker (DSI) ------------------------------------------------------------------------ */
static void *sbh_;
static int sb_fd(void) {
    static int fd = -1;
    if (fd < 0) fd = open("/srv/servicebroker", 0x2001);
    if (!sbh_) sbh_ = dlopen("libsys_dsi_servicebroker.cpp-ne.so.4", 0x102);
    return fd;
}
static void sb_list(void) {
    static u8 buf[48 * 0x104 + 0x200] __attribute__((aligned(8))); int cnt = 0, rc, i, fd = sb_fd();
    int (*getlist)(int, void *, int, int *);
    if (fd < 0 || !sbh_) { dbgf("sb: sem acesso (fd=%d)", fd, 0, 0); return; }
    getlist = dlsym(sbh_, "SBGetInterfaceList");
    memset(buf, 0, sizeof buf);
    rc = getlist(fd, buf, 48, &cnt);
    dbgf("sb: lista rc=%d cnt=%d", rc, cnt, 0);
    for (i = 0; i < cnt && i < 48; i++) hexdump_dbg("sb-if", buf + 0x104 * i, 0x60);
}
static void sb_register(const u8 *p, int n) {
    int fd = sb_fd(); u8 id[16]; int rc;
    int (*reg)(int, const char *, unsigned, unsigned, unsigned, unsigned, void *);
    if (n < 11 || fd < 0 || !sbh_) { dbgf("sb: registro impossivel (fd=%d)", fd, 0, 0); return; }
    reg = dlsym(sbh_, "SBRegisterInterfaceTCP");
    memset(id, 0, sizeof id);
    rc = reg(fd, (const char *)p + 10, p[2] << 8 | p[3], p[4] << 8 | p[5], (unsigned)(p[6] << 24 | p[7] << 16 | p[8] << 8 | p[9]), p[0] << 8 | p[1], id);
    dbgf("sb: registro rc=%d errno=%d", rc, *__get_errno_ptr(), 0);
    hexdump_dbg("sb-id", id, 8);
}

static u32 skip_, big_, bad_, frames_;
static u8 lastb_[0x1010], lasth_[3]; static int lastn_;
static void *rx_thread(void *arg) {
    u8 h[3]; static u8 buf[0x1000 + 16] __attribute__((aligned(8))); static u8 tmp[0x2000 + 64]; int st = 0, synced = 0;
    (void)arg;
    for (;;) {
        if (!synced) {
            u8 b;
            /* sincroniza em A5 5A */
            rdfull(&b, 1);
            if (st == 0) { if (b == 0xA5) st = 1; else { skip_++; if (skip_ == 1) { dbgf("rx: DIAG quadro anterior tipo=%x n=%u", lasth_[0], lastn_, 0); hexdump_dbg("prev", lastb_, lastn_ > 96 ? 96 : lastn_); }
                if (skip_ <= 40) dbgf("rx: byte fora de quadro %x (descartados=%u)", b, skip_, 0); } continue; }
            if (b != 0x5A) { skip_++; if (skip_ <= 20) dbgf("rx: A5 sem 5A (%x)", b, 0, 0); st = (b == 0xA5); continue; }
            st = 0;
        }
        synced = 0;
        rdfull(h, 3);
        { int n = h[1] | (h[2] << 8);
          if (n > 0x1000) { dbgf("rx: quadro grande %u (tipo %x)", n, h[0], 0); big_++; continue; }
          rdfull(buf, n);
          /* todo quadro host->guest termina com uma soma de 16 bits (v850.py _write). Se nao bater, o quadro chegou truncado/corrompido (o UART perde bytes sob carga):
             descarta em vez de entregar lixo ao `most` (tamanho absurdo -> alocacao de 1,5 GB -> ASSERTION em CHBByteStream.cpp:180) e reaproveita o que vier depois do proximo A5 5A. */
          { u32 sum = 0; int i, ok = n >= 2;
            if (ok) { for (i = 0; i < n - 2; i++) sum += buf[i]; ok = ((sum & 0xffff) == (u32)(buf[n - 2] | (buf[n - 1] << 8))); }
            if (!ok) {
                int k, rem = pb_n_ - pb_i_;
                bad_++;
                dbgf("rx: quadro com soma errada (tipo %x n=%u) -> ressincroniza", h[0], n, 0);
                for (k = 0; k + 1 < n; k++) if (buf[k] == 0xA5 && buf[k + 1] == 0x5A) break;
                if (k + 1 < n) {
                    int m = n - (k + 2);
                    memcpy(tmp, buf + k + 2, m); if (rem > 0) memcpy(tmp + m, pb_ + pb_i_, rem);
                    memcpy(pb_, tmp, m + rem); pb_n_ = m + rem; pb_i_ = 0;
                    synced = 1;                      /* A5 5A ja encontrado: o proximo e o cabecalho (tipo,len) */
                } else if (buf[n - 1] == 0xA5) st = 1;
                continue;
            }
            n -= 2; }
          lasth_[0] = h[0]; lasth_[1] = h[1]; lasth_[2] = h[2]; lastn_ = n; memcpy(lastb_, buf, n);
          if (++frames_ % 256 == 0) dbgf("rx: quadros=%u descartados=%u grandes=%u", frames_, skip_, big_);
          if (h[0] == 0x22 && n > 1 && buf[0] < NCONN) { int c = cfd_[buf[0]]; u8 *q = buf + 1; n--; while (c > 0 && n > 0) { long w = send(c, q, n, 0); if (w <= 0) break; q += w; n -= w; } continue; }
          if (h[0] == 0x23 && n >= 1 && buf[0] < NCONN) { int c = cfd_[buf[0]]; if (c > 0) shutdown(c, 2); continue; }
          if (h[0] == 0x24) { sb_list(); continue; }
          if (h[0] == 0x25) { sb_register(buf, n); continue; }
          if (h[0] != 2) continue;
          { void *d = desc_[rxn_]; struct ops *o = *(struct ops **)(tc_ + 0x110); int rc;
            rxn_ = (rxn_ + 1) % 5;
            memset(d, 0, 40);
            rc = ioipc_bp_alloc(0x1000, d);
            if (rc == 12) rc = ioipc_bp_wait_alloc(0x1000, d);
            if (rc) { dbgf("rx: bp_alloc rc=%u", rc, 0, 0); continue; }
            memcpy(*(u8 **)((u8 *)d + 8), buf, n);
            *(u32 *)((u8 *)d + 0x18) = n;
            rc = o->rx(*(void **)(tc_ + 0x10c), d);
            /* rc=12 (ENOMEM) = fila de recepcao do io-ipc cheia: contrapressao (tenta de novo em vez de descartar e deixar o buffer vazar,
               o que acabava matando o `most` por falta de memoria). Enquanto espera, o UART fica sem ser lido e o host segura o envio. */
            { int tries = 0; while (rc == 12 && tries < 150) { usleep(20000); tries++; rc = o->rx(*(void **)(tc_ + 0x10c), d); }
              if (tries && rc == 0) dbgf("rx: contrapressao ok apos %u tentativas", tries, 0, 0);
              if (rc == 12) { dbgf("rx: fila cheia, descartando (len %u)", n, 0, 0); ioipc_bp_free(d); continue; } }
            if (rc) dbgf("rx: rx_callback rc=%u (len %u)", rc, n, 0);
          } }
    }
    return NULL;
}

int init(void *tc, u32 ver) {
    static u8 copy[0x118] __attribute__((aligned(8))); u32 th[2];
    if (ver != 0x115) return 0x30;
    memcpy(copy, tc, 0x118); tc_ = copy;
    pthread_mutex_init(mtx_, NULL);
    fd_ = open("/dev/ser6", 2);
    if (fd_ < 0) return 2;
    put(0, copy, 0x118);
    dbgf("ioipc-idemu: init ok (ver %x)", ver, 0, 0);
    pthread_create(th, NULL, rx_thread, NULL);
    pthread_create(th, NULL, listen_thread, (void *)5555);
    pthread_create(th, NULL, listen_thread, (void *)5556);
    { struct ops *o = *(struct ops **)(tc_ + 0x110); o->status(*(void **)(tc_ + 0x10c), 1); }
    return 0;
}

int tx(void *a, void *b, void *desc, int c, int d, int e) {
    u8 *p = *(u8 **)((u8 *)desc + 8); u32 n = *(u32 *)((u8 *)desc + 0x18);
    (void)a; (void)b; (void)c; (void)d; (void)e;
    if (n > 0 && n <= 0x1000) put(1, p, n);
    ioipc_bp_free(desc);
    return 0;
}

int destroy(void *tc) { (void)tc; return 0; }

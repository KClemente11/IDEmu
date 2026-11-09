// libusb-1.0.so.0 falso, só para o devicemanager do iDrive 8: o guest não tem barramento USB, então esta biblioteca
// finge um único pen drive USB quando existir /run/idemu-usb/present (criado pelo idemuusb). Os callbacks de hotplug
// disparam dentro de libusb_handle_events_timeout_completed, como na libusb de verdade.
typedef unsigned long ul; typedef unsigned char u8; typedef unsigned short u16;
extern int open(const char *, int, ...); extern int close(int); extern long write(int, const void *, ul); extern long read(int, void *, ul);
extern int access(const char *, int); extern int usleep(unsigned); extern void *malloc(ul); extern void free(void *); extern ul strlen(const char *);
extern void *memset(void *, int, ul); extern char *strcpy(char *, const char *); extern int pipe2(int *, int); extern int poll(void *, ul, int);
extern int pthread_create(void *, const void *, void *(*)(void *), void *); extern int getpid(void); extern int snprintf(char *, ul, const char *, ...);
#define PRESENT "/run/idemu-usb/present"
static void flog(const char *s) { int fd = open("/tmp/usbfake.log", 0x441, 0644); if (fd >= 0) { char b[300]; int n = snprintf(b, sizeof b, "[libusb %d] %s\n", getpid(), s); write(fd, b, n); close(fd); } }
#define LOGF(...) do { char _b[260]; snprintf(_b, sizeof _b, __VA_ARGS__); flog(_b); } while (0)
typedef int (*HotCb)(void *, void *, int, void *);
static struct { int used, ev, flags; HotCb cb; void *ud; } hp[8];
static int pfd[2] = { -1, -1 }, last = 0, delivered = 0, inited = 0;
static void (*added_cb)(int, short, void *); static void (*removed_cb)(int, void *); static void *notif_ud;
static struct { int fd; short events; } pollfd_s; static void *pollfd_list[2];
static char devobj[64], ctxobj[64];
static int present(void) { return access(PRESENT, 0) == 0; }
static void *watcher(void *a) {
  for (;;) { usleep(200000); int s = present(); if (s != last) { last = s; if (pfd[1] >= 0) write(pfd[1], "x", 1); } }
  return 0;
}
int libusb_init(void **ctx) {
  if (!inited) {
    inited = 1; pipe2(pfd, 0x800 | 0x80000); last = delivered = present(); char th[16]; pthread_create(th, 0, watcher, 0);
    pollfd_s.fd = pfd[0]; pollfd_s.events = 1; pollfd_list[0] = &pollfd_s; pollfd_list[1] = 0;
  }
  if (ctx) *ctx = ctxobj; flog("libusb_init"); return 0;
}
void libusb_exit(void *ctx) { flog("libusb_exit"); }
int libusb_set_option(void *ctx, int opt, ...) { LOGF("set_option %d", opt); return 0; }
int libusb_hotplug_register_callback(void *ctx, int ev, int flags, int vid, int pid, int cls, HotCb cb, void *ud, int *handle) {
  int i; for (i = 0; i < 8 && hp[i].used; i++) ;
  if (i == 8) return -5;
  hp[i].used = 1; hp[i].ev = ev; hp[i].flags = flags; hp[i].cb = cb; hp[i].ud = ud; if (handle) *handle = i + 1;
  LOGF("hotplug_register ev=%d flags=%d vid=%d pid=%d cls=%d -> %d", ev, flags, vid, pid, cls, i + 1);
  if ((flags & 1) && (ev & 1) && present()) { LOGF("enumerate: ARRIVED"); cb(ctx, devobj, 1, ud); }
  return 0;
}
void libusb_hotplug_deregister_callback(void *ctx, int h) { LOGF("hotplug_deregister %d", h); if (h >= 1 && h <= 8) hp[h - 1].used = 0; }
const void **libusb_get_pollfds(void *ctx) { flog("get_pollfds"); return (const void **)pollfd_list; }
void libusb_set_pollfd_notifiers(void *ctx, void (*a)(int, short, void *), void (*r)(int, void *), void *ud) {
  added_cb = a; removed_cb = r; notif_ud = ud; flog("set_pollfd_notifiers"); if (a && pfd[0] >= 0) a(pfd[0], 1, ud);
}
int libusb_get_next_timeout(void *ctx, void *tv) { return 0; }
int libusb_handle_events_timeout_completed(void *ctx, void *tv, int *completed) {
  long tmo = 0; if (tv) { long *t = tv; tmo = t[0] * 1000 + t[1] / 1000; }
  char b[32]; struct { int fd; short ev, rev; } p = { pfd[0], 1, 0 };
  poll(&p, 1, tmo > 1000 ? 1000 : (int)tmo); while (read(pfd[0], b, sizeof b) > 0) ;
  int s = present();
  if (s != delivered) {
    delivered = s; LOGF("evento de hotplug: %s", s ? "ARRIVED" : "LEFT");
    for (int i = 0; i < 8; i++) if (hp[i].used && (hp[i].ev & (s ? 1 : 2))) { if (hp[i].cb(ctx, devobj, s ? 1 : 2, hp[i].ud)) hp[i].used = 0; }
  }
  return 0;
}
long libusb_get_device_list(void *ctx, void ***list) {
  void **l = malloc(16); int n = present() ? 1 : 0; l[0] = n ? devobj : 0; l[1] = 0; *list = l; LOGF("get_device_list -> %d", n); return n;
}
void libusb_free_device_list(void **l, int unref) { free(l); }
void *libusb_ref_device(void *d) { return d; }
void libusb_unref_device(void *d) { }
int libusb_get_device_descriptor(void *d, void *out) {
  u8 *p = out; memset(p, 0, 18); p[0] = 18; p[1] = 1; p[2] = 0x00; p[3] = 0x02; p[7] = 64; p[8] = 0x81; p[9] = 0x07; p[10] = 0x81; p[11] = 0x55; p[12] = 0x00; p[13] = 0x01;
  p[14] = 1; p[15] = 2; p[16] = 3; p[17] = 1; flog("get_device_descriptor"); return 0;
}
u8 libusb_get_bus_number(void *d) { return 1; }
int libusb_get_port_numbers(void *d, u8 *ports, int len) { if (len < 1) return -2; ports[0] = 1; return 1; }
int libusb_get_active_config_descriptor(void *d, void **cfg) {
  u8 *c = malloc(96); memset(c, 0, 96);
  c[0] = 9; c[1] = 2; c[2] = 32; c[4] = 1; c[5] = 1; c[7] = 0x80; c[8] = 50;
  *(void **)(c + 16) = c + 40; *(void **)(c + 40) = c + 56; *(int *)(c + 48) = 1;
  u8 *i = c + 56; i[0] = 9; i[1] = 4; i[5] = 8; i[6] = 6; i[7] = 0x50;
  *cfg = c; flog("get_active_config_descriptor"); return 0;
}
void libusb_free_config_descriptor(void *c) { free(c); }
int libusb_open(void *d, void **h) { *h = devobj; flog("open"); return 0; }
void libusb_close(void *h) { }
void *libusb_open_device_with_vid_pid(void *ctx, u16 v, u16 p) { LOGF("open_device_with_vid_pid %x:%x", v, p); return 0; }
int libusb_get_string_descriptor_ascii(void *h, u8 idx, unsigned char *buf, int len) {
  const char *s = idx == 1 ? "IDEmu" : idx == 2 ? "Virtual USB" : "IDEMU0001"; int n = (int)strlen(s); if (n >= len) n = len - 1; for (int k = 0; k < n; k++) buf[k] = s[k]; buf[n] = 0; return n;
}
int libusb_control_transfer(void *h, u8 rt, u8 r, u16 v, u16 i, unsigned char *d, u16 l, unsigned t) { LOGF("control_transfer rt=%x r=%x -> NOT_SUPPORTED", rt, r); return -12; }
int libusb_reset_device(void *h) { flog("reset_device"); return 0; }
const char *libusb_error_name(int e) { return "LIBUSB_ERROR"; }

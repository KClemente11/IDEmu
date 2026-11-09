// libudev.so.1 falso, só para o devicemanager do iDrive 8: descreve o pen drive USB virtual (dispositivo usb, disco e partição)
// quando existir /run/idemu-usb/present. Cada chamada vai para /tmp/usbfake.log.
typedef unsigned long ul;
extern int open(const char *, int, ...); extern int close(int); extern long write(int, const void *, ul); extern int access(const char *, int);
extern int strcmp(const char *, const char *); extern int getpid(void); extern int snprintf(char *, ul, const char *, ...); extern long read(int, void *, ul);
#define PRESENT "/run/idemu-usb/present"
static void flog(const char *s) { int fd = open("/tmp/usbfake.log", 0x441, 0644); if (fd >= 0) { char b[400]; int n = snprintf(b, sizeof b, "[libudev %d] %s\n", getpid(), s); write(fd, b, n); close(fd); } }
#define LOGF(...) do { char _b[360]; snprintf(_b, sizeof _b, __VA_ARGS__); flog(_b); } while (0)
static int present(void) { return access(PRESENT, 0) == 0; }
#define USB "/sys/devices/platform/soc/a600000.usb/xhci-hcd.0.auto/usb1/1-1"
#define IFC USB "/1-1:1.0"
#define TGT IFC "/host0/target0:0:0/0:0:0:0"
typedef struct { const char *sys, *name, *sub, *devtype, *node; } Dev;
static Dev DEVS[] = {
  { USB, "1-1", "usb", "usb_device", "/dev/bus/usb/001/002" },
  { IFC, "1-1:1.0", "usb", "usb_interface", 0 },
  { TGT "/block/sda", "sda", "block", "disk", "/dev/sda" },
  { TGT "/block/sda/sda1", "sda1", "block", "partition", "/dev/sda1" },
};
#define ND 4
typedef struct { const char *key, *val; } KV;
static char label[48] = "USB";
static void rd_label(void) { int fd = open(PRESENT, 0); if (fd >= 0) { long n = read(fd, label, 40); close(fd); if (n < 0) n = 0; label[n] = 0; for (long i = 0; i < n; i++) if (label[i] == 10) label[i] = 0; } }
static const char *prop(Dev *d, const char *k) {
  if (!strcmp(k, "DEVTYPE")) return d->devtype;
  if (!strcmp(k, "SUBSYSTEM")) return d->sub;
  if (!strcmp(k, "ID_BUS")) return "usb";
  if (!strcmp(k, "ID_VENDOR_ID")) return "0781";
  if (!strcmp(k, "ID_MODEL_ID")) return "5581";
  if (!strcmp(k, "ID_USB_DRIVER")) return d->node && d->node[5] == 's' ? "usb-storage" : "usb";
  if (!strcmp(k, "ID_PATH")) return "platform-a600000.usb-usb-0:1:1.0-scsi-0:0:0:0";
  if (!strcmp(k, "ID_FS_TYPE")) return d->devtype[0] == 'p' ? "vfat" : 0;
  if (!strcmp(k, "ID_FS_USAGE")) return d->devtype[0] == 'p' ? "filesystem" : 0;
  if (!strcmp(k, "ID_FS_LABEL")) { rd_label(); return d->devtype[0] == 'p' ? label : 0; }
  if (!strcmp(k, "BUSNUM")) return "001";
  if (!strcmp(k, "DEVNUM")) return "002";
  if (!strcmp(k, "MAJOR")) return d->devtype[0] == 'u' ? "189" : "8";
  return 0;
}
void *udev_new(void) { flog("udev_new"); return (void *)&DEVS; }
void *udev_unref(void *u) { return 0; }
void *udev_device_new_from_syspath(void *u, const char *p) {
  LOGF("new_from_syspath %s", p ? p : "(null)"); if (!present() || !p) return 0;
  for (int i = 0; i < ND; i++) if (!strcmp(DEVS[i].sys, p)) return &DEVS[i];
  return 0;
}
void *udev_device_new_from_subsystem_sysname(void *u, const char *sub, const char *n) {
  LOGF("new_from_subsystem_sysname %s %s", sub ? sub : "(null)", n ? n : "(null)"); if (!present() || !sub || !n) return 0;
  for (int i = 0; i < ND; i++) if (!strcmp(DEVS[i].sub, sub) && !strcmp(DEVS[i].name, n)) return &DEVS[i];
  return 0;
}
void *udev_device_unref(void *d) { return 0; }
const char *udev_device_get_devnode(Dev *d) { LOGF("get_devnode %s -> %s", d->name, d->node ? d->node : "(null)"); return d->node; }
const char *udev_device_get_devpath(Dev *d) { LOGF("get_devpath %s", d->name); return d->sys + 4; }
const char *udev_device_get_syspath(Dev *d) { LOGF("get_syspath %s", d->name); return d->sys; }
const char *udev_device_get_sysname(Dev *d) { LOGF("get_sysname %s", d->name); return d->name; }
const char *udev_device_get_property_value(Dev *d, const char *k) { const char *v = prop(d, k); LOGF("get_property_value %s %s -> %s", d->name, k, v ? v : "(null)"); return v; }
// enumeração
typedef struct { const char *sub; int n, ent[ND]; } Enum;
static Enum E;
typedef struct { const char *name; int next; } Ent;  // entrada de lista = índice em DEVS + 1
void *udev_enumerate_new(void *u) { E.sub = 0; E.n = 0; flog("enumerate_new"); return &E; }
void *udev_enumerate_unref(void *e) { return 0; }
int udev_enumerate_add_match_subsystem(Enum *e, const char *s) { LOGF("enumerate_add_match_subsystem %s", s); e->sub = s; return 0; }
int udev_enumerate_scan_devices(Enum *e) {
  e->n = 0; if (present()) for (int i = 0; i < ND; i++) if (!e->sub || !strcmp(DEVS[i].sub, e->sub)) e->ent[e->n++] = i;
  LOGF("enumerate_scan_devices sub=%s -> %d", e->sub ? e->sub : "(null)", e->n); return 0;
}
static struct { Enum *e; int pos; } LE[ND + 1];
void *udev_enumerate_get_list_entry(Enum *e) { if (!e->n) return 0; LE[0].e = e; LE[0].pos = 0; return &LE[0]; }
void *udev_list_entry_get_next(void *x) {
  int k = (int)((char *)x - (char *)&LE[0]) / (int)sizeof LE[0]; if (k < 0 || k >= ND || LE[k].pos + 1 >= LE[k].e->n) return 0;
  LE[k + 1].e = LE[k].e; LE[k + 1].pos = LE[k].pos + 1; return &LE[k + 1];
}
const char *udev_list_entry_get_name(void *x) { int k = (int)((char *)x - (char *)&LE[0]) / (int)sizeof LE[0]; const char *s = DEVS[LE[k].e->ent[LE[k].pos]].sys; LOGF("list_entry_get_name -> %s", s); return s; }

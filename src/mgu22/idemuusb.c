// idemuusb: pen drive virtual do iDrive 8.
// 1) Recebe do host (canal de papel 3, usb_proto.h) os arquivos da pasta escolhida e os grava em /media/<rótulo> (tmpfs).
// 2) Faz o papel do udisksd: serviço org.freedesktop.UDisks2 no barramento que o IVI usa (sessão, /run/dbus/session). O usbDaemon do firmware
//    (GetManagedObjects, InterfacesAdded, Filesystem.Mount) enxerga um pen drive FAT32 espetado e o publica ao resto do IVI.
// Teste sem o host: grave o rótulo em /tmp/idemuusb.attach (a pasta /media/<rótulo> já com os arquivos) ou crie /tmp/idemuusb.eject.
#include "chan.h"
#include "usb_proto.h"
typedef unsigned long ul; typedef unsigned u32; typedef unsigned short u16; typedef unsigned long long u64;
extern void *mmap(void *, ul, int, int, int, long); extern int open(const char *, int, ...); extern int close(int); extern long pread(int, void *, ul, long);
extern ul strlen(const char *); extern void *memcpy(void *, const void *, ul); extern void *memset(void *, int, ul); extern void *malloc(ul); extern void free(void *);
extern int getpid(void); extern long syscall(long, ...); extern int sched_yield(void); extern int nanosleep(const void *, void *);
extern long write(int, const void *, ul); extern int printf(const char *, ...); extern int fflush(void *); extern void *stdout; extern int snprintf(char *, ul, const char *, ...);
extern int strcmp(const char *, const char *); extern char *strcpy(char *, const char *); extern char *strchr(const char *, int); extern int mkdir(const char *, unsigned);
extern int system(const char *); extern int access(const char *, int); extern int unlink(const char *); extern long time(long *); extern int usleep(unsigned);
extern int pthread_create(void *, const void *, void *(*)(void *), void *); extern int pthread_mutex_lock(void *); extern int pthread_mutex_unlock(void *);
#define LOG(...) do { printf("[idemuusb] " __VA_ARGS__); fflush(stdout); } while (0)
#include "chan_guest.h"

// ---------- libdbus (sem cabeçalhos: só o que se usa) ----------
typedef struct DBusConnection DBusConnection; typedef struct DBusMessage DBusMessage;
typedef struct { void *a[16]; } It;
typedef struct { const char *name, *message; unsigned flags; void *pad; char more[32]; } Err;
extern int dbus_threads_init_default(void); extern void dbus_error_init(Err *); extern int dbus_error_is_set(const Err *);
extern DBusConnection *dbus_bus_get(int, Err *); extern int dbus_bus_request_name(DBusConnection *, const char *, unsigned, Err *);
extern int dbus_connection_add_filter(DBusConnection *, int (*)(DBusConnection *, DBusMessage *, void *), void *, void *);
extern int dbus_connection_read_write_dispatch(DBusConnection *, int); extern int dbus_connection_send(DBusConnection *, DBusMessage *, u32 *);
extern void dbus_connection_flush(DBusConnection *); extern void dbus_connection_set_exit_on_disconnect(DBusConnection *, int);
extern DBusMessage *dbus_message_new_method_return(DBusMessage *); extern DBusMessage *dbus_message_new_error(DBusMessage *, const char *, const char *);
extern DBusMessage *dbus_message_new_signal(const char *, const char *, const char *); extern void dbus_message_unref(DBusMessage *);
extern const char *dbus_message_get_path(DBusMessage *); extern const char *dbus_message_get_member(DBusMessage *); extern const char *dbus_message_get_interface(DBusMessage *);
extern int dbus_message_get_type(DBusMessage *);
extern int dbus_message_iter_init(DBusMessage *, It *); extern void dbus_message_iter_init_append(DBusMessage *, It *); extern void dbus_message_iter_get_basic(It *, void *); extern int dbus_message_iter_next(It *);
extern int dbus_message_iter_append_basic(It *, int, const void *); extern int dbus_message_iter_append_fixed_array(It *, int, const void *, int);
extern int dbus_message_iter_open_container(It *, int, const char *, It *); extern int dbus_message_iter_close_container(It *, It *);

#define N "org.freedesktop.UDisks2."
#define P_MGR "/org/freedesktop/UDisks2/Manager"
#define P_DRV "/org/freedesktop/UDisks2/drives/IDEmu_Virtual_USB_IDEMU0001"
#define P_DSK "/org/freedesktop/UDisks2/block_devices/sda"
#define P_PRT "/org/freedesktop/UDisks2/block_devices/sda1"
#define P_ROOT "/org/freedesktop/UDisks2"

// ---------- estado do dispositivo ----------
static char mu[64] __attribute__((aligned(8)));  // pthread_mutex_t zerado = inicializador padrão
static int present, mounted, pend;  // pend: 1 = anunciar entrada, 2 = anunciar saída
static char label[48], mnt[96], gone_label[48];
static u64 devsize = 8ull << 30, files_n, bytes_n;
static DBusConnection *conn;
static void lock(void) { pthread_mutex_lock(mu); }
static void unlock(void) { pthread_mutex_unlock(mu); }

// ---------- propriedades ----------
typedef struct { const char *k; char t; const char *s; u64 n; const char *e; } Pr;
static int props(const char *path, const char *iface, Pr *o) {
  int n = 0; long now = time(0) * 1000000l; const char *dev = strcmp(path, P_DSK) ? "/dev/sda1" : "/dev/sda";
  int part = !strcmp(path, P_PRT);
#define PR(k, t, s, v, e) o[n++] = (Pr){ k, t, s, (u64)(v), e }
  if (!strcmp(path, P_MGR) && !strcmp(iface, N "Manager")) {
    PR("Version", 's', "2.9.4", 0, 0); PR("SupportedFilesystems", 'S', "vfat", 0, 0); PR("SupportedEncryptionTypes", 'S', "luks1", 0, 0); PR("DefaultEncryptionType", 's', "luks1", 0, 0);
  } else if (!strcmp(path, P_DRV) && !strcmp(iface, N "Drive")) {
    PR("Vendor", 's', "IDEmu", 0, 0); PR("Model", 's', "Virtual USB", 0, 0); PR("Revision", 's', "1.00", 0, 0); PR("Serial", 's', "IDEMU0001", 0, 0); PR("WWN", 's', "", 0, 0);
    PR("Id", 's', "IDEmu-Virtual-USB-IDEMU0001", 0, 0); PR("Configuration", 'E', 0, 0, "{sv}"); PR("Media", 's', "thumb", 0, 0); PR("MediaCompatibility", 'S', "thumb", 0, 0);
    PR("MediaRemovable", 'b', 0, 1, 0); PR("MediaAvailable", 'b', 0, 1, 0); PR("MediaChangeDetected", 'b', 0, 1, 0); PR("Size", 't', 0, devsize, 0);
    PR("TimeDetected", 't', 0, now, 0); PR("TimeMediaDetected", 't', 0, now, 0); PR("Optical", 'b', 0, 0, 0); PR("OpticalBlank", 'b', 0, 0, 0);
    PR("OpticalNumTracks", 'u', 0, 0, 0); PR("OpticalNumAudioTracks", 'u', 0, 0, 0); PR("OpticalNumDataTracks", 'u', 0, 0, 0); PR("OpticalNumSessions", 'u', 0, 0, 0);
    PR("RotationRate", 'i', 0, 0, 0); PR("ConnectionBus", 's', "usb", 0, 0); PR("Seat", 's', "seat0", 0, 0); PR("Removable", 'b', 0, 1, 0); PR("Ejectable", 'b', 0, 1, 0);
    PR("SortKey", 's', "", 0, 0); PR("CanPowerOff", 'b', 0, 1, 0); PR("SiblingId", 's', "/sys/devices/platform/soc/a600000.usb/xhci-hcd.0.auto/usb1/1-1/1-1:1.0", 0, 0);
  } else if ((!strcmp(path, P_DSK) || part) && !strcmp(iface, N "Block")) {
    PR("Device", 'B', dev, 0, 0); PR("PreferredDevice", 'B', dev, 0, 0); PR("Symlinks", 'A', 0, 0, 0); PR("DeviceNumber", 't', 0, part ? 2049 : 2048, 0);
    PR("Id", 's', part ? "by-uuid-1DE5-0001" : "by-id-IDEmu_Virtual_USB", 0, 0); PR("Size", 't', 0, part ? devsize - (1 << 20) : devsize, 0); PR("ReadOnly", 'b', 0, 0, 0);
    PR("Drive", 'o', P_DRV, 0, 0); PR("MDRaid", 'o', "/", 0, 0); PR("MDRaidMember", 'o', "/", 0, 0);
    PR("IdUsage", 's', part ? "filesystem" : "", 0, 0); PR("IdType", 's', part ? "vfat" : "", 0, 0); PR("IdVersion", 's', part ? "FAT32" : "", 0, 0);
    PR("IdLabel", 's', part ? label : "", 0, 0); PR("IdUUID", 's', part ? "1DE5-0001" : "", 0, 0); PR("Configuration", 'E', 0, 0, "(sa{sv})");
    PR("CryptoBackingDevice", 'o', "/", 0, 0); PR("HintPartitionable", 'b', 0, !part, 0); PR("HintSystem", 'b', 0, 0, 0); PR("HintIgnore", 'b', 0, 0, 0); PR("HintAuto", 'b', 0, 1, 0);
    PR("HintName", 's', "", 0, 0); PR("HintIconName", 's', "", 0, 0); PR("HintSymbolicIconName", 's', "", 0, 0); PR("UserspaceMountOptions", 'S', 0, 0, 0);
  } else if (!strcmp(path, P_DSK) && !strcmp(iface, N "PartitionTable")) {
    PR("Type", 's', "dos", 0, 0); PR("Partitions", 'O', P_PRT, 0, 0);
  } else if (part && !strcmp(iface, N "Partition")) {
    PR("Number", 'u', 0, 1, 0); PR("Type", 's', "0x0c", 0, 0); PR("Flags", 't', 0, 0, 0); PR("Offset", 't', 0, 1 << 20, 0); PR("Size", 't', 0, devsize - (1 << 20), 0);
    PR("Name", 's', "", 0, 0); PR("UUID", 's', "", 0, 0); PR("Table", 'o', P_DSK, 0, 0); PR("IsContainer", 'b', 0, 0, 0); PR("IsContained", 'b', 0, 0, 0);
  } else if (part && !strcmp(iface, N "Filesystem")) {
    PR("MountPoints", 'M', mounted ? mnt : 0, 0, 0); PR("Size", 't', 0, devsize - (1 << 20), 0);
  } else return -1;
  return n;
}
typedef struct { const char *path; const char *ifs[4]; int dev; } Ob;
static const Ob OBS[] = { { P_MGR, { N "Manager" }, 0 }, { P_DRV, { N "Drive" }, 1 }, { P_DSK, { N "Block", N "PartitionTable" }, 1 }, { P_PRT, { N "Block", N "Partition", N "Filesystem" }, 1 } };
#define NOB 4

// ---------- marshaling ----------
#define OPEN(p, t, s, c) dbus_message_iter_open_container(p, t, s, c)
#define CLOSE(p, c) dbus_message_iter_close_container(p, c)
#define APP(i, t, v) dbus_message_iter_append_basic(i, t, v)
static void emit_val(It *par, const Pr *p) {
  It v, a, b; char sig[40]; u32 u = (u32)p->n; int sp = 0; const char *s = p->s;
  switch (p->t) {
  case 's': OPEN(par, 'v', "s", &v); APP(&v, 's', &s); CLOSE(par, &v); break;
  case 'o': OPEN(par, 'v', "o", &v); APP(&v, 'o', &s); CLOSE(par, &v); break;
  case 'b': u = p->n ? 1 : 0; OPEN(par, 'v', "b", &v); APP(&v, 'b', &u); CLOSE(par, &v); break;
  case 'u': OPEN(par, 'v', "u", &v); APP(&v, 'u', &u); CLOSE(par, &v); break;
  case 'i': OPEN(par, 'v', "i", &v); APP(&v, 'i', &u); CLOSE(par, &v); break;
  case 't': OPEN(par, 'v', "t", &v); APP(&v, 't', &p->n); CLOSE(par, &v); break;
  case 'B': OPEN(par, 'v', "ay", &v); OPEN(&v, 'a', "y", &a); dbus_message_iter_append_fixed_array(&a, 'y', &s, (int)strlen(s) + 1); CLOSE(&v, &a); CLOSE(par, &v); break;
  case 'S': OPEN(par, 'v', "as", &v); OPEN(&v, 'a', "s", &a); if (s) APP(&a, 's', &s); CLOSE(&v, &a); CLOSE(par, &v); break;
  case 'A': OPEN(par, 'v', "aay", &v); OPEN(&v, 'a', "ay", &a); CLOSE(&v, &a); CLOSE(par, &v); break;
  case 'O': OPEN(par, 'v', "ao", &v); OPEN(&v, 'a', "o", &a); if (s) APP(&a, 'o', &s); CLOSE(&v, &a); CLOSE(par, &v); break;
  case 'M': OPEN(par, 'v', "aay", &v); OPEN(&v, 'a', "ay", &a);
    if (s) { OPEN(&a, 'a', "y", &b); dbus_message_iter_append_fixed_array(&b, 'y', &s, (int)strlen(s) + 1); CLOSE(&a, &b); }
    CLOSE(&v, &a); CLOSE(par, &v); break;
  case 'E': sig[0] = 'a'; strcpy(sig + 1, p->e); OPEN(par, 'v', sig, &v); OPEN(&v, 'a', p->e, &a); CLOSE(&v, &a); CLOSE(par, &v); break;
  }
  (void)sp;
}
static void emit_dict(It *arr, Pr *pr, int n) {
  for (int i = 0; i < n; i++) { It e; const char *k = pr[i].k; OPEN(arr, 'e', 0, &e); APP(&e, 's', &k); emit_val(&e, &pr[i]); CLOSE(arr, &e); }
}
static void emit_ifaces(It *ifs, const Ob *o) {  // a{sa{sv}} de um objeto
  for (int j = 0; o->ifs[j] && j < 4; j++) {
    Pr pr[48]; int n = props(o->path, o->ifs[j], pr); It ie, pa; const char *nm = o->ifs[j];
    OPEN(ifs, 'e', 0, &ie); APP(&ie, 's', &nm); OPEN(&ie, 'a', "{sv}", &pa); if (n > 0) emit_dict(&pa, pr, n); CLOSE(&ie, &pa); CLOSE(ifs, &ie);
  }
}
static void send_and_free(DBusMessage *m) { if (m) { dbus_connection_send(conn, m, 0); dbus_message_unref(m); } }
static void sig_added(const Ob *o) {
  DBusMessage *m = dbus_message_new_signal(P_ROOT, "org.freedesktop.DBus.ObjectManager", "InterfacesAdded"); It it, ifs; const char *p = o->path;
  dbus_message_iter_init_append(m, &it); APP(&it, 'o', &p); OPEN(&it, 'a', "{sa{sv}}", &ifs); emit_ifaces(&ifs, o); CLOSE(&it, &ifs); send_and_free(m);
}
static void sig_removed(const Ob *o) {
  DBusMessage *m = dbus_message_new_signal(P_ROOT, "org.freedesktop.DBus.ObjectManager", "InterfacesRemoved"); It it, a; const char *p = o->path;
  dbus_message_iter_init_append(m, &it); APP(&it, 'o', &p); OPEN(&it, 'a', "s", &a);
  for (int j = 0; o->ifs[j] && j < 4; j++) { const char *nm = o->ifs[j]; APP(&a, 's', &nm); }
  CLOSE(&it, &a); send_and_free(m);
}
static void sig_mountpoints(void) {
  DBusMessage *m = dbus_message_new_signal(P_PRT, "org.freedesktop.DBus.Properties", "PropertiesChanged"); It it, d, e, ia; const char *fs = N "Filesystem"; Pr pr[2]; int n = props(P_PRT, fs, pr);
  dbus_message_iter_init_append(m, &it); APP(&it, 's', &fs); OPEN(&it, 'a', "{sv}", &d);
  for (int i = 0; i < n; i++) if (!strcmp(pr[i].k, "MountPoints")) { const char *k = pr[i].k; OPEN(&d, 'e', 0, &e); APP(&e, 's', &k); emit_val(&e, &pr[i]); CLOSE(&d, &e); }
  CLOSE(&it, &d); OPEN(&it, 'a', "s", &ia); CLOSE(&it, &ia); send_and_free(m);
}

// ---------- chamadas de método ----------
static int reply_err(DBusConnection *c, DBusMessage *m, const char *name, const char *msg) {
  DBusMessage *r = dbus_message_new_error(m, name, msg); dbus_connection_send(c, r, 0); dbus_message_unref(r); return 0;
}
static const Ob *find_ob(const char *path) { for (int i = 0; i < NOB; i++) if (!strcmp(path, OBS[i].path)) return (OBS[i].dev && !present) ? 0 : &OBS[i]; return 0; }
static int filt(DBusConnection *c, DBusMessage *m, void *u) {
  if (dbus_message_get_type(m) != 1) return 1;
  const char *path = dbus_message_get_path(m), *ifc = dbus_message_get_interface(m), *mem = dbus_message_get_member(m);
  if (!path || !mem) return 1;
  if (!ifc) ifc = "";
  lock();
  int r = 0;
  if (!strcmp(ifc, "org.freedesktop.DBus.ObjectManager") && !strcmp(mem, "GetManagedObjects")) {
    DBusMessage *rp = dbus_message_new_method_return(m); It it, objs, oe, ifs;
    dbus_message_iter_init_append(rp, &it); OPEN(&it, 'a', "{oa{sa{sv}}}", &objs);
    for (int i = 0; i < NOB; i++) {
      if (OBS[i].dev && !present) continue;
      const char *p = OBS[i].path; OPEN(&objs, 'e', 0, &oe); APP(&oe, 'o', &p); OPEN(&oe, 'a', "{sa{sv}}", &ifs); emit_ifaces(&ifs, &OBS[i]); CLOSE(&oe, &ifs); CLOSE(&objs, &oe);
    }
    CLOSE(&it, &objs); dbus_connection_send(c, rp, 0); dbus_message_unref(rp); LOG("GetManagedObjects (presente=%d)\n", present);
  } else if (!strcmp(ifc, "org.freedesktop.DBus.Properties") && (!strcmp(mem, "GetAll") || !strcmp(mem, "Get"))) {
    It a; const char *iface = 0, *pn = 0; const Ob *o = find_ob(path);
    if (!dbus_message_iter_init(m, &a)) r = reply_err(c, m, "org.freedesktop.DBus.Error.InvalidArgs", "faltam argumentos");
    else {
      dbus_message_iter_get_basic(&a, &iface); if (!strcmp(mem, "Get") && dbus_message_iter_next(&a)) dbus_message_iter_get_basic(&a, &pn);
      Pr pr[48]; int n = o ? props(path, iface, pr) : -1;
      if (n < 0) r = reply_err(c, m, "org.freedesktop.DBus.Error.UnknownObject", "objeto ou interface desconhecidos");
      else if (!strcmp(mem, "GetAll")) {
        DBusMessage *rp = dbus_message_new_method_return(m); It it, d; dbus_message_iter_init_append(rp, &it); OPEN(&it, 'a', "{sv}", &d); emit_dict(&d, pr, n); CLOSE(&it, &d);
        dbus_connection_send(c, rp, 0); dbus_message_unref(rp);
      } else {
        int k = -1; for (int i = 0; i < n; i++) if (pn && !strcmp(pr[i].k, pn)) k = i;
        if (k < 0) r = reply_err(c, m, "org.freedesktop.DBus.Error.InvalidArgs", "propriedade desconhecida");
        else { DBusMessage *rp = dbus_message_new_method_return(m); It it; dbus_message_iter_init_append(rp, &it); emit_val(&it, &pr[k]); dbus_connection_send(c, rp, 0); dbus_message_unref(rp); }
      }
    }
  } else if (!strcmp(ifc, N "Filesystem") && !strcmp(path, P_PRT) && present && !strcmp(mem, "Mount")) {
    if (mounted) { char b[200]; snprintf(b, sizeof b, "Device /dev/sda1 is already mounted at `%s'.", mnt); r = reply_err(c, m, N "Error.AlreadyMounted", b); }
    else {
      snprintf(mnt, sizeof mnt, "/media/%s", label); mounted = 1;
      DBusMessage *rp = dbus_message_new_method_return(m); It it; const char *p = mnt; dbus_message_iter_init_append(rp, &it); APP(&it, 's', &p);
      dbus_connection_send(c, rp, 0); dbus_message_unref(rp); sig_mountpoints(); LOG("Mount -> %s\n", mnt);
    }
  } else if (!strcmp(ifc, N "Filesystem") && !strcmp(path, P_PRT) && present && !strcmp(mem, "Unmount")) {
    if (!mounted) r = reply_err(c, m, N "Error.NotMounted", "Device is not mounted");
    else { mounted = 0; DBusMessage *rp = dbus_message_new_method_return(m); dbus_connection_send(c, rp, 0); dbus_message_unref(rp); sig_mountpoints(); LOG("Unmount\n"); }
  } else if (!strcmp(ifc, "org.freedesktop.DBus.Introspectable")) {
    DBusMessage *rp = dbus_message_new_method_return(m); It it; const char *x = "<node/>"; dbus_message_iter_init_append(rp, &it); APP(&it, 's', &x); dbus_connection_send(c, rp, 0); dbus_message_unref(rp);
  } else { LOG("chamada ignorada: %s %s.%s\n", path, ifc, mem); r = reply_err(c, m, "org.freedesktop.DBus.Error.UnknownMethod", "metodo nao suportado"); }
  unlock();
  return r;
}

// ---------- entrega dos arquivos (canal do host) ----------
static void mkparents(char *p) {
  for (char *s = p + 1; *s; s++) if (*s == '/') { *s = 0; mkdir(p, 0755); *s = '/'; }
}
static int safe(const char *n) {
  if (!n[0] || n[0] == '/') return 0;
  for (const char *s = n; *s; s++) if (s[0] == '.' && s[1] == '.' && (s == n || s[-1] == '/') && (s[2] == 0 || s[2] == '/')) return 0;
  return 1;
}
static void clean_label(char *l) { for (; *l; l++) if (!((*l >= '0' && *l <= '9') || (*l >= 'A' && *l <= 'Z') || (*l >= 'a' && *l <= 'z') || *l == '_' || *l == '-' || *l == '.')) *l = '_'; }
static void do_eject(void) {
  lock(); if (present) { strcpy(gone_label, label); pend = 2; } unlock();
}
static void *chan_thread(void *arg) {
  Ch *c = arg; static char name[4200], path[4400]; char *buf = malloc(1 << 20); char base[96] = ""; int open_ok = 0;
  for (;;) {
    usb_msg h; get(c, &h, sizeof h);
    if (h.magic != USB_MAGIC || h.namelen > 4096) { LOG("mensagem inválida, descartando\n"); continue; }
    if (h.namelen) get(c, name, h.namelen); name[h.namelen] = 0;
    if (h.op == USB_BEGIN) {
      lock(); int was = present; unlock();
      if (was) { do_eject(); for (int i = 0; i < 100; i++) { lock(); int p = present || pend; unlock(); if (!p) break; usleep(50000); } }
      clean_label(name); if (!name[0]) strcpy(name, "USB");
      snprintf(base, sizeof base, "/media/%s", name);
      snprintf(path, sizeof path, "rm -rf '%s'; mkdir -p '%s'", base, base); system(path);
      lock(); strcpy(label, name); unlock(); files_n = bytes_n = 0; open_ok = 1; LOG("recebendo '%s' (%llu bytes previstos)\n", name, h.size);
    } else if (h.op == USB_DIR || h.op == USB_FILE) {
      int fd = -1;
      if (open_ok && safe(name)) {
        snprintf(path, sizeof path, "%s/%s", base, name); mkparents(path);
        if (h.op == USB_DIR) mkdir(path, 0755); else fd = open(path, 0x241, 0644);
      }
      u64 left = h.size;
      if (h.op == USB_FILE) {
        while (left) { ul n = left > (1 << 20) ? (1 << 20) : left; get(c, buf, n); if (fd >= 0) write(fd, buf, n); left -= n; }
        if (fd >= 0) { close(fd); files_n++; bytes_n += h.size; }
      }
    } else if (h.op == USB_END) {
      if (open_ok) { lock(); present = 1; mounted = 0; pend = 1; devsize = bytes_n + (1ull << 30) > (8ull << 30) ? bytes_n + (1ull << 30) : (8ull << 30); unlock(); LOG("pronto: %llu arquivos, %llu bytes\n", files_n, bytes_n); }
      open_ok = 0;
    } else if (h.op == USB_EJECT) do_eject();
  }
}

// ---------- laço principal ----------
static void presence(int on) {
  if (!on) { unlink("/run/idemu-usb/present"); return; }
  int fd = open("/run/idemu-usb/present", 0x241, 0644); if (fd >= 0) { write(fd, label, strlen(label)); write(fd, "\n", 1); close(fd); }
}
static void announce(int what) {
  if (what == 1) { presence(1); usleep(600000); for (int i = 1; i < NOB; i++) sig_added(&OBS[i]); LOG("pen drive '%s' anunciado\n", label); }
  else { for (int i = NOB - 1; i >= 1; i--) sig_removed(&OBS[i]); presence(0); char cmd[160]; snprintf(cmd, sizeof cmd, "rm -rf '/media/%s'", gone_label); system(cmd); LOG("pen drive removido\n"); }
}
int main(void) {
  Err e; dbus_threads_init_default(); dbus_error_init(&e);
  for (int i = 0; i < 100 && !conn; i++) { conn = dbus_bus_get(0, &e); if (!conn) { LOG("sem barramento (DBUS_SESSION_BUS_ADDRESS), tentando de novo\n"); usleep(500000); } }
  if (!conn) return 1;
  dbus_connection_set_exit_on_disconnect(conn, 0);
  int rq = dbus_bus_request_name(conn, "org.freedesktop.UDisks2", 4, &e);
  if (rq != 1) { LOG("não consegui o nome org.freedesktop.UDisks2 (%d)\n", rq); return 1; }
  dbus_connection_add_filter(conn, filt, 0, 0);
  mkdir("/media", 0755); mkdir("/run/idemu-usb", 0755); unlink("/run/idemu-usb/present");
  Ch *ch = ch_open(USB_ROLE);
  if (ch) { char th[16]; pthread_create(th, 0, chan_thread, ch); }
  LOG("UDisks2 falso no ar\n");
  for (;;) {
    if (!dbus_connection_read_write_dispatch(conn, 100)) { LOG("barramento caiu\n"); return 2; }
    if (!access("/tmp/idemuusb.attach", 0)) {  // teste manual: o conteúdo do arquivo é o rótulo
      char l[48] = ""; int fd = open("/tmp/idemuusb.attach", 0); if (fd >= 0) { long n = pread(fd, l, 40, 0); if (n > 0) l[n] = 0; close(fd); }
      unlink("/tmp/idemuusb.attach"); char *nl = strchr(l, '\n'); if (nl) *nl = 0; clean_label(l); if (!l[0]) strcpy(l, "TESTE");
      lock(); strcpy(label, l); present = 1; mounted = 0; pend = 1; unlock();
    }
    if (!access("/tmp/idemuusb.eject", 0)) { unlink("/tmp/idemuusb.eject"); do_eject(); }
    lock(); int p = pend; pend = 0; unlock();
    if (p) { lock(); if (p == 2) { announce(2); present = 0; mounted = 0; } else announce(1); unlock(); }
  }
}

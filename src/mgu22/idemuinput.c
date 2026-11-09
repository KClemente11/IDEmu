// idemuinput: touchscreen do iDrive 8. Cria um dispositivo uinput multitoque e aplica os comandos que o host manda pelo canal:
// "d x y\n" (toca), "m x y\n" (arrasta), "u\n" (solta).
#include "chan.h"
typedef unsigned long ul; typedef unsigned u32; typedef unsigned short u16;
extern void *mmap(void *, ul, int, int, int, long); extern int open(const char *, int, ...); extern int close(int); extern long pread(int, void *, ul, long);
extern ul strlen(const char *); extern void *memcpy(void *, const void *, ul); extern void *memset(void *, int, ul); extern void *malloc(ul);
extern int getpid(void); extern long syscall(long, ...); extern int sched_yield(void); extern int nanosleep(const void *, void *);
extern int ioctl(int, ul, ...); extern long write(int, const void *, ul); extern int printf(const char *, ...); extern int fflush(void *); extern void *stdout; extern int sscanf(const char *, const char *, ...); extern char *strcpy(char *, const char *);
extern void *stderr; extern int fprintf(void *, const char *, ...);
#define LOG(...) do { printf("[idemuinput] " __VA_ARGS__); fflush(stdout); } while (0)
#include "chan_guest.h"
static int ufd;
static void emit(u16 t, u16 c, int v) { struct { long s, us; u16 t, c; int v; } e; memset(&e, 0, sizeof e); e.t = t; e.c = c; e.v = v; write(ufd, &e, sizeof e); }
static void absx(u16 code, int mn, int mx) { struct { u16 c, p; int v, mi, ma, fu, fl, re; } a; memset(&a, 0, sizeof a); a.c = code; a.mi = mn; a.ma = mx; ioctl(ufd, 0x401c5504, &a); }
enum { EV_SYN, EV_KEY, EV_ABS = 3, BTN_TOUCH = 0x14a, ABS_X = 0, ABS_Y = 1, MT_SLOT = 0x2f, MT_X = 0x35, MT_Y = 0x36, MT_ID = 0x39 };
int main(void) {
  ufd = open("/dev/uinput", 2);
  if (ufd < 0) { LOG("sem /dev/uinput\n"); return 1; }
  ioctl(ufd, 0x40045564, EV_KEY); ioctl(ufd, 0x40045564, EV_ABS); ioctl(ufd, 0x40045565, BTN_TOUCH); ioctl(ufd, 0x4004556e, 1);
  int ax[] = { ABS_X, ABS_Y, MT_SLOT, MT_X, MT_Y, MT_ID };
  for (int i = 0; i < 6; i++) ioctl(ufd, 0x40045567, ax[i]);
  absx(ABS_X, 0, 2879); absx(ABS_Y, 0, 959); absx(MT_X, 0, 2879); absx(MT_Y, 0, 959); absx(MT_SLOT, 0, 4); absx(MT_ID, 0, 65535);
  struct { u16 bus, ven, pro, ver; char name[80]; u32 ff; } su; memset(&su, 0, sizeof su); su.bus = 3; su.ven = 0x1234; su.pro = 0x5678; strcpy(su.name, "cid-touchscreen");
  ioctl(ufd, 0x405c5503, &su); ioctl(ufd, 0x5501);
  Ch *c = ch_open(1); LOG("pronto\n");
  char l[64]; int n = 0, tid = 1;
  for (;;) {
    char b; get(c, &b, 1);
    if (b != '\n') { if (n < 63) l[n++] = b; continue; }
    l[n] = 0; n = 0; int x = 0, y = 0;
    if (l[0] == 'd' && sscanf(l + 1, "%d %d", &x, &y) == 2) {
      emit(EV_ABS, MT_SLOT, 0); emit(EV_ABS, MT_ID, tid++ & 0xffff); emit(EV_ABS, MT_X, x); emit(EV_ABS, MT_Y, y);
      emit(EV_KEY, BTN_TOUCH, 1); emit(EV_ABS, ABS_X, x); emit(EV_ABS, ABS_Y, y); emit(EV_SYN, 0, 0);
    } else if (l[0] == 'm' && sscanf(l + 1, "%d %d", &x, &y) == 2) {
      emit(EV_ABS, MT_SLOT, 0); emit(EV_ABS, MT_X, x); emit(EV_ABS, MT_Y, y); emit(EV_ABS, ABS_X, x); emit(EV_ABS, ABS_Y, y); emit(EV_SYN, 0, 0);
    } else if (l[0] == 'u') {
      emit(EV_ABS, MT_SLOT, 0); emit(EV_ABS, MT_ID, -1); emit(EV_KEY, BTN_TOUCH, 0); emit(EV_SYN, 0, 0);
    }
  }
}

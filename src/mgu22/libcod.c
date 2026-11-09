// libcod.so.0 do IDEmu (iDrive 8): responde cod_get_flag com a tabela /etc/idemu/coding.tab
// gerada de MGU22_Coding.txt + cafd_mgu_02_a.bin por tools/mgu/gencoding.py. Formato: "<id hex> <valor>\n".
typedef unsigned long u64; typedef unsigned int u32;
typedef struct FILE FILE;
extern FILE *fopen(const char *, const char *); extern int fclose(FILE *); extern char *fgets(char *, int, FILE *);
extern unsigned long strtoul(const char *, char **, int); extern long strtol(const char *, char **, int);
extern void *malloc(unsigned long); extern int fprintf(FILE *, const char *, ...); extern FILE *stderr;
extern char *getenv(const char *);
static struct ent { u32 id; long val; } *tab; static int ntab, tried, dbg;
static void load(void) {
  if (tried) return; tried = 1; dbg = getenv("IDEMU_COD_DEBUG") != 0;
  FILE *f = fopen("/etc/idemu/coding.tab", "r"); if (!f) return;
  tab = malloc(sizeof(*tab) * 8192); char l[128];
  while (ntab < 8192 && fgets(l, sizeof l, f)) { char *e; u32 id = strtoul(l, &e, 16); tab[ntab].id = id; tab[ntab].val = strtol(e, 0, 10); ntab++; }
  fclose(f);
}
int cod_init(int area, unsigned char maj, unsigned char min) { load(); return 0; }
int cod_close(int area) { return 0; }
int cod_get_flag(u64 uuid, long *out) {
  load();
  u32 id = (u32)(uuid >> 16);
  for (int i = 0; i < ntab; i++) if (tab[i].id == id) { if (dbg) fprintf(stderr, "cod %016lx = %ld\n", uuid, tab[i].val); if (out) *out = tab[i].val; return 0; }
  if (dbg) fprintf(stderr, "cod %016lx ?\n", uuid);
  if (out) *out = 0; return 1;
}

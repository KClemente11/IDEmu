// idemu-run <usuário> <comando...>: executa o comando com o uid/gid/grupos do usuário (o vsomeip confere as credenciais).
typedef unsigned int u32;
struct pw { char *name, *pass; u32 uid, gid; };
extern struct pw *getpwnam(const char*); extern int initgroups(const char*, u32); extern int setgid(u32); extern int setuid(u32);
extern int execvp(const char*, char *const*); extern int fprintf(void*, const char*, ...); extern void *stderr;
int main(int argc, char **argv) {
  if (argc < 3) return 2; struct pw *p = getpwnam(argv[1]); if (!p) { fprintf(stderr, "idemu-run: usuário %s?\n", argv[1]); return 3; }
  initgroups(argv[1], p->gid); if (setgid(p->gid) || setuid(p->uid)) { fprintf(stderr, "idemu-run: setuid falhou\n"); return 4; }
  execvp(argv[2], argv + 2); fprintf(stderr, "idemu-run: exec %s falhou\n", argv[2]); return 5;
}
__asm__(".globl _start\n_start:\n xor %ebp,%ebp\n mov (%rsp),%edi\n lea 8(%rsp),%rsi\n and $-16,%rsp\n call main\n mov %eax,%edi\n mov $60,%eax\n syscall\n");

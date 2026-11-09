// _start mínimo para executáveis do guest (sem crt1.o do firmware)
extern int main(int, char **, char **);
extern int __libc_start_main(int (*)(int, char **, char **), int, char **, void *, void *, void *, void *);
__asm__(".text\n.globl _start\n_start:\n mov x29,#0\n mov x30,#0\n mov x5,x0\n ldr x1,[sp]\n add x2,sp,#8\n mov x6,sp\n and x0,x6,#~15\n mov sp,x0\n adrp x0,:got:main\n ldr x0,[x0,:got_lo12:main]\n mov x3,#0\n mov x4,#0\n bl __libc_start_main\n brk #1\n");

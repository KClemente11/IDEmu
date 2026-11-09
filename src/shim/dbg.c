#include "common.h"
extern void *dlopen(const char*,int); extern void *dlsym(void*,const char*);
static void *real(const char*n){ return dlsym(dlopen("libc.so.3",2),n); }
/* log only missing files: tells us which assets the HMI wants and we don't ship */
int open(const char*p,int f,...){ static int(*r)(const char*,int,...); if(!r) r=real("open"); int fd=r(p,f,0666); if(fd<0) br_logx(p,0xe0,f,0); return fd; }
int stat(const char*p,void*b){ static int(*r)(const char*,void*); if(!r) r=real("stat"); int x=r(p,b); if(x<0) br_logx(p,0xe1,x,0); return x; }
int stat64(const char*p,void*b){ static int(*r)(const char*,void*); if(!r) r=real("stat64"); int x=r(p,b); if(x<0) br_logx(p,0xe2,x,0); return x; }
int access(const char*p,int m){ static int(*r)(const char*,int); if(!r) r=real("access"); int x=r(p,m); if(x<0) br_logx(p,0xe3,x,m); return x; }

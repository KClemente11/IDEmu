typedef unsigned int u32; typedef int s32; typedef unsigned char u8; typedef unsigned short u16; typedef unsigned long long u64;
#define NULL ((void*)0)
extern int open(const char*,int,...); extern long write(int,const void*,unsigned long); extern int close(int);
extern void *malloc(unsigned long); extern void *calloc(unsigned long,unsigned long); extern void *realloc(void*,unsigned long); extern void free(void*);
extern void *memcpy(void*,const void*,unsigned long); extern void *memset(void*,int,unsigned long);
extern unsigned long strlen(const char*); extern int strcmp(const char*,const char*);
extern void *mmap_device_memory(void*,unsigned long,int,int,unsigned long long);
extern int sched_yield(void);
#include "glops.h"
/* bridge */
void br_init(void);
u32 *br_begin(u32 op,u32 nwords);
void br_flush(void);
u32 br_sync(u32 **reply);          /* returns reply length in bytes */
void br_log(const char*s);
void br_logx(const char*s,u32 a,u32 b,u32 c);
extern volatile int br_lock_v;
extern int usleep(unsigned);
#define LOCK()   do{ int _n=0; br_init(); while(__atomic_exchange_n(&br_lock_v,1,__ATOMIC_ACQUIRE)){ if(++_n>4) usleep(500); else sched_yield(); } }while(0)
#define UNLOCK() __atomic_store_n(&br_lock_v,0,__ATOMIC_RELEASE)
#define MAXOP_BYTES (6*1024*1024)

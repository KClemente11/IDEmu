#include "common.h"
volatile int br_lock_v;
static volatile u32 *R; static u32 *Q,*P; static u32 qn; static int inited,dummy;
static u32 dummyrep[4];
#define QCAP (2*1024*1024)
void br_init(void){
  if(inited) return; inited=1;
  R=(volatile u32*)mmap_device_memory(0,0x1000,0xb00,0,0x7ff00000ULL);
  u32 *b=(u32*)mmap_device_memory(0,0x1000000,0x300,0,0x7e000000ULL);
  if((int)R==-1||(int)b==-1){ dummy=1; Q=(u32*)malloc(8<<20); P=dummyrep; }
  else { Q=b; P=b+0x200000; }
}
u32 *br_begin(u32 op,u32 n){
  if(qn+2+n>QCAP-8) br_flush();
  u32 *p=Q+qn; p[0]=op; p[1]=n; qn+=2+n; return p+2;
}
void br_flush(void){
  if(!qn) return;
  if(dummy){ qn=0; dummyrep[0]=0; return; }
  u32 n=qn*4; qn=0; R[0]=n;
}
u32 br_sync(u32 **rep){
  br_flush(); *rep=P;
  if(dummy) return 0;
  return R[2];
}
static void putstr(const char*s,u32 a,u32 b,u32 c){
  u32 l=strlen(s); u32 nw=(l+3)/4;
  u32 *p=br_begin(OP_LOG,4+nw); p[0]=l; p[1]=a; p[2]=b; p[3]=c; memcpy(p+4,s,l);
}
void br_logx(const char*s,u32 a,u32 b,u32 c){ LOCK(); putstr(s,a,b,c); br_flush(); UNLOCK(); }
void br_log(const char*s){ br_logx(s,0,0,0); }

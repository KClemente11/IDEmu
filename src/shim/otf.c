/* Fake libBMWOTFapi.so.3 : no agent; prints the HMI's trace text to the host log */
#include "common.h"
typedef __builtin_va_list va_list;
#define va_start __builtin_va_start
#define va_end __builtin_va_end
extern int vsnprintf(char*,unsigned long,const char*,va_list);
extern int snprintf(char*,unsigned long,const char*,...);
#include "otf_stubs.inc"
unsigned guiStartTime;
#ifndef OTFLVL
#define OTFLVL 0x10
#endif
void *_ZN15OTF_CppScopeUseC1EPK17tagOTF_ScopeEntry(void **t,void *s){ *t=s; return t; }
void *_ZN15OTF_CppScopeUseC2EPK17tagOTF_ScopeEntry(void **t,void *s){ *t=s; return t; }
void *_ZN15OTF_CppScopeUseD1Ev(void *t){ return t; }
void *_ZN15OTF_CppScopeUseD2Ev(void *t){ return t; }
typedef struct { u32 id; const char *name; u32 a,b; u16 c,d; u8 lvl; } scope_t;
static int prefix(const char*s,const char*p){ while(*p) if(*s++!=*p++) return 0; return 1; }
static void emit(const char *lvl,scope_t *s,const char *msg){ char b[300]; const char*nm="?"; if((u32)s>0x1000&&s->name&&(u32)s->name>0x1000) nm=s->name;
  if(lvl[0]=='T'&&(prefix(nm,"HmiBase_CHmiTimer")||prefix(nm,"A4A_")||prefix(nm,"CommonAPI_")||prefix(nm,"HmiBase_ProfTime")||prefix(nm,"CHmiResourceManager")||prefix(nm,"HmiPerformanceMonitor")||prefix(nm,"HmiPlugin_")||prefix(nm,"Hmi_Ines_textureCreate"))) return; snprintf(b,sizeof b,"%s[%s] %s",lvl,nm,msg?msg:"(null)"); br_log(b); }
extern void install_hooks(void);
int OTF_open(const char*a,const char*b,u32 c,u32 d){ br_log("OTF_open(fake)"); install_hooks(); return 1; }
int OTF_traceV(scope_t *s,const char *f,va_list ap){ char t[256]; vsnprintf(t,sizeof t,f,ap); t[255]=0; emit("T",s,t); return 0; }
int OTF_trace(scope_t *s,const char *f,...){ va_list ap; va_start(ap,f); OTF_traceV(s,f,ap); va_end(ap); return 0; }
int OTF_error(scope_t *s,const char *m){ emit("E",s,m); return 0; }
int OTF_warning(scope_t *s,const char *m){ emit("W",s,m); return 0; }
u32 OTF_getUIntSetting(u32 a,u32 b){ return b; }
/* scope ctor: same layout as the real one, no registration */
void *_ZN17OTF_CppScopeEntryC2EPKch(scope_t *t,const char *n,u8 lvl){ t->id=0; t->name=n; t->a=t->b=0; t->c=t->d=0; t->lvl=(lvl&~3)|OTFLVL; return t; }
void *_ZN17OTF_CppScopeEntryC1EPKch(scope_t *t,const char *n,u8 lvl){ return _ZN17OTF_CppScopeEntryC2EPKch(t,n,lvl); }

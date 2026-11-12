/* hook.c: runtime patches into the HMI's libraries (coding profile, etc.) */
#include "common.h"
void *hook_home(void); static unsigned char *disp_svc;
#define AUTO_POWER_TICKS 200
extern void *dlopen(const char*,int); extern void *dlsym(void*,const char*);
extern int mprotect(void*,unsigned long,int);
void *hk_sym(const char*lib,const char*s){ void*h=dlopen(lib,2); return h?dlsym(h,s):0; }
extern void *mmap(void*,unsigned long,int,int,int,long); extern int *__get_errno_ptr(void);
/* shared-library text can't be made writable: replace the page(s) by private anonymous copies */
static int unshare(u32 pg){ static u8 tmp[0x1000]; memcpy(tmp,(void*)pg,0x1000); void*r=mmap((void*)pg,0x1000,0x700,0x80012,-1,0); if((int)r==-1){ br_logx("hook: mmap FAILED",pg,*__get_errno_ptr(),0); return -1; } memcpy((void*)pg,tmp,0x1000); return 0; }
int hk_patch(void*target,void*fn){ u32 a=(u32)target&~1u; u32 pg=a&~0xfffu; if(unshare(pg)) return -1; if(((a+7)&~0xfffu)!=pg&&unshare(pg+0x1000)) return -1;
  u32 *p=(u32*)a; p[0]=0xe51ff004; p[1]=(u32)fn; return 0; }
int hk(const char*lib,const char*s,void*fn){ void*t=hk_sym(lib,s); if(!t){ br_logx(s,0xdead,0,0); return -1; } int r=hk_patch(t,fn); br_logx(s,0x600d,(u32)t,r); return r; }
/* trampoline: first two instructions (must not be pc-relative) + jump back */
void *hk_tramp(u32 a,void *fn){ u32 *t=(u32*)mmap(0,4096,0x700,0x80002,-1,0); if((int)t==-1){ br_logx("hook: tramp mmap failed",a,0,0); return 0; } t[0]=((u32*)a)[0]; t[1]=((u32*)a)[1]; t[2]=0xe51ff004; t[3]=a+8; hk_patch((void*)a,fn); return t; }
typedef struct { u16 blk,byte; u8 mask,val; } cod_t;
static const cod_t cod_builtin[]={
#include "coding_tab.inc"
};
/* IDEmu: the coding profile of the virtual car lives in /fs/shim/coding.tab (6-byte rows), written by the host builder */
extern int open(const char*,int,...); extern long read(int,void*,unsigned long); extern int close(int);
static const cod_t *cod=cod_builtin; static u32 NCOD=sizeof cod_builtin/sizeof cod_builtin[0]; static int cod_loaded;
static void cod_load(void){ if(cod_loaded) return; cod_loaded=1; int fd=open("/fs/shim/coding.tab",0); if(fd<0) return; static u8 buf[6*4096] __attribute__((aligned(4))); long n=0,r; while(n<(long)sizeof buf&&(r=read(fd,buf+n,sizeof buf-n))>0) n+=r; close(fd); if(n>=6){ cod=(const cod_t*)buf; NCOD=(u32)n/6; br_logx("coding: profile from /fs/shim/coding.tab, rows",NCOD,0,0); } }
static int (*getdef)(u32,const u8**,u32*);
static int hk_readCodingBlock(u8 *self,u8 *buf,u32 sz){ cod_load(); static const u8 map[17]={7,5,1,13,12,3,9,8,6,4,10,15,16,17,14,2,11};
  u16 blk=*(u16*)(self+4); u32 i; const u8*d=0; u32 n=0;
  if(blk<0x3000||blk>0x3010){ br_logx("coding: unknown block",blk,sz,0); return 1; }
  if(getdef) getdef(map[blk-0x3000],&d,&n);
  memset(buf,0,sz); if(d&&n) memcpy(buf,d,n<sz?n:sz);
  for(i=0;i<NCOD;i++) if(cod[i].blk==blk&&cod[i].byte<sz) buf[cod[i].byte]=(buf[cod[i].byte]&~cod[i].mask)|cod[i].val;
  br_logx("coding: block",blk,sz,n); return 1; }
static int hk_true(void){ return 1; }
/* the coding service only hands out streams once "coding available" is signalled by the (absent) syset server */
static void *(*dsi_ctor)(void*,u16);
static void *hk_openBinaryStream(u8 *svc,void *feature){ u32 **o=(u32**)malloc(8); dsi_ctor(o,*(u16*)(svc+0x10)); typedef int(*fn)(void*,void*); fn f=(fn)o[0][2]; if(f(o,feature)==0){ br_logx("coding: stream open failed",*(u16*)((u8*)feature+8),0,0); return 0; } return o; }
/* ---- controller input: host -> guest thread -> CHmiControllerEvent ---- */
static u8 *procs[256];
static u32 hk_getID(u8 *t){ u32 id=t[0xce]; if(!procs[id]){ procs[id]=t; br_logx("procunit",id,(u32)t,*(u32*)t); } return id; }
extern int pthread_create(void*,const void*,void*(*)(void*),void*);
static void *pu_c2; static u32 pu_saved[2];
static void *hk_pu_c2(u8 *t,void *disp,u32 id){ void*(*orig)(void*,void*,u32)=(void*(*)(void*,void*,u32))pu_c2; ((u32*)pu_c2)[0]=pu_saved[0]; ((u32*)pu_c2)[1]=pu_saved[1]; void *r=orig(t,disp,id); hk_patch(pu_c2,hk_pu_c2); id&=255; procs[id]=t; br_logx("procunit",id,(u32)t,*(u32*)t); return r; }
static int app_unit=-1;
static void send_ctrl(u32 key,int pressed,int repeat,int longp,int unit){ void*(*mk)(void)=(void*(*)(void))0x736fa0; u8*p=procs[unit]; if(!p){ br_logx("input: no proc unit",unit,0,0); return; }
  u8 *ev=(u8*)mk(); *(u32*)(ev+0x18)=key; ev[0x1c]=pressed; *(int*)(ev+0x20)=repeat; ev[0x24]=longp;
  typedef void(*pushf)(void*,void*); ((pushf)((u32*)*(u32*)p)[7])(p,ev); }
extern void *_Z14getHmiProcUnitv(void);
static u8 *main_pu;      /* 0x20f518 (getHmiProcUnit) usa TLS e devolve 0 em outros threads: guarda o do thread principal */
/* Ligar o HMI ("auto power on"): no thread principal (updateAliveTime). */
static void crash_install(void);
static void auto_power_on(void){ static int t,done; if(!done&&hook_home()&&++t>AUTO_POWER_TICKS){ done=1; u8*pu=((u8*(*)(void))0x20f518)(); crash_install(); br_log("auto power on"); ((void(*)(void*,u32))0x2152c4)(pu,3); br_log("auto power on: returned"); ((u8*)hook_home())[0x33b]=1; ((u8*)hook_home())[0x33a]=0; } }
/* Entrada do host: thread própria a cada 15 ms. Antes era lida em updateAliveTime, que com o relógio correto do guest (cntfrq) só roda ~1x/s com a tela parada: cada comando atrasava até 1 s.
   O giro do rotor vai direto para a fila do proc unit (vt[7]). Botões e comandos de depuração usam funções que exigem o thread principal (getHmiProcUnit por TLS, com assert): ficam num anel que
   hk_alive esvazia, e um evento vazio na fila acorda o laço principal para isso acontecer logo. */
void (*ilm_main_cb)(void); volatile int ilm_main_want;   /* avisos da ILM a entregar no thread principal (src/shim/ilm.c) */
typedef void(*pushf)(void*,void*);
static void push_ctrl(u32 key,u32 pressed,int param){ u8 *c=((u8*(*)(void))0x24a004)(); *(u32*)(c+0x18)=key; c[0x1c]=pressed; *(int*)(c+0x20)=param; c[0x24]=0; ((pushf)((u32*)*(u32*)main_pu)[7])(main_pu,c); }
static void touch_send(u32 state,u32 x,u32 y,u32 hms);
static u32 now_us(void); volatile u32 tm_swap_n,tm_swap_max,tm_swap_lock,tm_pump_lock,tm_push_max; extern volatile u32 tm_flush_n,tm_flush_bytes,tm_sync_n,tm_sync_us,tm_sync_max;
#define RINGN 256
static u32 ring[RINGN][4]; static volatile u32 ring_w, ring_r;
void input_pump(void){ u32 *p,*rep; u32 n;
  if(!main_pu) return;
  u32 tl0=now_us(); LOCK(); u32 tl1=now_us(); if(tl1-tl0>tm_pump_lock) tm_pump_lock=tl1-tl0; p=br_begin(OP_GETINPUT,0); n=br_sync(&rep); static u32 ev[64*4]; if(n>sizeof ev) n=sizeof ev; memcpy(ev,rep,n); UNLOCK();
  int wake=0;
  for(u32 i=0;i<n/16;i++){ u32 *e=ev+i*4;
    if(e[0]==40){ touch_send(e[1],e[2]&0xffff,e[2]>>16,e[3]==0xffff?0:e[3]); continue; }   /* toque: direto da thread de entrada (a entrega é assíncrona) e sem o evento de controlador que "acordaria" o laço: ele faria o HMI achar que o iDrive tomou a entrada */
    if(e[0]==2){ static int nr; if(nr<60){ nr++; br_logx("timing: rotary key/detents/guest ms",e[1],e[2],now_us()/1000u); } u32 tp=now_us(); push_ctrl(e[1],0,(int)e[2]); tp=now_us()-tp; if(tp>tm_push_max) tm_push_max=tp; continue; }   /* rotary: key=13 right / 14 left, val=detents */
    if(e[0]==30){ void *rd=*(void**)0x3af0a1c; if(rd) ((void(*)(void*,u32))0x2a0c498)(rd,e[1]); continue; }   /* imagem nova do mapa: o que o sinal do LayerManager faria (CHmiSurfaceRedirection::notifyUpdate) */
    if(ring_w-ring_r<RINGN){ memcpy(ring[ring_w%RINGN],e,16); __atomic_add_fetch(&ring_w,1,__ATOMIC_RELEASE); wake=1; }
  }
  if(wake||ilm_main_want) push_ctrl(0,0,0);
}
/* toque na tela (CID): monta um CTouchData e o entrega a CTouchDataClient::forwardTouchData (assíncrono), como o driver do touchscreen faria.
   Layout (ver docs/TOQUE.md): CTouchData{vptr, vector<dedo> @4, u8 @0x10 (tem de ser 0), tempo @0x14, origem @0x18}; dedo = 10 bytes {u16 x,u16 y,u16 z,u8 tipo,u8 estado,u8 id,u8 0};
   estado 1 = toca, 2 = move/segura, 3 = solta. O shared_ptr é montado à mão com contagem alta: o objeto nunca é liberado. */
extern int clock_gettime(int,void*);
static void *tdc_client; static void *(*tdc_c1)(void*,u32,u32); static void *(*tdc_c2)(void*,u32,u32);
/* o construtor começa com ldr/add relativos ao PC (base da GOT): o trampolim refaz essas duas e salta para depois do prólogo (0x18) */
static void *hk_tdc_tramp(u32 a,void *fn){ u32 *t=(u32*)mmap(0,4096,0x700,0x80002,-1,0); if((int)t==-1) return 0;
  t[0]=((u32*)a)[0]; t[1]=((u32*)a)[2]; t[2]=0xe59f5008; t[3]=0xe59f3008; t[4]=((u32*)a)[4]; t[5]=0xe59ff004; t[6]=0x39e7930; t[7]=0x7f60; t[8]=a+0x18; hk_patch((void*)a,fn); return t; }
static void *hk_tdc_a(void *t,u32 a,u32 b){ void *r=tdc_c1(t,a,b); if(!tdc_client){ tdc_client=t; br_logx("touch client C1",(u32)t,0,0); } return r; }
static void *hk_tdc_b(void *t,u32 a,u32 b){ void *r=tdc_c2(t,a,b); if(!tdc_client){ tdc_client=t; br_logx("touch client C2",(u32)t,0,0); } return r; }
/* o serviço guarda, por origem, se ela está habilitada (std::map<int,bool> em +0x28); num F-series sem touchscreen a origem 1 fica desligada */
static void touch_enable(void){ u32 *l=*(u32**)((u8*)tdc_client+0x1fc); if(!l||!l[2]) return; int key=1; u8 *p=((u8*(*)(void*,int*))0x2a01514)((u8*)l[2]+0x28,&key);
  if(!*p){ *p=1; br_logx("touch: origem 1 habilitada",(u32)p,0,0); } }
static void touch_send(u32 state,u32 x,u32 y,u32 hms){
  if(!tdc_client){ static int n; if(n++<5) br_logx("touch: sem cliente",state,x,y); return; }
  touch_enable();
  /* sem o monitor de verdade, o serviço de display acha que a tela está apagada e usa o primeiro toque só para acordá-la: marca como ligada */
  if(disp_svc&&(!disp_svc[0x3c]||!disp_svc[0x3d])){ disp_svc[0x3c]=1; disp_svc[0x3d]=1; ((void(*)(void*,int))0x2df744)(disp_svc,1); br_logx("touch: display marcado como ligado",(u32)disp_svc,0,0); }
  /* o tratador de gestos descarta o primeiro toque quando acha que a tela está apagada (+0x30 == 0): ele só a "acorda" */
  { u32 *ip=*(u32**)((u8*)tdc_client+0xd8); int k=0; while(ip&&k<10){ if(ip[3]==0x3384e8){ u8 *ob=(u8*)ip[2]+((int)ip[4]>>1); if(!ob[0x30]){ ob[0x30]=1; br_logx("touch: gestos ativos",(u32)ob,0,0); } } ip=(u32*)ip[0]; k++; } }
  u8 *f=(u8*)malloc(16); memset(f,0,16); *(u16*)f=(u16)x; *(u16*)(f+2)=(u16)y; *(u16*)(f+4)=30; f[6]=0; f[7]=(u8)state; f[8]=1;
  u32 vec[3]={(u32)f,(u32)(f+10),(u32)(f+10)};
  u8 *o=(u8*)malloc(0x20); memset(o,0,0x20);
  u32 ts[2]={0,0}; clock_gettime(2,ts); u32 ms=hms?hms:ts[0]*1000+ts[1]/1000000;   /* hms: hora em que o Mac enviou o toque (o laço do HMI ocioso só roda ~1 vez por segundo e juntaria descida e subida) */
  ((void*(*)(void*,void*,u32,u32,u32))0x2a26914)(o,vec,0,ms,1);
  u32 *cb=(u32*)malloc(16); cb[0]=0x39e2900; cb[1]=0x10000000; cb[2]=1; cb[3]=(u32)o;
  u32 sp[2]={(u32)o,(u32)cb};
  ((void(*)(void*,void*))0x2a22600)(tdc_client,sp);   /* forwardTouchData (assíncrono): enfileira forwardTouchDataSync no processo certo, como o driver faria */
}
/* no thread principal */
static void input_main(u8 *pu){
  /* o tratamento de uma tecla pode rodar um laço aninhado e voltar a updateAliveTime: sem esta trava, o mesmo evento era tratado sem fim (HMI travado, morto pelo watchdog) */
  static int busy; if(busy) return; busy=1;
  while(ring_r!=__atomic_load_n(&ring_w,__ATOMIC_ACQUIRE)){ u32 ee[4]; memcpy(ee,ring[ring_r%RINGN],16); __atomic_add_fetch(&ring_r,1,__ATOMIC_RELEASE); u32 *e=ee;
    if(e[0]==1&&e[3]==1){ push_ctrl(e[1],e[2]!=0,1); }
    else if(e[0]==40){ touch_send(e[1],e[2]&0xffff,e[2]>>16,e[3]==0xffff?0:e[3]); }
    else if(e[0]==9){ void*h=hook_home(); br_logx("home app",(u32)h,h?*((u8*)h+0x338):0,0); if(h) ((void(*)(void*,int))0x2f7114)(h,e[1]); }
    else if(e[0]==7){ u8 *o=((u8*(*)(void))0x228384)(); u8 *x=o?*(u8**)(o+8):0; u8 *h=x?((u8*(*)(void*))0x60af10)(x):0; br_logx("dbg obj",(u32)o,(u32)x,(u32)h); if(h){ u32 vt=*(u32*)h; br_logx("dbg handler vt",vt,*(u32*)(vt+0xc),*(u32*)(vt+8)); } }
    else if(e[0]==6){ br_logx("force display",(u32)disp_svc,disp_svc?disp_svc[0x3c]:0,disp_svc?disp_svc[0x3d]:0); if(disp_svc){ disp_svc[0x3c]=1; disp_svc[0x3d]=1; ((void(*)(void*,int))0x2df744)(disp_svc,1); } }
    else if(e[0]==5){ u8*h=(u8*)hook_home(); if(h){ br_logx("home flags",h[0x338]|h[0x339]<<8|h[0x33a]<<16|h[0x33b]<<24,h[0x33c],e[1]); h[0x33b]=e[1]; h[0x33a]=e[2]; } }
    else if(e[0]==8){ void*h=hook_home(); int N=-1; for(int o=-0x2000;o<0x2000&&h;o+=4){ if(*(void**)(pu+o+0x990)==h){ N=o; break; } } br_logx("powermode this-offset",N,(u32)h,e[1]); if(N!=-1) ((void(*)(void*,u32))0x2152c4)(pu+N,e[1]); }
    else if(e[0]==1){ /* button: key event + controller event, as CHmiCCSController::onCCSPushButton does */
      ((void(*)(u32,u32,u32,u32))0x2dd6fc)(e[1],e[2]!=0,0,0); push_ctrl(e[1],e[2]!=0,1); }
  }
  if(ilm_main_want&&ilm_main_cb){ ilm_main_want=0; ilm_main_cb(); }
  busy=0; }
static void *home_app; void *hook_home(void){ return home_app; } static int (*stc_tramp)(void*,u32,u32,u32);
static int hk_stc(void *t,u32 a,u32 b,u32 c){ home_app=t; return stc_tramp(t,a,b,c); }
static u32 (*reg_tramp)(void*,void*,u32,u32,u32,u32);
static u32 hk_reg(void *pu,void *tgt,u32 fn,u32 adj,u32 grp,u32 ty){ if(grp==*(u16*)0x3af08cc||(u16)grp==*(u16*)0x3af08cc) br_logx("reg ctrl listener",fn,(u32)tgt,ty); return reg_tramp(pu,tgt,fn,adj,grp,ty); }
static u32 (*add_tramp)(void*,void*,u32,u32,u32,u32);
static u32 hk_add(void *d,void *tgt,u32 fn,u32 adj,u32 grp,u32 ty){ if((u16)grp==*(u16*)0x3af08cc) { u32 vt=*(u32*)tgt; br_logx("add ctrl listener",fn,(u32)tgt,vt); if(fn<0x1000){ br_logx(" virt target",*(u32*)(vt+fn),adj,0); } } return add_tramp(d,tgt,fn,adj,grp,ty); }
extern int snprintf(char*,unsigned long,const char*,...);
void hk_bt(const char*tag){ volatile u32 m; u32 *sp=(u32*)&m; char b[260]; int n=0,c=0; n=snprintf(b,260,"BT %s:",tag); for(int i=0;i<500&&c<14&&n<230;i++){ u32 w=sp[i]; if(w>0x100000&&w<0x3000000&&!(w&3)){ u32 ins=*(u32*)(w-4); if((ins&0x0f000000)==0x0b000000||(ins&0x0ffffff0)==0x012fff30){ n+=snprintf(b+n,260-n," %x",w); c++; } } } br_log(b); }
static u32 (*wh_tramp)(void*,u32,u32,u32);
static u32 hk_wh(void *t,u32 a,u32 b,u32 c){ static int n; if(n++<8){ br_logx("widget handle",(u32)t,a,b); hk_bt("wh"); } return wh_tramp(t,a,b,c); }
static u32 (*lh_tramp)(void*,u32,u32,u32,u32); static u32 (*ch_tramp)(void*,u32,u32,u32,u32);
static u32 hk_lh(void *t,u32 a,u32 b,u32 c,u32 d){ u32 r=lh_tramp(t,a,b,c,d); br_logx("list handler",a,b,r); return r; }
static u32 hk_ch(void *t,u32 a,u32 b,u32 c,u32 d){ u32 r=ch_tramp(t,a,b,c,d); br_logx("container handler",a,b,r); return r; }
static u32 hk_pmd(void){ return 0x64; } /* PMD_Fullon_useron */
static u32 hk_pm(void){ return 3; }     /* PM_fullon_useron */
static u32 (*eds_tramp)(void*,u32,u32,u32);
static u32 hk_eds(void *t,u32 a,u32 b,u32 c){ if(!disp_svc) br_logx("display service",(u32)t,0,0); disp_svc=(u8*)t; return eds_tramp(t,a,b,c); }
static u32 (*eds2_tramp)(void*,u32,u32,u32);
static u32 hk_eds2(void *t,u32 a,u32 b,u32 c){ if(!disp_svc) br_logx("display service (2)",(u32)t,0,0); disp_svc=(u8*)t; return eds2_tramp(t,a,b,c); }
static void (*alive_tramp)(void*);
extern int usleep(unsigned);
/* IDEmu diag (timing): guest tick size, how long sleeps really take, and how long one input poll (bridge round trip) takes. Logging only. */
extern int ClockPeriod(int,const void*,void*,int);
static u32 now_us(void){ u32 ts[2]={0,0}; clock_gettime(2,ts); return ts[0]*1000000u+ts[1]/1000u; }
u32 tm_now_us(void){ return now_us(); }
static void timing_probe(void){ u32 cp[2]={0,0}; int r=ClockPeriod(0,0,cp,0); br_logx("timing: ClockPeriod ns (ret)",cp[0],(u32)r,0);
  static const u32 req[3]={1000,5000,16000}; for(int k=0;k<3;k++){ u32 mx=0,sum=0; for(int i=0;i<8;i++){ u32 t=now_us(); usleep(req[k]); u32 d=now_us()-t; sum+=d; if(d>mx) mx=d; } br_logx("timing: usleep us req/avg/max",req[k],sum/8,mx); } }
static void *input_thread(void *a){ timing_probe(); u32 mx=0,n=0,sum=0,t0=now_us();
  for(;;){ u32 t=now_us(); usleep(15000); u32 t1=now_us(); input_pump(); u32 t2=now_us(); u32 per=t2-t; sum+=per; n++; if(t2-t1>mx) mx=t2-t1;
    if(t2-t0>10000000u){ br_logx("timing: input poll period avg us / pump max us / polls",sum/(n?n:1),mx,n); br_logx("timing: pump lock-wait max us / swaps / swap max us",tm_pump_lock,tm_swap_n,tm_swap_max);
      br_logx("timing: swap lock-wait max us / flushes / flushed KB",tm_swap_lock,tm_flush_n,tm_flush_bytes>>10); br_logx("timing: syncs / sync total ms / sync max us",tm_sync_n,tm_sync_us/1000,tm_sync_max); br_logx("timing: rotary push max us / main unit id",tm_push_max,main_pu?main_pu[0xce]:0,0); tm_push_max=0;
      tm_pump_lock=tm_swap_n=tm_swap_max=tm_swap_lock=tm_flush_n=tm_flush_bytes=tm_sync_n=tm_sync_us=tm_sync_max=0; mx=0; n=0; sum=0; t0=t2; } } return 0; }
/* Each HMI proc unit thread passes through updateAliveTime (the app unit 100 = 0x64 and tHMI_Platform 102). main_pu used to follow whichever ran last, so knob turns and
   the wake-up event were pushed into the platform unit about half the time. Once the app unit has shown up, only it is used; until then, the old behaviour. */
static int app_pu_seen;
static void hk_alive(void *t){ static int n; if(t==((void*(*)(void))0x20f518)()){ u8 uid=((u8*)t)[0xce]; if(n<6&&(u8*)t!=main_pu){ n++; br_logx("alive on unit (ptr/id)",(u32)t,uid,0); } if(uid==0x64) app_pu_seen=1; if(uid!=0x64&&app_pu_seen){ alive_tramp(t); return; } main_pu=(u8*)t; if(uid==0x64) auto_power_on();   /* só no proc unit do app (100): hk_alive passa em todo proc unit (getHmiProcUnit é por thread) e ligar pelo tHMI_Platform (102) derrubava o HMI */ input_main((u8*)t); { static int started; static u32 tid[8]; if(!started){ started=1; pthread_create(tid,0,input_thread,0); extern void hsfz_start(void); hsfz_start(); } } } alive_tramp(t); }
static void (*lua_err_tramp)(u8*);
static void hk_luaerr(u8 *L){ u8 *top=*(u8**)(L+8); u32 v=*(u32*)(top-16); u32 tt=*(u32*)(top-8); static int n; if(n<400&&tt==4&&v){ n++; char b[250]; const char*m=(const char*)(v+16); u32 i=0; b[0]='L';b[1]='U';b[2]='A';b[3]=':';b[4]=' '; while(m[i]&&i<230){ b[5+i]=m[i]; i++; } b[5+i]=0; br_log(b); } lua_err_tramp(L); }
/* IDEmu diag: log every distinct (variant id -> result) the HMI asks; optional overrides from /fs/shim/variants.bin (u32 LE: id | forced<<31) */
static u32 (*isv_tramp)(void*,u32);
static u8 isv_seen[8192]; static u32 isv_force[512]; static u32 nforce, force_loaded;
static void isv_load(void){ if(force_loaded) return; force_loaded=1; int fd=open("/fs/shim/variants.bin",0); if(fd<0) return; long n=0,r; static u8 b[2048] __attribute__((aligned(4))); while(n<(long)sizeof b&&(r=read(fd,b+n,sizeof b-n))>0) n+=r; close(fd); nforce=(u32)n/4; for(u32 i=0;i<nforce;i++) isv_force[i]=((u32*)b)[i]; br_logx("variants: overrides",nforce,0,0); }
static u32 hk_isv(void *t,u32 id){ isv_load(); u32 r=isv_tramp(t,id)&0xff; u32 i; for(i=0;i<nforce;i++) if((isv_force[i]&0xffff)==id){ r=isv_force[i]>>31; break; }
  if(id<65536&&!(isv_seen[id>>3]&(1<<(id&7)))){ isv_seen[id>>3]|=(1<<(id&7)); br_logx("variant",id,r,i<nforce); } return r; }
/* diag: CDevCarTpmStatusImpl::updateStatus (0xd98b44): estado interno depois de cada chamada */
/* O RDC real reenvia telegramas continuamente; no emulador o valor de CTyresStatus e fixo. O temporizador de 17,5 s (relogio do guest ~6x mais rapido que o do host) do
   CDevCarTpmStatusImpl (callback 0xd99218) declararia "sem dados" (estado 0x60 -> traços no lugar das pressões): neutralizado. */
static void hk_tpm_timer(void){ }
static void (*tpm_tramp)(u8*);
static void hk_tpm(u8 *t){ tpm_tramp(t); static u32 last[4]; static u32 n; u32 a=(u32)t[0x60]|((u32)t[0x68]<<8)|((u32)t[0x69]<<16)|((u32)t[0x6a]<<24); u32 b=(u32)t[0x0c]|((u32)t[0x58]<<8)|((u32)t[0x70]<<16)|((u32)t[0x6d]<<24); u32 c=(u32)t[0x6e]|((u32)t[0x6f]<<8);
  if(n<200&&(a!=last[0]||b!=last[1]||c!=last[2])){ last[0]=a;last[1]=b;last[2]=c; n++; br_logx("tpm: st60|68|69|6a",a,b,c); } }
/* Mapa: sem o processo de navegacao nao ha LayerManager para criar /dev/layermanager_<n>_{img,cmd}. CHmiSurfaceRedirection::mapSurfaceBuffer (0x2a0d728)
   so precisa preencher SharedSurface (+8 tamanho, +0xc imagem, +0x10 RemoteImageData); os pixels ficam na textura do host (OP_MAPBIND, src/glhost/map.c). */
extern u32 map_cur[3]; extern int pthread_mutex_init(void*,const void*); extern int getpid(void); extern int munmap(void*,unsigned long);
static int hk_mapsurf(void *self,u32 surf,u32 w,u32 h,u8 *out){ if(!w||!h) return 0; u32 len=w*h*4; void *img=mmap(0,len,0x300,0x80002,-1,0); if((int)img==-1){ br_logx("map: sem memoria",surf,w,h); return 0; }
  u32 *m=(u32*)calloc(1,0x38); m[0]=8; m[1]=w; m[2]=h; m[3]=w*4; m[4]=getpid(); pthread_mutex_init(m+5,0); *(u32*)(out+8)=len; *(void**)(out+0xc)=img; *(void**)(out+0x10)=m;
  map_cur[0]=surf; map_cur[1]=w; map_cur[2]=h; br_logx("map: superficie criada",surf,w,h); return 1; }
static void hk_unmapsurf(void *self,u32 surf,u8 *sh){ void *img=*(void**)(sh+0xc); u32 len=*(u32*)(sh+8); void *m=*(void**)(sh+0x10); if(img) munmap(img,len); if(m) free(m); *(u32*)(sh+8)=0; *(u32*)(sh+0xc)=0; *(u32*)(sh+0x10)=0; br_logx("map: superficie removida",surf,0,0); }
/* diagnóstico: sem o gerenciador de falhas do carro, uma queda do HMI não deixava rastro; registra de onde veio e devolve ao tratamento padrão */
extern void (*signal(int,void(*)(int)))(int);
static void crash_h(int sg,u32 *info,u32 *uc){ static int n; if(n++==0){ br_logx("CRASH sinal",(u32)sg,(u32)info,(u32)uc);
    if((u32)info>0x1000&&(u32)info<0xf0000000){ br_logx("CRASH info",info[0],info[1],info[2]); br_logx("CRASH info2",info[3],info[4],info[5]); }
    if((u32)uc>0x1000&&(u32)uc<0xf0000000){ for(int i=0;i<64;i+=4) if(uc[i]||uc[i+1]||uc[i+2]||uc[i+3]){ br_logx("CRASH ctx",i,uc[i],uc[i+1]); br_logx(" ",uc[i+2],uc[i+3],0); } }
    hk_bt("crash"); } signal(sg,(void(*)(int))0); }
/* IDEmu: registrador de quedas. Instalado só no "auto power on" (não no boot: ver CRASHHK acima). Na primeira falha registra sinal, thread,
   endereço da instrução e do acesso, registradores e uma pilha resolvida por dladdr; depois devolve o tratamento anterior e retorna: a instrução
   falha de novo e o processo termina exatamente como antes (mesmo código de saída). */
typedef struct { const char *fname; void *fbase; const char *sname; void *saddr; } crash_dli;
struct crash_sa { void *h; int flags; u32 mask[2]; };          /* layout do sigaction do QNX (libc: abort() usa +8 como máscara) */
extern int dladdr(void*,crash_dli*); extern int sigaction(int,const void*,void*); extern int raise(int);
extern u32 pthread_self(void); extern int pthread_getname_np(u32,char*,int);
static struct crash_sa crash_prev[12]; static volatile int crash_busy;
static int crash_ptr_ok(u32 p){ return p>0x1000&&p<0xf0000000&&!(p&3); }
static void crash_log(const char*s,u32 a,u32 b,u32 c){ for(int i=0;i<4000&&br_lock_v;i++) sched_yield(); br_lock_v=0; br_logx(s,a,b,c); }  /* a thread que caiu pode estar com a trava da ponte */
static int crash_where(u32 a,char*b,int n){ crash_dli di; if(!a||!dladdr((void*)a,&di)||!di.fname) return snprintf(b,n," %x(?)",a);
  const char*f=di.fname,*q=f; while(*q){ if(*q=='/') f=q+1; q++; } u32 base=(u32)di.fbase; if(base>a) base=0;
  if(di.sname&&di.saddr) return snprintf(b,n," %x(%s+%x %s+%x)",a,f,a-base,di.sname,a-(u32)di.saddr); return snprintf(b,n," %x(%s+%x)",a,f,a-base); }
static void crash_h2(int sg,u32 *info,u32 *uc){ int k=(sg>=0&&sg<12)?sg:0;
  sigaction(sg,&crash_prev[k],0);                                  /* qualquer nova falha (inclusive aqui dentro) vai ao tratamento anterior */
  if(__atomic_exchange_n(&crash_busy,1,__ATOMIC_ACQ_REL)) return;
  char b[300]; int n; u32 ip=0,sp=0,lr=0; char nm[48]; nm[0]=0; pthread_getname_np(pthread_self(),nm,sizeof nm);
  n=snprintf(b,sizeof b,"CRASH sinal %d thread %d (%s)",sg,(int)pthread_self(),nm[0]?nm:"sem nome"); crash_log(b,sg,0,0);
  if(crash_ptr_ok((u32)info)){ ip=info[4]; crash_log("CRASH si_code fltno addr",info[1],info[3],info[5]); }
  if(crash_ptr_ok((u32)uc)){ int r=-1; for(int i=15;i<48;i++) if(ip&&uc[i]==ip){ r=i-15; break; }
    if(r>=0){ u32*g=uc+r; n=snprintf(b,sizeof b,"CRASH regs"); for(int i=0;i<16&&n<280;i++) n+=snprintf(b+n,sizeof b-n," r%d=%x",i,g[i]); crash_log(b,0,0,0); sp=g[13]; lr=g[14]; }
    else for(int i=0;i<40;i+=4) crash_log("CRASH ctx",uc[i],uc[i+1],uc[i+2]); }
  n=snprintf(b,sizeof b,"CRASH pc"); crash_where(ip,b+n,sizeof b-n); crash_log(b,0,0,0);
  n=snprintf(b,sizeof b,"CRASH lr"); crash_where(lr,b+n,sizeof b-n); crash_log(b,0,0,0);
  /* pilha: palavras que apontam para logo depois de um BL/BLX dentro de código carregado (dladdr confirma antes de ler a instrução) */
  { volatile u32 here; u32 *s=crash_ptr_ok(sp)?(u32*)sp:(u32*)&here; int c=0; n=snprintf(b,sizeof b,"CRASH stack");
    for(int i=0;i<2048&&c<12;i++){ u32 w=s[i]; crash_dli di; if(w<0x100000||(w&3)||!dladdr((void*)w,&di)) continue; u32 ins=*(u32*)(w-4);
      if((ins&0x0f000000)==0x0b000000||(ins&0xfe000000)==0xfa000000||(ins&0x0ffffff0)==0x012fff30){ if(n>200){ crash_log(b,0,0,0); n=snprintf(b,sizeof b,"CRASH stack+"); } n+=crash_where(w,b+n,sizeof b-n); c++; } }
    crash_log(b,0,0,0); }
  if(!crash_ptr_ok((u32)info)||(int)info[1]<=0) raise(sg);          /* sinal enviado (kill/raise), não falha de CPU: repete para o tratamento anterior */
}
static void crash_install(void){ static int done; if(done) return; done=1; static const int sigs[]={4,8,10,11};
  for(int i=0;i<4;i++){ struct crash_sa a; memset(&a,0,sizeof a); a.h=(void*)crash_h2; a.flags=2; /* SA_SIGINFO */ sigaction(sigs[i],&a,&crash_prev[sigs[i]]); }
  br_log("crash logger: instalado"); }
void install_hooks(void){ static int done; if(done) return; done=1;
#ifdef CRASHHK   /* diagnóstico de quedas (-DCRASHHK): ligado, o iDrive 5 não termina de subir (sinal capturado no boot); desligado por padrão */
  signal(11,(void(*)(int))crash_h); signal(10,(void(*)(int))crash_h); signal(4,(void(*)(int))crash_h); signal(8,(void(*)(int))crash_h);
#endif
  eds_tramp=(u32(*)(void*,u32,u32,u32))hk_tramp(0x2df744,hk_eds); eds2_tramp=(u32(*)(void*,u32,u32,u32))hk_tramp(0x2dfe98,hk_eds2);
  tdc_c1=(void*(*)(void*,u32,u32))hk_tdc_tramp(0x2a24660,hk_tdc_a); tdc_c2=(void*(*)(void*,u32,u32))hk_tdc_tramp(0x2a24e48,hk_tdc_b);
  hk_patch((void*)0x2a0d728,hk_mapsurf); hk_patch((void*)0x2a0cd04,hk_unmapsurf);
  lua_err_tramp=(void(*)(u8*))hk_tramp(0x2a4e9b8,hk_luaerr);
  stc_tramp=(int(*)(void*,u32,u32,u32))hk_tramp(0x2f9308,hk_stc);
  hk_patch((void*)0x18d8800,hk_pmd); hk_patch((void*)0x18d8ef8,hk_pm);
  { void *a=hk_sym("libhmicom.so","_ZN12CHmiProcUnit15updateAliveTimeEv"); if(a) alive_tramp=(void(*)(void*))hk_tramp((u32)a,hk_alive); }
  { static u32 tid; pu_c2=hk_sym("libhmicom.so","_ZN12CHmiProcUnitC2ER18CHmiMainDispatcherh"); if(pu_c2){ pu_saved[0]=((u32*)pu_c2)[0]; pu_saved[1]=((u32*)pu_c2)[1]; hk_patch(pu_c2,hk_pu_c2); } }
  getdef=(int(*)(u32,const u8**,u32*))hk_sym("libhmicoding.so","sysetDefaults_getBuffer");
  dsi_ctor=(void*(*)(void*,u16))hk_sym("libhmicoding.so","_ZN16CDsiBinaryStreamC1Et");
  hk("libhmicoding.so","_ZN16CDsiBinaryStream15readCodingBlockEPvj",hk_readCodingBlock);
  hk("libhmicoding.so","_ZN17CHmiCodingService16openBinaryStreamEPK14CODING_FEATURE",hk_openBinaryStream);
  hk("libhmicoding.so","_ZN17CHmiVariantServer15isVACodingValidEv",hk_true);
  tpm_tramp=(void(*)(u8*))hk_tramp(0xd98b44,hk_tpm);
  hk_patch((void*)0xd99218,hk_tpm_timer);
  { void *a=hk_sym("libhmicoding.so","_ZN17CHmiVariantServer12isVariantSetEj"); if(a) isv_tramp=(u32(*)(void*,u32))hk_tramp((u32)a,hk_isv); }
}

/* IDEmu: emulated ZGW diagnostic gateway (HSFZ, TCP 6801) for apps on the head unit, such as the BoostDeck collector.
   Runs as threads inside HmiMain3D (which already has the socket library loaded) and only when the builder wrote
   /fs/shim/hsfz.cfg. rc.sh puts the gateway addresses from that file on lo0, so a tool that connects to the car's
   gateway (169.254.x.x:6801) reaches this listener.

   Each UDS request goes to the host over UART1 as a text line "Q <seq> <src> <tgt> <hex>". The host (idemu/uds.py)
   answers "U <seq> <hex>" ("-" = no reply), the guest agent (agent.sh, the reader of /dev/ser5) writes the answer to
   /var/idemu/uds/<seq>, and this thread picks it up and sends the HSFZ reply. */
#include "common.h"
extern void *dlopen(const char*,int); extern void *dlsym(void*,const char*);
extern int pthread_create(void*,const void*,void*(*)(void*),void*);
extern int snprintf(char*,unsigned long,const char*,...);
extern int unlink(const char*);
extern long read(int,void*,unsigned long);

typedef struct { u8 len, family; u16 port; u32 addr; u8 zero[8]; } sin_t;    /* BSD sockaddr_in (QNX io-pkt) */
static int (*s_socket)(int,int,int); static int (*s_setsockopt)(int,int,int,const void*,int);
static int (*s_bind)(int,const void*,int); static int (*s_listen)(int,int); static int (*s_accept)(int,void*,void*);
static long (*s_recv)(int,void*,unsigned long,int); static long (*s_send)(int,const void*,unsigned long,int);
static int (*s_open)(const char*,int,...);       /* libc's own open: the shim's open() logs every missing file */
static int ser = -1;
static u32 seq;

static int rd(int fd, u8 *b, u32 n){ while(n){ long k=s_recv(fd,b,n,0); if(k<=0) return 0; b+=k; n-=(u32)k; } return 1; }
static int wr(int fd, const u8 *b, u32 n){ while(n){ long k=s_send(fd,b,n,0); if(k<=0) return 0; b+=k; n-=(u32)k; } return 1; }
static void be32(u8 *p,u32 v){ p[0]=v>>24; p[1]=v>>16; p[2]=v>>8; p[3]=v; }
static int hexv(int c){ return c>='0'&&c<='9'?c-'0':c>='A'&&c<='F'?c-'A'+10:c>='a'&&c<='f'?c-'a'+10:-1; }

static int hsfz_send(int fd, u16 ctrl, u8 a, u8 b, const u8 *d, u32 n){
  u8 out[2048+8]; if(n>2048) n=2048;
  be32(out,n+2); out[4]=ctrl>>8; out[5]=(u8)ctrl; out[6]=a; out[7]=b; memcpy(out+8,d,n);
  return wr(fd,out,8+n);
}

/* one request to the host; returns reply length, 0 for "no reply", -1 for no answer from the host */
static int ask_host(u8 src, u8 tgt, const u8 *req, u32 n, u8 *rep, u32 cap){
  static const char hx[]="0123456789ABCDEF";
  char line[2200]; if(n>1000) n=1000;
  u32 s=__atomic_add_fetch(&seq,1,__ATOMIC_RELAXED);
  int k=snprintf(line,sizeof line,"Q %u %02X %02X ",s,src,tgt);
  for(u32 i=0;i<n;i++){ line[k++]=hx[req[i]>>4]; line[k++]=hx[req[i]&15]; }
  line[k++]='\n';
  if(ser<0||write(ser,line,k)!=k) return -1;
  char path[64]; snprintf(path,sizeof path,"/var/idemu/uds/%u",s);
  for(int w=0;w<1000;w++){                        /* up to ~2 s */
    int fd=s_open(path,0);
    if(fd>=0){
      char buf[2200]; long m=read(fd,buf,sizeof buf-1); close(fd);
      if(m>0&&buf[m-1]=='\n'){
        unlink(path);
        if(buf[0]=='-') return 0;
        u32 r=0; for(long i=0;i+1<m&&r<cap;i+=2){ int a=hexv(buf[i]),b=hexv(buf[i+1]); if(a<0||b<0) break; rep[r++]=(u8)(a<<4|b); }
        return (int)r;
      }
    }
    usleep(2000);
  }
  return -1;
}

static void *client(void *arg){
  int fd=(int)(long)arg;
  u8 hdr[6], *msg=(u8*)malloc(8200), *rep=(u8*)malloc(2048);
  while(msg&&rep&&rd(fd,hdr,6)){
    u32 len=(u32)hdr[0]<<24|(u32)hdr[1]<<16|(u32)hdr[2]<<8|hdr[3]; u16 ctrl=(u16)(hdr[4]<<8|hdr[5]);
    if(len>8192||!rd(fd,msg,len)) break;
    if(ctrl!=1||len<3) continue;                  /* only diagnostic messages; alive checks and the rest are ignored */
    u8 src=msg[0], tgt=msg[1];
    if(!hsfz_send(fd,2,src,tgt,msg+2,len-2>4?4:len-2)) break;    /* acknowledge, as the ZGW does */
    int r=ask_host(src,tgt,msg+2,len-2,rep,2048);
    if(r>0&&!hsfz_send(fd,1,tgt,src,rep,(u32)r)) break;          /* 0 = ECU stays silent, -1 = host did not answer */
  }
  free(msg); free(rep); close(fd);
  return 0;
}

static void *server(void *arg){
  (void)arg;
  void *so=dlopen("libsocket.so.3",2); if(!so) so=dlopen("libsocket.so.2",2);
  void *lc=dlopen("libc.so.3",2);
  if(!so||!lc){ br_log("hsfz: libsocket not found"); return 0; }
  s_socket=dlsym(so,"socket"); s_setsockopt=dlsym(so,"setsockopt"); s_bind=dlsym(so,"bind"); s_listen=dlsym(so,"listen");
  s_accept=dlsym(so,"accept"); s_recv=dlsym(so,"recv"); s_send=dlsym(so,"send"); s_open=dlsym(lc,"open");
  if(!s_socket||!s_bind||!s_listen||!s_accept||!s_recv||!s_send||!s_open){ br_log("hsfz: socket functions missing"); return 0; }
  ser=s_open("/dev/ser5",1);
  if(ser<0) br_log("hsfz: cannot open /dev/ser5 (UART1 to the host)");
  for(int attempt=0;;attempt++){
    int ls=s_socket(2,1,0);
    if(ls>=0){
      int one=1; s_setsockopt(ls,0xffff,4,&one,sizeof one);           /* SOL_SOCKET, SO_REUSEADDR */
      sin_t a; memset(&a,0,sizeof a); a.len=sizeof a; a.family=2; a.port=(u16)((6801>>8)|((6801&255)<<8));
      if(s_bind(ls,&a,sizeof a)==0&&s_listen(ls,4)==0){
        br_logx("hsfz: gateway listening on port 6801",(u32)ls,(u32)ser,0);
        for(;;){
          int c=s_accept(ls,0,0); if(c<0){ usleep(100000); continue; }
          int nd=1; s_setsockopt(c,6,1,&nd,sizeof nd);                    /* IPPROTO_TCP, TCP_NODELAY */
          u32 tid; if(pthread_create(&tid,0,client,(void*)(long)c)) close(c);
        }
      }
      close(ls);
    }
    if(attempt==0) br_log("hsfz: could not listen on 6801 yet, retrying");
    usleep(2000000);
  }
  return 0;
}

void hsfz_start(void){
  static int started; if(started) return; started=1;
  void *lc=dlopen("libc.so.3",2); int (*ro)(const char*,int,...)=lc?dlsym(lc,"open"):0;
  int fd=ro?ro("/fs/shim/hsfz.cfg",0):-1; if(fd<0) return;     /* gateway emulation is off for this environment */
  close(fd);
  u32 tid; pthread_create(&tid,0,server,0);
}

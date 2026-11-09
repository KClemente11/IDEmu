// ustk <pid> [comm]: lista candidatos a endereço de retorno na pilha de cada thread (depuração)
typedef unsigned long u64; typedef long i64;
typedef struct FILE FILE; extern FILE *fopen(const char*,const char*); extern char *fgets(char*,int,FILE*); extern int fclose(FILE*);
extern int printf(const char*,...); extern int sscanf(const char*,const char*,...); extern char *strstr(const char*,const char*); extern int atoi(const char*); extern int snprintf(char*,u64,const char*,...);
extern int open(const char*,int,...); extern i64 pread(int,void*,u64,i64); extern int close(int);
typedef struct DIR DIR; struct dirent{u64 ino;i64 off;unsigned short rl;unsigned char t;char name[256];}; extern DIR *opendir(const char*); extern struct dirent *readdir(DIR*);
extern char *strchr(const char*,int); extern int strcmp(const char*,const char*); extern int fflush(FILE*); extern u64 strlen(const char*);
static struct{u64 a,b,o;char n[64];} m[4096]; int nm;
int main(int c,char**v){int pid=atoi(v[1]); char p[128],l[512]; snprintf(p,128,"/proc/%d/maps",pid); FILE*f=fopen(p,"r");
 while(f&&fgets(l,512,f)&&nm<4096){u64 a,b,o;char pr[8],nmz[256];nmz[0]=0; int d; if(sscanf(l,"%lx-%lx %7s %lx %*s %*d %255s",&a,&b,pr,&o,nmz)>=4&&pr[2]=='x'){m[nm].a=a;m[nm].b=b;m[nm].o=o;char*s=nmz,*q;while((q=strchr(s,'/')))s=q+1;int i=0;while(s[i]&&i<63){m[nm].n[i]=s[i];i++;}m[nm].n[i]=0;nm++;}}
 if(f)fclose(f);
 snprintf(p,128,"/proc/%d/task",pid); DIR*d=opendir(p); struct dirent*e; snprintf(l,64,"/proc/%d/mem",pid); int mf=open(l,0);
 while((e=readdir(d))){ if(e->name[0]=='.')continue; char q[128],cm[64]={0},sc[256]={0}; snprintf(q,128,"/proc/%d/task/%s/comm",pid,e->name); FILE*g=fopen(q,"r"); if(g){fgets(cm,64,g);fclose(g);} cm[strlen(cm)?strlen(cm)-1:0]=0;
  if(c>2&&strcmp(cm,v[2]))continue;
  snprintf(q,128,"/proc/%d/task/%s/syscall",pid,e->name); g=fopen(q,"r"); if(!g)continue; fgets(sc,256,g); fclose(g);
  u64 x[9]; int nr; if(sscanf(sc,"%d %lx %lx %lx %lx %lx %lx %lx %lx",&nr,&x[0],&x[1],&x[2],&x[3],&x[4],&x[5],&x[6],&x[7])<9){continue;}
  u64 sp=x[6]; static u64 buf[8192]; i64 r=pread(mf,buf,sizeof buf,sp); printf("T %s %s sc=%d pc=%lx\n",e->name,cm,nr,x[7]); int cnt=0;
  for(int i=0;i<r/8&&cnt<48;i++){u64 w=buf[i]; for(int k=0;k<nm;k++) if(w>=m[k].a&&w<m[k].b){printf(" %s+%lx\n",m[k].n,w-m[k].a+m[k].o);cnt++;break;}}
 }
 return 0;}

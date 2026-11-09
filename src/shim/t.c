typedef unsigned int u32;
extern int open(const char*,int,...); extern long write(int,const void*,unsigned long); extern int getpid(void);
int screen_create_context(void**c,int f){ int fd=open("/var/gl.log",0x201|0x8|0x400); write(fd,"hi\n",3); *c=(void*)1; return 0;}

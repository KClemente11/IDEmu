/* panel.c: iDrive controller front-end drawn below the HMI screen (rotor, tilt, hard keys) */
#include <math.h>
enum { KEY_MENU=1,KEY_BACK=2,KEY_OPTION=3,KEY_CD=4,KEY_RADIO=5,KEY_TEL=6,KEY_NAVI=7,KEY_PRESS=8,KEY_N=9,KEY_S=10,KEY_W=11,KEY_E=12,KEY_RIGHT=13,KEY_LEFT=14 };
typedef struct { const char*label; int key; float x,y,w,h; int down; const char *hint; } Btn;
static Btn btns[]={ /* x,y in panel units: 1440 wide, 170 tall */
 {"MENU",KEY_MENU,60,28,120,48,0,"M"},{"BACK",KEY_BACK,60,92,120,48,0,"B"},
 {"OPTION",KEY_OPTION,200,28,120,48,0,"O"},{"RADIO",KEY_RADIO,200,92,120,48,0,"R"},
 {"MEDIA",KEY_CD,340,28,120,48,0,"C"},{"NAV",KEY_NAVI,340,92,120,48,0,"N"},
 {"TEL",KEY_TEL,480,28,120,48,0,"T"},
};
#define NBTN (sizeof btns/sizeof btns[0])
#define PANEL_H 170.0f
#define ROTX 820.0f
#define ROTY 85.0f
#define ROTR 62.0f
static float rot_angle; static int rot_drag; static float rot_last, rot_acc; static int rot_press, tilt_key; static int panel_dirty=1; static double boot_msg_t;
static int screen_seen;
static float screen_h(void){ return (float)winw*(float)sh/(float)sw; }
static float panel_scale(void){ return (float)winw/1440.0f; }
static void p2w(float px,float py,float *x,float *y){ float s=panel_scale(); *x=px*s; *y=(float)winh-(screen_h()+py*s); }
static void draw_circle(float cx,float cy,float r,float R,float G,float B,int fill){ glColor3f(R,G,B); glBegin(fill?GL_TRIANGLE_FAN:GL_LINE_LOOP); if(fill) glVertex2f(cx,cy); for(int i=0;i<=64;i++){ float a=i*6.2831853f/64; glVertex2f(cx+cosf(a)*r,cy+sinf(a)*r); } glEnd(); }
static void text(float x,float y,const char*s,void*font){ glRasterPos2f(x,y); while(*s) glutBitmapCharacter(font,*s++); }
static void text_c(float cx,float y,const char*s,void*font){ int w=0; for(const char*p=s;*p;p++) w+=glutBitmapWidth(font,*p); text(cx-w/2.0f,y,s,font); }
static void draw_panel(void){ float s=panel_scale(); glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity(); glOrtho(0,winw,0,winh,-1,1); glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity(); glDisable(GL_TEXTURE_2D); glDisable(GL_BLEND);
  float x0,y0; p2w(0,0,&x0,&y0); float yb=0; glBegin(GL_QUADS); glColor3f(0.075f,0.08f,0.09f); glVertex2f(0,y0); glVertex2f(winw,y0); glColor3f(0.03f,0.03f,0.035f); glVertex2f(winw,yb); glVertex2f(0,yb); glEnd();
  for(unsigned i=0;i<NBTN;i++){ Btn*b=&btns[i]; float x,y; p2w(b->x,b->y,&x,&y); float w=b->w*s,h=b->h*s; float c=b->down?0.32f:0.15f; glBegin(GL_QUADS); glColor3f(c+0.05f,c+0.05f,c+0.06f); glVertex2f(x,y); glVertex2f(x+w,y); glColor3f(c,c,c+0.01f); glVertex2f(x+w,y-h); glVertex2f(x,y-h); glEnd(); glColor3f(0.30f,0.32f,0.36f); glBegin(GL_LINE_LOOP); glVertex2f(x,y); glVertex2f(x+w,y); glVertex2f(x+w,y-h); glVertex2f(x,y-h); glEnd(); glColor3f(0.92f,0.93f,0.95f); text_c(x+w/2,y-h/2-5,b->label,GLUT_BITMAP_HELVETICA_12); glColor3f(0.45f,0.47f,0.52f); text(x+w-14,y-h+4,b->hint,GLUT_BITMAP_HELVETICA_10); }
  /* rotor */
  float cx,cy; p2w(ROTX,ROTY,&cx,&cy); float R=ROTR*s; draw_circle(cx,cy,R+26*s,0.10f,0.105f,0.115f,1); draw_circle(cx,cy,R+26*s,0.26f,0.27f,0.30f,0);
  /* tilt arrows */
  struct { float dx,dy; int k; } t[]={{0,1,KEY_N},{0,-1,KEY_S},{-1,0,KEY_W},{1,0,KEY_E}}; for(int i=0;i<4;i++){ float ax=cx+t[i].dx*(R+14*s),ay=cy+t[i].dy*(R+14*s); float sz=6*s; int on=tilt_key==t[i].k; glColor3f(on?1.0f:0.55f,on?0.5f:0.57f,on?0.1f:0.62f); glBegin(GL_TRIANGLES); glVertex2f(ax+t[i].dx*sz,ay+t[i].dy*sz); glVertex2f(ax-t[i].dx*sz+t[i].dy*sz,ay-t[i].dy*sz+t[i].dx*sz); glVertex2f(ax-t[i].dx*sz-t[i].dy*sz,ay-t[i].dy*sz-t[i].dx*sz); glEnd(); }
  float f=rot_press?0.34f:0.22f; draw_circle(cx,cy,R,f,f,f+0.01f,1); draw_circle(cx,cy,R,0.42f,0.43f,0.46f,0); for(int i=0;i<36;i++){ float a=rot_angle+i*6.2831853f/36; float g=0.34f; glColor3f(g,g,g); glBegin(GL_LINES); glVertex2f(cx+cosf(a)*R*0.86f,cy+sinf(a)*R*0.86f); glVertex2f(cx+cosf(a)*R,cy+sinf(a)*R); glEnd(); }
  draw_circle(cx,cy,R*0.74f,f+0.05f,f+0.05f,f+0.06f,1); { float a=rot_angle; glColor3f(1.0f,0.45f,0.08f); glLineWidth(3); glBegin(GL_LINES); glVertex2f(cx+cosf(a)*R*0.55f,cy+sinf(a)*R*0.55f); glVertex2f(cx+cosf(a)*R*0.72f,cy+sinf(a)*R*0.72f); glEnd(); glLineWidth(1); }
  glColor3f(0.85f,0.86f,0.88f); text_c(cx,cy-4,"iDrive",GLUT_BITMAP_HELVETICA_12);
  /* help */
  glColor3f(0.58f,0.6f,0.65f); float hx,hy; p2w(980,36,&hx,&hy); const char*h[]={"Rotor: arraste, role o trackpad, ou setas Esq/Dir","Pressionar: clique no centro ou Enter/Espaco","Inclinar: setas Cima/Baixo, A / D","Teclas: M B O R C N T   |   F11 tela cheia"}; for(int i=0;i<4;i++) text(hx,hy-i*22*s,h[i],GLUT_BITMAP_HELVETICA_12);
  if(!screen_seen){ float bx,by; p2w(720,-screen_h()/s/2,&bx,&by); glColor3f(0.9f,0.9f,0.92f); text_c(bx,by,"Iniciando o iDrive 6 ... (cerca de 2 minutos)",GLUT_BITMAP_HELVETICA_18); }
  glMatrixMode(GL_PROJECTION); glPopMatrix(); glMatrixMode(GL_MODELVIEW); glPopMatrix(); }
static void send_key(int k,int down){ input_ev(1,k,down,0xffff); panel_dirty=1; }
static void send_rot(int detents){ if(!detents) return; input_ev(2,detents>0?KEY_RIGHT:KEY_LEFT,detents>0?detents:-detents,0xffff); rot_angle-=detents*0.2618f; panel_dirty=1; }
static int in_panel(int x,int y,float *px,float *py){ float s=panel_scale(); float yy=y-screen_h(); if(yy<0) return 0; *px=x/s; *py=yy/s; return 1; }
static Btn *cur_btn; static int cur_tilt;
static void on_mouse(int b,int st,int x,int y){ float px,py; if(b==3||b==4){ if(st==GLUT_DOWN) send_rot(b==3?-1:1); return; } if(b!=GLUT_LEFT_BUTTON) return;
  if(st==GLUT_UP){ if(cur_btn){ cur_btn->down=0; send_key(cur_btn->key,0); cur_btn=0; } if(rot_press){ rot_press=0; send_key(KEY_PRESS,0); } if(cur_tilt){ send_key(cur_tilt,0); cur_tilt=0; tilt_key=0; } rot_drag=0; panel_dirty=1; return; }
  if(!in_panel(x,y,&px,&py)) return; for(unsigned i=0;i<NBTN;i++){ Btn*q=&btns[i]; if(px>=q->x&&px<=q->x+q->w&&py>=q->y&&py<=q->y+q->h){ q->down=1; cur_btn=q; send_key(q->key,1); return; } }
  float dx=px-ROTX,dy=py-ROTY,d=sqrtf(dx*dx+dy*dy); if(d<=ROTR*0.6f){ rot_press=1; send_key(KEY_PRESS,1); return; } if(d<=ROTR){ rot_drag=1; rot_last=atan2f(-dy,dx); rot_acc=0; return; } if(d<=ROTR+28){ int k=fabsf(dx)>fabsf(dy)?(dx>0?KEY_E:KEY_W):(dy>0?KEY_S:KEY_N); cur_tilt=k; tilt_key=k; send_key(k,1); } }
static void on_motion(int x,int y){ float px,py; if(!rot_drag||!in_panel(x,y,&px,&py)) return; float a=atan2f(-(py-ROTY),px-ROTX); float d=a-rot_last; if(d>3.14159f) d-=6.28318f; if(d<-3.14159f) d+=6.28318f; rot_last=a; rot_acc+=d; while(rot_acc<-0.2618f){ rot_acc+=0.2618f; send_rot(1); } while(rot_acc>0.2618f){ rot_acc-=0.2618f; send_rot(-1); } }
static int key_map(unsigned char k){ switch(k>='a'&&k<='z'?k-32:k){ case 'M':return KEY_MENU; case 'B':case 27:return KEY_BACK; case 'O':return KEY_OPTION; case 'R':return KEY_RADIO; case 'C':return KEY_CD; case 'N':return KEY_NAVI; case 'T':return KEY_TEL; case 13:case ' ':return KEY_PRESS; case 'A':return KEY_W; case 'D':return KEY_E; } return 0; }
static void key_vis(int k,int d){ for(unsigned i=0;i<NBTN;i++) if(btns[i].key==k) btns[i].down=d; if(k==KEY_PRESS) rot_press=d; if(k>=KEY_N&&k<=KEY_E) tilt_key=d?k:0; }
static void on_key(unsigned char c,int x,int y){ int k=key_map(c); if(k){ key_vis(k,1); send_key(k,1); } }
static void on_keyup(unsigned char c,int x,int y){ int k=key_map(c); if(k){ key_vis(k,0); send_key(k,0); } }
static void on_special(int c,int x,int y){ switch(c){ case GLUT_KEY_LEFT: send_rot(-1); break; case GLUT_KEY_RIGHT: send_rot(1); break; case GLUT_KEY_UP: key_vis(KEY_N,1); send_key(KEY_N,1); break; case GLUT_KEY_DOWN: key_vis(KEY_S,1); send_key(KEY_S,1); break; case GLUT_KEY_F11: { static int fs; fs=!fs; if(fs) glutFullScreen(); else { glutReshapeWindow(1440,710); } } break; } }
static void on_specialup(int c,int x,int y){ switch(c){ case GLUT_KEY_UP: key_vis(KEY_N,0); send_key(KEY_N,0); break; case GLUT_KEY_DOWN: key_vis(KEY_S,0); send_key(KEY_S,0); break; } }

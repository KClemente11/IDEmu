/* shgen.c: PowerVR SGX binary shaders -> GLSL 1.20. The binaries only keep their symbol table in readable form,
   so the shader body is rebuilt from the symbols (names follow the HMI's conventions). */
typedef struct { char name[64]; int type,cls,flag,arr; } Sym;
typedef struct { int kind,n; Sym s[160]; u32 hash; unsigned char*bin; u32 len; } ShInfo;
#define MAXSH 65536
static ShInfo *shinfo[MAXSH];
static struct { u32 vs,fs; } progbin[MAXSH];
static struct { u32 h; char *n; } *shidx; static int nshidx;
static void load_index(void){ FILE*f=fopen(getenv("GLHOST_SHIDX")?getenv("GLHOST_SHIDX"):"../shd/index.txt","r"); if(!f) return; char l[512]; shidx=calloc(8192,sizeof *shidx); while(fgets(l,512,f)&&nshidx<8192){ u32 h; char nm[480]; if(sscanf(l,"%x %479s",&h,nm)==2){ shidx[nshidx].h=h; shidx[nshidx].n=strdup(nm); nshidx++; } } fclose(f); fprintf(stderr,"[host] shader index: %d\n",nshidx); }
static const char *shname(u32 h){ for(int i=0;i<nshidx;i++) if(shidx[i].h==h) return shidx[i].n; return "?"; }
static u32 fnv1a(const unsigned char*b,u32 n){ u32 h=0x811c9dc5; for(u32 i=0;i<n;i++) h=(h^b[i])*0x01000193; return h; }
static int parse_syms(const unsigned char*b,int len,ShInfo*o){
  o->kind=(b[0x20]<<24|b[0x21]<<16|b[0x22]<<8|b[0x23]); o->n=0;
  for(int p=len-3;p>0x40;p--){
    u32 n=(b[p]<<8)|b[p+1]; if(n==0||n>160) continue;
    int q=p+2,ok=1; u32 i;
    for(i=0;i<n&&ok;i++){ int e=q; while(e<len&&b[e]) { if(b[e]<=32||b[e]>=127){ ok=0; break; } e++; }
      if(!ok||e>=len||e==q||e-q>=64||e+19>len){ ok=0; break; } q=e+19; }
    if(!ok||q!=len) continue;
    q=p+2; for(i=0;i<n;i++){ Sym*s=&o->s[i]; int e=q; while(b[e]) e++; memcpy(s->name,b+q,e-q); s->name[e-q]=0; const unsigned char*x=b+e+1;
      s->flag=x[1]; s->type=x[2]; s->cls=x[3]; s->arr=x[7]; q=e+19; }
    o->n=n; return 1; }
  return 0; }
static const char *reserved[]={"active","common","partition","filter","input","output","half","fixed","sample","texture","class","union","enum","template","this","default","public","static","extern","external","long","short","double","using","flat","smooth","superp","cast","namespace","interface","goto","noise","packed","volatile","inline","noinline",0};
static const char *gname(const char*n){ static char b[8][72]; static int k; for(int i=0;reserved[i];i++) if(!strcmp(n,reserved[i])){ k=(k+1)&7; snprintf(b[k],72,"%s_",n); return b[k]; } return n; }
static const char *gtype(int t){ switch(t){ case 2:return "float"; case 3:return "vec2"; case 4:return "vec3"; case 5:return "vec4"; case 6:return "bool"; case 18:return "mat3"; case 22:return "mat4"; case 20:return "mat2"; case 24:case 30:return "sampler2D"; case 26:return "samplerCube"; } return "float"; }
static Sym *fnd(ShInfo*o,const char*n,int cls){ for(int i=0;i<o->n;i++) if((cls<0||o->s[i].cls==cls)&&!strcmp(o->s[i].name,n)&&!o->s[i].flag) return &o->s[i]; return 0; }
static int ieq(const char*a,const char*b){ return !strcasecmp(a,b); }
static void decls(ShInfo*o,char**pp,int vs){ char*p=*pp;
  for(int i=0;i<o->n;i++){ Sym*s=&o->s[i]; if(s->flag) continue; const char*q=0; if(s->cls==3) q="uniform"; else if(s->cls==4) q="attribute"; else if(s->cls==5&&vs) q="varying"; else if(s->cls==6&&!vs) q="varying"; if(!q) continue;
    if(s->arr>1) p+=sprintf(p,"%s %s %s[%d];\n",q,gtype(s->type),gname(s->name),s->arr); else p+=sprintf(p,"%s %s %s;\n",q,gtype(s->type),gname(s->name)); }
  *pp=p; }
/* a varying of the fragment shader that the vertex shader does not list gets declared too */
#ifndef SZAXIS
#define SZAXIS 'z'
#endif
static char *gen_vs(ShInfo*v,ShInfo*f){ char *o=malloc(32768),*p=o; p+=sprintf(p,"#version 120\n"); decls(v,&p,1);
  for(int i=0;f&&i<f->n;i++){ Sym*s=&f->s[i]; if(s->cls==6&&!s->flag&&!fnd(v,s->name,5)) p+=sprintf(p,"varying %s %s;\n",gtype(s->type),gname(s->name)); }
  p+=sprintf(p,"void main(){\n"); Sym*pos=fnd(v,"a_Position",4); const char*pe="vec4(0.0,0.0,0.0,1.0)"; char pb[80];
  if(pos){ if(pos->type==3) sprintf(pb,"vec4(a_Position,0.0,1.0)"); else if(pos->type==4) sprintf(pb,"vec4(a_Position,1.0)"); else sprintf(pb,"vec4(a_Position.xyz,1.0)"); pe=pb; }
  p+=sprintf(p," vec4 P=%s;\n",pe);
  /* widgets stretched by size uniforms (cursor, frames): TexCoord1 marks which vertices move */
  { const char*tc1=fnd(v,"a_TextureCoordinate1",4)?"a_TextureCoordinate1":(fnd(v,"a_TextureCoordinate",4)?"a_TextureCoordinate":0);
    if(fnd(v,"size_x",3)){ if(tc1) p+=sprintf(p," P.x+=size_x*%s.x;\n",tc1); else p+=sprintf(p," P.x*=size_x;\n"); }
    if(fnd(v,"size_z",3)){ if(tc1) p+=sprintf(p," P.%c+=size_z*%s.y;\n",SZAXIS,tc1); else p+=sprintf(p," P.%c*=size_z;\n",SZAXIS); } }
  if(fnd(v,"u_MVPMatrix",3)) p+=sprintf(p," gl_Position=u_MVPMatrix*P;\n"); else if(fnd(v,"u_MVMatrix",3)&&fnd(v,"u_PMatrix",3)) p+=sprintf(p," gl_Position=u_PMatrix*u_MVMatrix*P;\n"); else if(fnd(v,"u_MVMatrix",3)) p+=sprintf(p," gl_Position=u_MVMatrix*P;\n"); else p+=sprintf(p," gl_Position=P;\n");
  Sym *nav = fnd(v,"nav",3);
  const char *arrow_u = NULL;
  if(nav && nav->type==2 && fnd(v,"a_TextureCoordinate",4)){
    const char *material = shname(v->hash);
    /* Both arrow shaders use nav, but only the tile-order one has a second UV set. */
    if(strstr(material,"/controller_arrow/shaders/mat_arrow.vert.shd"))
      arrow_u = "mix(1.0-a_TextureCoordinate.x,a_TextureCoordinate.x,nav)";
    else if(fnd(v,"a_TextureCoordinate1",4) && strstr(material,"/pad/shaders/WI_HwShader18.vert.shd"))
      arrow_u = "mix(a_TextureCoordinate.x,1.0-a_TextureCoordinate1.x,nav)";
  }
  ShInfo *lists[2]={v,f}; char seen[256][64]; int ns=0;
  for(int L=0;L<2;L++){ ShInfo*o2=lists[L]; if(!o2) continue; for(int i=0;i<o2->n;i++){ Sym*s=&o2->s[i]; if(s->flag||s->cls!=(L==0?5:6)) continue;
    int dup=0; for(int k=0;k<ns;k++) if(!strcmp(seen[k],s->name)) dup=1; if(dup||ns>=256) continue; strcpy(seen[ns++],s->name); if(s->arr>1) continue;
    const char*n=gname(s->name); char u[80]; const char*bare=s->name; if(!strncmp(bare,"v_",2)) bare+=2;
    switch(s->type){
      case 3: { const char*a=NULL; int has1=strchr(s->name,'1')!=0; if(has1&&fnd(v,"a_TextureCoordinate1",4)) a="a_TextureCoordinate1"; else if(fnd(v,"a_TextureCoordinate",4)) a="a_TextureCoordinate"; else if(fnd(v,"a_TextureCoordinate1",4)) a="a_TextureCoordinate1";
        if(arrow_u && !strcmp(s->name,"uv"))
          p+=sprintf(p," %s=vec2(%s,a_TextureCoordinate.y);\n",n,arrow_u);
        else if(a) p+=sprintf(p," %s=%s;\n",n,a); else p+=sprintf(p," %s=P.xy*0.5+0.5;\n",n); break; }
      case 2: { Sym*un=fnd(v,bare,3); if(un&&un->type==2&&strcmp(bare,s->name)) p+=sprintf(p," %s=%s;\n",n,gname(bare)); else p+=sprintf(p," %s=1.0;\n",n); break; }
      case 4: { if(fnd(v,"a_Normal",4)&&(strstr(s->name,"ormal"))) p+=sprintf(p," %s=a_Normal;\n",n); else { const char*c1=0,*c2=0; for(int z=0;z<v->n;z++){ Sym*t=&v->s[z]; if(t->cls==3&&t->type==4&&!strncmp(t->name,"CO",2)){ if(!c1) c1=t->name; else if(!c2) c2=t->name; } }
          if(c1&&c2&&fnd(v,"a_Color",4)) p+=sprintf(p," %s=mix(%s,%s,a_Color.r);\n",n,gname(c1),gname(c2)); else if(c1) p+=sprintf(p," %s=%s;\n",n,gname(c1)); else p+=sprintf(p," %s=vec3(1.0);\n",n); } break; }
      case 5: { if(!strcmp(s->name,"varCoordUVColRG")){ const char*a=fnd(v,"a_TextureCoordinate",4)?"a_TextureCoordinate":"P.xy"; p+=sprintf(p," %s=vec4(%s,1.0,1.0);\n",n,a); }
        else if(fnd(v,"a_Color",4)) { Sym*c=fnd(v,"a_Color",4); p+=sprintf(p,c->type==5?" %s=a_Color;\n":" %s=vec4(a_Color.rgb,1.0);\n",n); }
        else if(fnd(v,"u_color",3)) p+=sprintf(p," %s=u_color;\n",n); else p+=sprintf(p," %s=vec4(1.0);\n",n); break; }
      default: break; }
    (void)u; } }
  p+=sprintf(p,"}\n"); return o; }
static const char* pick_vec2(ShInfo*f){ static const char *pref[]={"uv","uvCoord","varCoord","vTexCoord","v_TexCoord","v_texCoord","texCoord","vTexCoord0","uv0","repeatCoord","staticCoord",0};
  for(int i=0;pref[i];i++){ Sym*s=fnd(f,pref[i],6); if(s&&s->type==3) return s->name; }
  for(int i=0;i<f->n;i++) if(f->s[i].cls==6&&f->s[i].type==3&&!f->s[i].flag) return f->s[i].name; return 0; }
static char *gen_fs(ShInfo*f){ char *o=malloc(32768),*p=o; p+=sprintf(p,"#version 120\n"); decls(f,&p,0);
  const char *tex=0; static const char *tp[]={"tex0","tex","t0","t","DiffuseTex","texture0","s_texture","tex1",0};
  for(int i=0;tp[i]&&!tex;i++){ Sym*s=fnd(f,tp[i],3); if(s&&(s->type==24||s->type==30)) tex=s->name; }
  for(int i=0;i<f->n&&!tex;i++) if(f->s[i].cls==3&&(f->s[i].type==24||f->s[i].type==30)) tex=f->s[i].name;
  const char *uv=pick_vec2(f); char uvb[80]; if(!uv&&fnd(f,"varCoordUVColRG",6)){ uv="varCoordUVColRG.xy"; }
  (void)uvb; p+=sprintf(p,"void main(){\n vec4 col=vec4(1.0);\n");
  if(tex&&uv){ if(fnd(f,"u_useTexture",3)) p+=sprintf(p," if(u_useTexture) col=texture2D(%s,%s);\n",gname(tex),uv); else p+=sprintf(p," col=texture2D(%s,%s);\n",gname(tex),uv);
    if(fnd(f,"u_useRedChannelAsAlpha",3)) p+=sprintf(p," if(u_useRedChannelAsAlpha) col=vec4(1.0,1.0,1.0,col.r);\n"); }
  /* text: glyph alpha only */
  if(tex&&fnd(f,"vColor",6)&&(fnd(f,"fFading",6)||fnd(f,"u_opacity",3))) { p+=sprintf(p," col=vec4(vColor.rgb,vColor.a*col.a*max(col.r,max(col.g,col.b)));\n"); if(fnd(f,"u_opacity",3)) p+=sprintf(p," col.a*=u_opacity;\n"); if(fnd(f,"fFading",6)) p+=sprintf(p," col.a*=fFading;\n"); p+=sprintf(p," gl_FragColor=col;\n}\n"); return o; }
  { int hascolor=0; for(int i=0;i<f->n;i++){ Sym*s=&f->s[i]; const char*n=s->name; if(!s->flag&&s->type==4&&(s->cls==6||s->cls==3)&&((!strncmp(n,"CO",2)&&!strstr(n,"TOUCH"))||ieq(n,"mixed_co")||ieq(n,"diffColor")||ieq(n,"base_co")||ieq(n,"cm")||ieq(n,"BLUE")||ieq(n,"col")||ieq(n,"c"))) hascolor=1; }
    if(hascolor&&tex&&uv) p+=sprintf(p," col.a=col.a*max(col.r,max(col.g,col.b));\n"); }
  for(int i=0;i<f->n;i++){ Sym*s=&f->s[i]; if(s->flag||s->arr>1) continue; const char*n=s->name;
    if(s->type==5&&(s->cls==6||s->cls==3)&&(ieq(n,"vColor")||ieq(n,"col")||ieq(n,"c")||ieq(n,"v_color")||ieq(n,"u_color")||ieq(n,"color"))) p+=sprintf(p," col*=%s;\n",gname(n));
    if(s->type==4&&(s->cls==6||s->cls==3)&&(((!strncmp(n,"CO",2))&&!strstr(n,"TOUCH")&&strcmp(n,"CO_FES"))||ieq(n,"mixed_co")||ieq(n,"mc")||ieq(n,"diffColor")||ieq(n,"c")||ieq(n,"col")||ieq(n,"v_BaseShade")||ieq(n,"color")||ieq(n,"base_co")||ieq(n,"cm")||ieq(n,"BLUE"))) p+=sprintf(p," col.rgb=%s;\n",gname(n));
    if(s->type==2&&(s->cls==6||s->cls==3)&&(ieq(n,"main_menu")||ieq(n,"v_main_menu")||ieq(n,"opacity")||ieq(n,"u_opacity")||ieq(n,"u_Opacity")||ieq(n,"fade")||ieq(n,"vis")||ieq(n,"pre_alpha")||ieq(n,"am")||ieq(n,"alpha")||ieq(n,"intensity"))) p+=sprintf(p," col.a*=%s;\n",gname(n)); }
  { const char *nm=f->hash?shname(f->hash):""; 
    if(strstr(nm,"navi_startup")&&strstr(nm,"mat_bg")) p+=sprintf(p," col.rgb=vec3(0.13,0.13,0.14);\n");
    if(strstr(nm,"mat_list_gloss")) p+=sprintf(p," col=vec4(1.0,1.0,1.0,0.06);\n");
    if(strstr(nm,"mat_frame_inner")) p+=sprintf(p," col.a*=0.25;\n");
    if(strstr(nm,"/CursorBG/")&&strstr(nm,"mat_shadow")) p+=sprintf(p," col.a*=0.25;\n");
    if(strstr(nm,"/CursorBG/")&&strstr(nm,"mat_bg")) p+=sprintf(p," col.a*=0.45;\n");
    if(strstr(nm,"/cursor/")&&strstr(nm,"mat_list_pressed")) p+=sprintf(p," col.a*=0.0;\n");
    if(strstr(nm,"/cursor/")&&strstr(nm,"mat_highlight")) p+=sprintf(p," col.a*=0.25;\n"); }
  p+=sprintf(p," gl_FragColor=col;\n}\n"); return o; }
static GLuint comp(GLenum t,const char*src,const char*what){ GLuint s=glCreateShader(t); glShaderSource(s,1,&src,NULL); glCompileShader(s); GLint ok=0; glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
  if(!ok){ char lg[2048]; glGetShaderInfoLog(s,2048,NULL,lg); fprintf(stderr,"[host] GEN %s FAILED: %s\n--- src\n%s---\n",what,lg,src); } return s; }
static int ndec[3];
static int alpha_hack=0; /* GL_ALPHA -> white+alpha was only needed by the name-based shaders; real code wants (0,0,0,a) */
/* a varying the fragment stage reads but the vertex stage never wrote (optimised out by the original compiler) must still link */
static char *patch_varyings(char *vs,const char *fs){ char *o=malloc(strlen(vs)+8192),decl[2048]="",init[4096]=""; const char *p=fs;
  while((p=strstr(p,"varying "))){ if(p!=fs&&p[-1]!='\n'){ p+=8; continue; } const char*e=strchr(p,';'); if(!e) break; char ln[200]; int L=e-p; if(L>190) L=190; memcpy(ln,p,L); ln[L]=0; char ty[40],nm[120]; if(sscanf(ln,"varying %39s %119s",ty,nm)==2&&!strchr(nm,'[')){ char key[160]; snprintf(key,160,"varying %s %s;",ty,nm); if(!strstr(vs,key)){ strncat(decl,key,sizeof decl-strlen(decl)-2); strcat(decl,"\n"); char q[200]; snprintf(q,200,"%s=%s(0.0);\n",nm,ty); strncat(init,q,sizeof init-strlen(init)-1); } } p=e; }
  const char*a=strstr(vs,"//VARYINGS"),*b=strstr(vs,"//ENDMAIN"); if(!a||!b||(!decl[0])){ strcpy(o,vs); free(vs); return o; }
  size_t n=0; memcpy(o,vs,a-vs); n=a-vs; strcpy(o+n,decl); n+=strlen(decl); memcpy(o+n,a,b-a); n+=b-a; strcpy(o+n,init); n+=strlen(init); strcpy(o+n,b); free(vs); return o; }
static char *load_glsl(u32 h,const char*ext){ const char*d=getenv("GLHOST_GLSLDIR"); if(!d) d="../usc/glsl"; char p[600]; snprintf(p,600,"%s/%08x.%s",d,h,ext); FILE*f=fopen(p,"r"); if(!f) return 0; fseek(f,0,SEEK_END); long n=ftell(f); fseek(f,0,SEEK_SET); char*o=malloc(n+1); o[fread(o,1,n,f)]=0; fclose(f); return o; }
static int comp_ok(GLenum t,const char*src){ GLuint s=glCreateShader(t); glShaderSource(s,1,&src,NULL); glCompileShader(s); GLint ok=0; glGetShaderiv(s,GL_COMPILE_STATUS,&ok); if(!ok){ char lg[1024]; glGetShaderInfoLog(s,1024,NULL,lg); fprintf(stderr,"[host] decomp compile: %s\n",lg); } glDeleteShader(s); return ok; }
static void do_attach(u32 prog,u32 sh){ if(sh<MAXSH&&shinfo[sh]){ if(prog<MAXSH){ if(shinfo[sh]->kind==0) progbin[prog].vs=sh; else progbin[prog].fs=sh; } return; } glAttachShader(H(4,prog),H(4,sh)); }
static void do_detach(u32 prog,u32 sh){ if(sh<MAXSH&&shinfo[sh]){ if(prog<MAXSH){ if(progbin[prog].vs==sh) progbin[prog].vs=0; if(progbin[prog].fs==sh) progbin[prog].fs=0; } return; } glDetachShader(H(4,prog),H(4,sh)); }
static u32 hostprog_name[65536][2];
static void do_link(u32 prog){ GLuint P=H(4,prog); u32 vs=prog<MAXSH?progbin[prog].vs:0,fs=prog<MAXSH?progbin[prog].fs:0;
  if(!vs&&!fs){ glLinkProgram(P); return; }
  static ShInfo empty; ShInfo *V=vs?shinfo[vs]:&empty,*F=fs?shinfo[fs]:&empty;
  fprintf(stderr,"[host] PROG %u vs=%s fs=%s\n",P,V->hash?shname(V->hash):"-",F->hash?shname(F->hash):"-"); if(P<65536){ hostprog_name[P][0]=V->hash; hostprog_name[P][1]=F->hash; }
  /* decompiled GLSL (usc/decomp.py) wins when present and compiles; the name-based generator stays as the fallback */
  char *a=(V->hash)?load_glsl(V->hash,"vert"):0,*b=(F->hash)?load_glsl(F->hash,"frag"):0;
  if(a&&!comp_ok(GL_VERTEX_SHADER,a)){ fprintf(stderr,"[host] DECOMP VS rejected %08x\n",V->hash); free(a); a=0; }
  if(b&&!comp_ok(GL_FRAGMENT_SHADER,b)){ fprintf(stderr,"[host] DECOMP FS rejected %08x\n",F->hash); free(b); b=0; }
  ndec[0]+=a!=0; ndec[1]+=b!=0; ndec[2]+=2;
  /* a decompiled stage talks through its own varying names, so a half-decompiled pair is only safe if both agree */
  if(a&&b) a=patch_varyings(a,b);
  if(!a) a=gen_vs(V,F); if(!b) b=gen_fs(F);
  if(getenv("GLHOST_DUMPLINK")) fprintf(stderr,"[host] link stats decompiled vs=%d fs=%d of %d\n",ndec[0],ndec[1],ndec[2]);
  GLuint sa=comp(GL_VERTEX_SHADER,a,"VS"),sb=comp(GL_FRAGMENT_SHADER,b,"FS");
  glAttachShader(P,sa); glAttachShader(P,sb); if(fnd(V,"a_Position",4)) glBindAttribLocation(P,0,"a_Position"); glLinkProgram(P);
  GLint ok=0; glGetProgramiv(P,GL_LINK_STATUS,&ok); if(!ok){ char lg[2048]; glGetProgramInfoLog(P,2048,NULL,lg); fprintf(stderr,"[host] GEN LINK FAILED: %s\n%s\n%s\n",lg,a,b); }
  glDetachShader(P,sa); glDetachShader(P,sb); glDeleteShader(sa); glDeleteShader(sb); free(a); free(b); }

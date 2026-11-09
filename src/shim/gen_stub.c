void glBlendColor(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glBlendColor,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glBlendEquationSeparate(u32 a0,u32 a1){ u32*p; LOCK(); p=br_begin(OP_glBlendEquationSeparate,2); p[0]=a0; p[1]=a1; UNLOCK(); }
void glBlendFuncSeparate(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glBlendFuncSeparate,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glClear(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glClear,1); p[0]=a0; UNLOCK(); }
void glClearColor(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glClearColor,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glClearDepthf(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glClearDepthf,1); p[0]=a0; UNLOCK(); }
void glClearStencil(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glClearStencil,1); p[0]=a0; UNLOCK(); }
void glColorMask(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glColorMask,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glCullFace(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glCullFace,1); p[0]=a0; UNLOCK(); }
void glDepthFunc(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glDepthFunc,1); p[0]=a0; UNLOCK(); }
void glDepthMask(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glDepthMask,1); p[0]=a0; UNLOCK(); }
void glDisable(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glDisable,1); p[0]=a0; UNLOCK(); }
void glEnable(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glEnable,1); p[0]=a0; UNLOCK(); }
void glFrontFace(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glFrontFace,1); p[0]=a0; UNLOCK(); }
void glLineWidth(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glLineWidth,1); p[0]=a0; UNLOCK(); }
void glPolygonOffset(u32 a0,u32 a1){ u32*p; LOCK(); p=br_begin(OP_glPolygonOffset,2); p[0]=a0; p[1]=a1; UNLOCK(); }
void glSampleCoverage(u32 a0,u32 a1){ u32*p; LOCK(); p=br_begin(OP_glSampleCoverage,2); p[0]=a0; p[1]=a1; UNLOCK(); }
void glScissor(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glScissor,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glViewport(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glViewport,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glStencilFuncSeparate(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glStencilFuncSeparate,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glStencilMaskSeparate(u32 a0,u32 a1){ u32*p; LOCK(); p=br_begin(OP_glStencilMaskSeparate,2); p[0]=a0; p[1]=a1; UNLOCK(); }
void glStencilOpSeparate(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glStencilOpSeparate,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glVertexAttrib4f(u32 a0,u32 a1,u32 a2,u32 a3,u32 a4){ u32*p; LOCK(); p=br_begin(OP_glVertexAttrib4f,5); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; p[4]=a4; UNLOCK(); }
void glTexParameteri(u32 a0,u32 a1,u32 a2){ u32*p; LOCK(); p=br_begin(OP_glTexParameteri,3); p[0]=a0; p[1]=a1; p[2]=a2; UNLOCK(); }
void glTexParameterf(u32 a0,u32 a1,u32 a2){ u32*p; LOCK(); p=br_begin(OP_glTexParameterf,3); p[0]=a0; p[1]=a1; p[2]=a2; UNLOCK(); }
void glCopyTexSubImage2D(u32 a0,u32 a1,u32 a2,u32 a3,u32 a4,u32 a5,u32 a6,u32 a7){ u32*p; LOCK(); p=br_begin(OP_glCopyTexSubImage2D,8); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; p[4]=a4; p[5]=a5; p[6]=a6; p[7]=a7; UNLOCK(); }
void glGenerateMipmap(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glGenerateMipmap,1); p[0]=a0; UNLOCK(); }
void glAttachShader(u32 a0,u32 a1){ u32*p; LOCK(); p=br_begin(OP_glAttachShader,2); p[0]=a0; p[1]=a1; UNLOCK(); }
void glDetachShader(u32 a0,u32 a1){ u32*p; LOCK(); p=br_begin(OP_glDetachShader,2); p[0]=a0; p[1]=a1; UNLOCK(); }
void glCompileShader(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glCompileShader,1); p[0]=a0; UNLOCK(); }
void glLinkProgram(u32 a0){ u32*p; LOCK(); p=br_begin(OP_glLinkProgram,1); p[0]=a0; UNLOCK(); }
void glFramebufferRenderbuffer(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glFramebufferRenderbuffer,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
void glFramebufferTexture2D(u32 a0,u32 a1,u32 a2,u32 a3,u32 a4){ u32*p; LOCK(); p=br_begin(OP_glFramebufferTexture2D,5); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; p[4]=a4; UNLOCK(); }
void glRenderbufferStorage(u32 a0,u32 a1,u32 a2,u32 a3){ u32*p; LOCK(); p=br_begin(OP_glRenderbufferStorage,4); p[0]=a0; p[1]=a1; p[2]=a2; p[3]=a3; UNLOCK(); }
typedef struct{const char*n;void*p;}fent;
const fent gl_funcs[]={
 {"glActiveTexture",(void*)glActiveTexture},
 {"glBlendColor",(void*)glBlendColor},
 {"glBlendEquationSeparate",(void*)glBlendEquationSeparate},
 {"glBlendFuncSeparate",(void*)glBlendFuncSeparate},
 {"glClear",(void*)glClear},
 {"glClearColor",(void*)glClearColor},
 {"glClearDepthf",(void*)glClearDepthf},
 {"glClearStencil",(void*)glClearStencil},
 {"glColorMask",(void*)glColorMask},
 {"glCullFace",(void*)glCullFace},
 {"glDepthFunc",(void*)glDepthFunc},
 {"glDepthMask",(void*)glDepthMask},
 {"glDisable",(void*)glDisable},
 {"glEnable",(void*)glEnable},
 {"glFrontFace",(void*)glFrontFace},
 {"glLineWidth",(void*)glLineWidth},
 {"glPolygonOffset",(void*)glPolygonOffset},
 {"glSampleCoverage",(void*)glSampleCoverage},
 {"glScissor",(void*)glScissor},
 {"glViewport",(void*)glViewport},
 {"glStencilFuncSeparate",(void*)glStencilFuncSeparate},
 {"glStencilMaskSeparate",(void*)glStencilMaskSeparate},
 {"glStencilOpSeparate",(void*)glStencilOpSeparate},
 {"glVertexAttrib4f",(void*)glVertexAttrib4f},
 {"glTexParameteri",(void*)glTexParameteri},
 {"glTexParameterf",(void*)glTexParameterf},
 {"glCopyTexSubImage2D",(void*)glCopyTexSubImage2D},
 {"glGenerateMipmap",(void*)glGenerateMipmap},
 {"glBindBuffer",(void*)glBindBuffer},
 {"glBindFramebuffer",(void*)glBindFramebuffer},
 {"glBindRenderbuffer",(void*)glBindRenderbuffer},
 {"glBindTexture",(void*)glBindTexture},
 {"glUseProgram",(void*)glUseProgram},
 {"glAttachShader",(void*)glAttachShader},
 {"glDetachShader",(void*)glDetachShader},
 {"glCompileShader",(void*)glCompileShader},
 {"glLinkProgram",(void*)glLinkProgram},
 {"glFramebufferRenderbuffer",(void*)glFramebufferRenderbuffer},
 {"glFramebufferTexture2D",(void*)glFramebufferTexture2D},
 {"glRenderbufferStorage",(void*)glRenderbufferStorage},
 {"glPixelStorei",(void*)glPixelStorei},
 {"glEnableVertexAttribArray",(void*)glEnableVertexAttribArray},
 {"glDisableVertexAttribArray",(void*)glDisableVertexAttribArray},
#include "gl_hand_names.inc"
 {0,0}};

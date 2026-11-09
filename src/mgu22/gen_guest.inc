void glActiveTexture(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_ActiveTexture, 1, v); pub(c); }
void glAttachShader(unsigned a0, unsigned a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1 }; msg(c, OP_AttachShader, 2, v); pub(c); }
void glBindBuffer(unsigned a0, unsigned a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1 }; msg(c, OP_BindBuffer, 2, v); pub(c); }
void glBindFramebuffer(unsigned a0, unsigned a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1 }; msg(c, OP_BindFramebuffer, 2, v); pub(c); }
void glBindRenderbuffer(unsigned a0, unsigned a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1 }; msg(c, OP_BindRenderbuffer, 2, v); pub(c); }
void glBindSampler(unsigned a0, unsigned a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1 }; msg(c, OP_BindSampler, 2, v); pub(c); }
void glBindTexture(unsigned a0, unsigned a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1 }; msg(c, OP_BindTexture, 2, v); pub(c); }
void glBindVertexArray(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_BindVertexArray, 1, v); pub(c); }
void glBlendColor(float a0, float a1, float a2, float a3) { Ch *c = cur(); unsigned long v[] = { fbits(a0), fbits(a1), fbits(a2), fbits(a3) }; msg(c, OP_BlendColor, 4, v); pub(c); }
void glBlendEquationSeparate(unsigned a0, unsigned a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1 }; msg(c, OP_BlendEquationSeparate, 2, v); pub(c); }
void glBlendFuncSeparate(unsigned a0, unsigned a1, unsigned a2, unsigned a3) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3 }; msg(c, OP_BlendFuncSeparate, 4, v); pub(c); }
void glBlitFramebuffer(int a0, int a1, int a2, int a3, int a4, int a5, int a6, int a7, unsigned a8, unsigned a9) { Ch *c = cur(); unsigned long v[] = { (unsigned long)(long)a0, (unsigned long)(long)a1, (unsigned long)(long)a2, (unsigned long)(long)a3, (unsigned long)(long)a4, (unsigned long)(long)a5, (unsigned long)(long)a6, (unsigned long)(long)a7, (unsigned long)a8, (unsigned long)a9 }; msg(c, OP_BlitFramebuffer, 10, v); pub(c); }
void glClear(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_Clear, 1, v); pub(c); }
void glClearColor(float a0, float a1, float a2, float a3) { Ch *c = cur(); unsigned long v[] = { fbits(a0), fbits(a1), fbits(a2), fbits(a3) }; msg(c, OP_ClearColor, 4, v); pub(c); }
void glClearDepthf(float a0) { Ch *c = cur(); unsigned long v[] = { fbits(a0) }; msg(c, OP_ClearDepthf, 1, v); pub(c); }
void glClearStencil(int a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)(long)a0 }; msg(c, OP_ClearStencil, 1, v); pub(c); }
void glColorMask(unsigned char a0, unsigned char a1, unsigned char a2, unsigned char a3) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3 }; msg(c, OP_ColorMask, 4, v); pub(c); }
void glCompileShader(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_CompileShader, 1, v); pub(c); }
void glCullFace(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_CullFace, 1, v); pub(c); }
void glDeleteProgram(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_DeleteProgram, 1, v); pub(c); }
void glDeleteShader(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_DeleteShader, 1, v); pub(c); }
void glDepthFunc(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_DepthFunc, 1, v); pub(c); }
void glDepthMask(unsigned char a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_DepthMask, 1, v); pub(c); }
void glDisable(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_Disable, 1, v); pub(c); }
void glDrawArrays(unsigned a0, int a1, int a2) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)(long)a2 }; msg(c, OP_DrawArrays, 3, v); pub(c); }
void glDrawArraysInstanced(unsigned a0, int a1, int a2, int a3) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)(long)a2, (unsigned long)(long)a3 }; msg(c, OP_DrawArraysInstanced, 4, v); pub(c); }
void glDrawElements(unsigned a0, int a1, unsigned a2, const void * a3) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)a2, (unsigned long)a3 }; msg(c, OP_DrawElements, 4, v); pub(c); }
void glDrawElementsInstanced(unsigned a0, int a1, unsigned a2, const void * a3, int a4) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)(long)a4 }; msg(c, OP_DrawElementsInstanced, 5, v); pub(c); }
void glEnable(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_Enable, 1, v); pub(c); }
void glEnableVertexAttribArray(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_EnableVertexAttribArray, 1, v); pub(c); }
void glFlush(void) { Ch *c = cur(); unsigned long v[] = { 0 }; msg(c, OP_Flush, 0, v); pub(c); }
void glFramebufferRenderbuffer(unsigned a0, unsigned a1, unsigned a2, unsigned a3) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3 }; msg(c, OP_FramebufferRenderbuffer, 4, v); pub(c); }
void glFramebufferTexture2D(unsigned a0, unsigned a1, unsigned a2, unsigned a3, int a4) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)(long)a4 }; msg(c, OP_FramebufferTexture2D, 5, v); pub(c); }
void glGenerateMipmap(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_GenerateMipmap, 1, v); pub(c); }
void glLinkProgram(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_LinkProgram, 1, v); pub(c); }
void glRenderbufferStorageMultisample(unsigned a0, int a1, unsigned a2, int a3, int a4) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)a2, (unsigned long)(long)a3, (unsigned long)(long)a4 }; msg(c, OP_RenderbufferStorageMultisample, 5, v); pub(c); }
void glSamplerParameteri(unsigned a0, unsigned a1, int a2) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1, (unsigned long)(long)a2 }; msg(c, OP_SamplerParameteri, 3, v); pub(c); }
void glScissor(int a0, int a1, int a2, int a3) { Ch *c = cur(); unsigned long v[] = { (unsigned long)(long)a0, (unsigned long)(long)a1, (unsigned long)(long)a2, (unsigned long)(long)a3 }; msg(c, OP_Scissor, 4, v); pub(c); }
void glStencilFunc(unsigned a0, int a1, unsigned a2) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)a2 }; msg(c, OP_StencilFunc, 3, v); pub(c); }
void glStencilOp(unsigned a0, unsigned a1, unsigned a2) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1, (unsigned long)a2 }; msg(c, OP_StencilOp, 3, v); pub(c); }
void glTexParameteri(unsigned a0, unsigned a1, int a2) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1, (unsigned long)(long)a2 }; msg(c, OP_TexParameteri, 3, v); pub(c); }
void glTexStorage2D(unsigned a0, int a1, unsigned a2, int a3, int a4) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)a2, (unsigned long)(long)a3, (unsigned long)(long)a4 }; msg(c, OP_TexStorage2D, 5, v); pub(c); }
void glTexStorage2DMultisample(unsigned a0, int a1, unsigned a2, int a3, int a4, unsigned char a5) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)a2, (unsigned long)(long)a3, (unsigned long)(long)a4, (unsigned long)a5 }; msg(c, OP_TexStorage2DMultisample, 6, v); pub(c); }
void glTexStorage3D(unsigned a0, int a1, unsigned a2, int a3, int a4, int a5) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)a2, (unsigned long)(long)a3, (unsigned long)(long)a4, (unsigned long)(long)a5 }; msg(c, OP_TexStorage3D, 6, v); pub(c); }
void glUniform1i(int a0, int a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)(long)a0, (unsigned long)(long)a1 }; msg(c, OP_Uniform1i, 2, v); pub(c); }
void glUseProgram(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_UseProgram, 1, v); pub(c); }
void glVertexAttribDivisor(unsigned a0, unsigned a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)a1 }; msg(c, OP_VertexAttribDivisor, 2, v); pub(c); }
void glVertexAttribPointer(unsigned a0, int a1, unsigned a2, unsigned char a3, int a4, const void * a5) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, (unsigned long)(long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)(long)a4, (unsigned long)a5 }; msg(c, OP_VertexAttribPointer, 6, v); pub(c); }
void glViewport(int a0, int a1, int a2, int a3) { Ch *c = cur(); unsigned long v[] = { (unsigned long)(long)a0, (unsigned long)(long)a1, (unsigned long)(long)a2, (unsigned long)(long)a3 }; msg(c, OP_Viewport, 4, v); pub(c); }
unsigned glCheckFramebufferStatus(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_CheckFramebufferStatus, 1, v); pub(c); unsigned long r; get(c, &r, 8); return (unsigned)r; }
unsigned glCreateProgram(void) { Ch *c = cur(); unsigned long v[] = { 0 }; msg(c, OP_CreateProgram, 0, v); pub(c); unsigned long r; get(c, &r, 8); return (unsigned)r; }
unsigned glCreateShader(unsigned a0) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0 }; msg(c, OP_CreateShader, 1, v); pub(c); unsigned long r; get(c, &r, 8); return (unsigned)r; }
unsigned glGetError(void) { Ch *c = cur(); unsigned long v[] = { 0 }; msg(c, OP_GetError, 0, v); pub(c); unsigned long r; get(c, &r, 8); return (unsigned)r; }
int glGetAttribLocation(unsigned a0, const char * a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, strlen(a1) + 1 }; msg(c, OP_GetAttribLocation, 2, v); put(c, a1, strlen(a1) + 1); pub(c); unsigned long r; get(c, &r, 8); return (int)r; }
int glGetUniformLocation(unsigned a0, const char * a1) { Ch *c = cur(); unsigned long v[] = { (unsigned long)a0, strlen(a1) + 1 }; msg(c, OP_GetUniformLocation, 2, v); put(c, a1, strlen(a1) + 1); pub(c); unsigned long r; get(c, &r, 8); return (int)r; }

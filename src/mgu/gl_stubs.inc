void glActiveTexture(unsigned int a0) { simple(F_ActiveTexture, 1, (unsigned long)a0); }
void glAttachShader(unsigned int a0, unsigned int a1) { simple(F_AttachShader, 2, (unsigned long)a0, (unsigned long)a1); }
void glBindBuffer(unsigned int a0, unsigned int a1) { simple(F_BindBuffer, 2, (unsigned long)a0, (unsigned long)a1); }
void glBindFramebuffer(unsigned int a0, unsigned int a1) { simple(F_BindFramebuffer, 2, (unsigned long)a0, (unsigned long)a1); }
void glBindRenderbuffer(unsigned int a0, unsigned int a1) { simple(F_BindRenderbuffer, 2, (unsigned long)a0, (unsigned long)a1); }
void glBindSampler(unsigned int a0, unsigned int a1) { simple(F_BindSampler, 2, (unsigned long)a0, (unsigned long)a1); }
void glBindTexture(unsigned int a0, unsigned int a1) { simple(F_BindTexture, 2, (unsigned long)a0, (unsigned long)a1); }
void glBlendEquationSeparate(unsigned int a0, unsigned int a1) { simple(F_BlendEquationSeparate, 2, (unsigned long)a0, (unsigned long)a1); }
void glBlendFuncSeparate(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_BlendFuncSeparate, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glBlitFramebuffer(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3, unsigned int a4, unsigned int a5, unsigned int a6, unsigned int a7, unsigned int a8, unsigned int a9) { simple(F_BlitFramebuffer, 10, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4, (unsigned long)a5, (unsigned long)a6, (unsigned long)a7, (unsigned long)a8, (unsigned long)a9); }
void glClear(unsigned int a0) { simple(F_Clear, 1, (unsigned long)a0); }
void glClearColor(float a0, float a1, float a2, float a3) { simple(F_ClearColor, 4, A_F(a0), A_F(a1), A_F(a2), A_F(a3)); }
void glClearDepthf(float a0) { simple(F_ClearDepthf, 1, A_F(a0)); }
void glClearStencil(unsigned int a0) { simple(F_ClearStencil, 1, (unsigned long)a0); }
void glColorMask(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_ColorMask, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glCompileShader(unsigned int a0) { simple(F_CompileShader, 1, (unsigned long)a0); }
void glCullFace(unsigned int a0) { simple(F_CullFace, 1, (unsigned long)a0); }
void glDepthFunc(unsigned int a0) { simple(F_DepthFunc, 1, (unsigned long)a0); }
void glDepthMask(unsigned int a0) { simple(F_DepthMask, 1, (unsigned long)a0); }
void glDisable(unsigned int a0) { simple(F_Disable, 1, (unsigned long)a0); }
void glDrawArrays(unsigned int a0, unsigned int a1, unsigned int a2) { simple(F_DrawArrays, 3, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2); }
void glDrawArraysInstanced(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_DrawArraysInstanced, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glDrawElements(unsigned int a0, unsigned int a1, unsigned int a2, long a3) { simple(F_DrawElements, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glDrawElementsInstanced(unsigned int a0, unsigned int a1, unsigned int a2, long a3, unsigned int a4) { simple(F_DrawElementsInstanced, 5, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4); }
void glEnable(unsigned int a0) { simple(F_Enable, 1, (unsigned long)a0); }
void glEnableVertexAttribArray(unsigned int a0) { simple(F_EnableVertexAttribArray, 1, (unsigned long)a0); }
void glFramebufferRenderbuffer(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_FramebufferRenderbuffer, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glFramebufferTexture2D(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3, unsigned int a4) { simple(F_FramebufferTexture2D, 5, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4); }
void glGenerateMipmap(unsigned int a0) { simple(F_GenerateMipmap, 1, (unsigned long)a0); }
void glLinkProgram(unsigned int a0) { simple(F_LinkProgram, 1, (unsigned long)a0); }
void glPixelStorei(unsigned int a0, unsigned int a1) { simple(F_PixelStorei, 2, (unsigned long)a0, (unsigned long)a1); }
void glRenderbufferStorageMultisample(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3, unsigned int a4) { simple(F_RenderbufferStorageMultisample, 5, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4); }
void glScissor(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_Scissor, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glStencilFunc(unsigned int a0, unsigned int a1, unsigned int a2) { simple(F_StencilFunc, 3, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2); }
void glStencilOp(unsigned int a0, unsigned int a1, unsigned int a2) { simple(F_StencilOp, 3, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2); }
void glTexParameteri(unsigned int a0, unsigned int a1, unsigned int a2) { simple(F_TexParameteri, 3, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2); }
void glTexStorage2D(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3, unsigned int a4) { simple(F_TexStorage2D, 5, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4); }
void glTexStorage3D(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3, unsigned int a4, unsigned int a5) { simple(F_TexStorage3D, 6, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4, (unsigned long)a5); }
void glUniform1i(unsigned int a0, unsigned int a1) { simple(F_Uniform1i, 2, (unsigned long)a0, (unsigned long)a1); }
void glUseProgram(unsigned int a0) { simple(F_UseProgram, 1, (unsigned long)a0); }
void glVertexAttribDivisor(unsigned int a0, unsigned int a1) { simple(F_VertexAttribDivisor, 2, (unsigned long)a0, (unsigned long)a1); }
void glVertexAttribPointer(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3, unsigned int a4, long a5) { simple(F_VertexAttribPointer, 6, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4, (unsigned long)a5); }
void glViewport(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_Viewport, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glDisableVertexAttribArray(unsigned int a0) { simple(F_DisableVertexAttribArray, 1, (unsigned long)a0); }
void glStencilMask(unsigned int a0) { simple(F_StencilMask, 1, (unsigned long)a0); }
void glStencilFuncSeparate(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_StencilFuncSeparate, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glStencilOpSeparate(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_StencilOpSeparate, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glBlendColor(float a0, float a1, float a2, float a3) { simple(F_BlendColor, 4, A_F(a0), A_F(a1), A_F(a2), A_F(a3)); }
void glHint(unsigned int a0, unsigned int a1) { simple(F_Hint, 2, (unsigned long)a0, (unsigned long)a1); }
void glLineWidth(float a0) { simple(F_LineWidth, 1, A_F(a0)); }
void glPolygonOffset(float a0, float a1) { simple(F_PolygonOffset, 2, A_F(a0), A_F(a1)); }
void glFrontFace(unsigned int a0) { simple(F_FrontFace, 1, (unsigned long)a0); }
void glBlendEquation(unsigned int a0) { simple(F_BlendEquation, 1, (unsigned long)a0); }
void glBlendFunc(unsigned int a0, unsigned int a1) { simple(F_BlendFunc, 2, (unsigned long)a0, (unsigned long)a1); }
void glTexParameterf(unsigned int a0, unsigned int a1, float a2) { simple(F_TexParameterf, 3, (unsigned long)a0, (unsigned long)a1, A_F(a2)); }
void glSamplerParameteri(unsigned int a0, unsigned int a1, unsigned int a2) { simple(F_SamplerParameteri, 3, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2); }
void glUniform1f(unsigned int a0, float a1) { simple(F_Uniform1f, 2, (unsigned long)a0, A_F(a1)); }
void glUniform2f(unsigned int a0, float a1, float a2) { simple(F_Uniform2f, 3, (unsigned long)a0, A_F(a1), A_F(a2)); }
void glUniform3f(unsigned int a0, float a1, float a2, float a3) { simple(F_Uniform3f, 4, (unsigned long)a0, A_F(a1), A_F(a2), A_F(a3)); }
void glUniform4f(unsigned int a0, float a1, float a2, float a3, float a4) { simple(F_Uniform4f, 5, (unsigned long)a0, A_F(a1), A_F(a2), A_F(a3), A_F(a4)); }
void glUniform2i(unsigned int a0, unsigned int a1, unsigned int a2) { simple(F_Uniform2i, 3, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2); }
void glUniform3i(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3) { simple(F_Uniform3i, 4, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3); }
void glUniform4i(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3, unsigned int a4) { simple(F_Uniform4i, 5, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4); }
void glDepthRangef(float a0, float a1) { simple(F_DepthRangef, 2, A_F(a0), A_F(a1)); }
void glSampleCoverage(float a0, unsigned int a1) { simple(F_SampleCoverage, 2, A_F(a0), (unsigned long)a1); }
void glVertexAttrib4f(unsigned int a0, float a1, float a2, float a3, float a4) { simple(F_VertexAttrib4f, 5, (unsigned long)a0, A_F(a1), A_F(a2), A_F(a3), A_F(a4)); }
void glBindVertexArray(unsigned int a0) { simple(F_BindVertexArray, 1, (unsigned long)a0); }
void glFramebufferTextureLayer(unsigned int a0, unsigned int a1, unsigned int a2, unsigned int a3, unsigned int a4) { simple(F_FramebufferTextureLayer, 5, (unsigned long)a0, (unsigned long)a1, (unsigned long)a2, (unsigned long)a3, (unsigned long)a4); }
void glReadBuffer(unsigned int a0) { simple(F_ReadBuffer, 1, (unsigned long)a0); }

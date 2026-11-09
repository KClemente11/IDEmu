#!/usr/bin/env python3
"""Gera gl_stubs.inc (guest) e gl_ids.h (host) a partir da lista de funções GLES só com argumentos escalares."""
SPEC = """ActiveTexture:i AttachShader:ii BindBuffer:ii BindFramebuffer:ii BindRenderbuffer:ii BindSampler:ii BindTexture:ii
BlendEquationSeparate:ii BlendFuncSeparate:iiii BlitFramebuffer:iiiiiiiiii Clear:i ClearColor:ffff ClearDepthf:f ClearStencil:i
ColorMask:iiii CompileShader:i CullFace:i DepthFunc:i DepthMask:i Disable:i DrawArrays:iii DrawArraysInstanced:iiii
DrawElements:iiil DrawElementsInstanced:iiili Enable:i EnableVertexAttribArray:i FramebufferRenderbuffer:iiii FramebufferTexture2D:iiiii
GenerateMipmap:i LinkProgram:i PixelStorei:ii RenderbufferStorageMultisample:iiiii Scissor:iiii StencilFunc:iii StencilOp:iii
TexParameteri:iii TexStorage2D:iiiii TexStorage3D:iiiiii Uniform1i:ii UseProgram:i VertexAttribDivisor:ii VertexAttribPointer:iiiiil Viewport:iiii
DisableVertexAttribArray:i StencilMask:i StencilFuncSeparate:iiii StencilOpSeparate:iiii BlendColor:ffff Hint:ii LineWidth:f PolygonOffset:ff
FrontFace:i BlendEquation:i BlendFunc:ii TexParameterf:iif SamplerParameteri:iii Uniform1f:if Uniform2f:iff Uniform3f:ifff Uniform4f:iffff
Uniform2i:iii Uniform3i:iiii Uniform4i:iiiii DepthRangef:ff SampleCoverage:fi VertexAttrib4f:iffff BindVertexArray:i
FramebufferTextureLayer:iiiii ReadBuffer:i"""
fns = [(s.split(':')[0], s.split(':')[1]) for s in SPEC.split()]
T = {'i': 'unsigned int', 'f': 'float', 'l': 'long'}
with open('gl_stubs.inc', 'w') as g, open('gl_ids.h', 'w') as h:
    h.write('// gerado por gen_gl.py\nenum {\n' + ''.join(' F_%s,\n' % n for n, _ in fns) + ' F__COUNT\n};\nstatic const char *F_TYPES[] = {\n' + ''.join('  "%s",\n' % t for _, t in fns) + '};\n')
    for i, (n, t) in enumerate(fns):
        params = ', '.join('%s a%d' % (T[c], k) for k, c in enumerate(t)) or 'void'
        args = ''.join(', ' + ('A_F(a%d)' % k if c == 'f' else '(unsigned long)a%d' % k) for k, c in enumerate(t))
        g.write('void gl%s(%s) { simple(F_%s, %d%s); }\n' % (n, params, n, len(t), args))
print(len(fns), 'funções escalares')

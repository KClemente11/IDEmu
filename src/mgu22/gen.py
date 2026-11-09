#!/usr/bin/env python3
"""Gera gen_ops.h, gen_guest.inc e gen_host.inc: chamadas GLES com argumentos escalares e operações à mão."""
SPEC = """
v ActiveTexture u
v AttachShader uu
v BindBuffer uu
v BindFramebuffer uu
v BindRenderbuffer uu
v BindSampler uu
v BindTexture uu
v BindVertexArray u
v BlendColor ffff
v BlendEquationSeparate uu
v BlendFuncSeparate uuuu
v BlitFramebuffer iiiiiiiiuu
v Clear u
v ClearColor ffff
v ClearDepthf f
v ClearStencil i
v ColorMask bbbb
v CompileShader u
v CullFace u
v DeleteProgram u
v DeleteShader u
v DepthFunc u
v DepthMask b
v Disable u
v DrawArrays uii
v DrawArraysInstanced uiii
v DrawElements uiup
v DrawElementsInstanced uiupi
v Enable u
v EnableVertexAttribArray u
v Flush
v FramebufferRenderbuffer uuuu
v FramebufferTexture2D uuuui
v GenerateMipmap u
v LinkProgram u
v RenderbufferStorageMultisample uiuii
v SamplerParameteri uui
v Scissor iiii
v StencilFunc uiu
v StencilOp uuu
v TexParameteri uui
v TexStorage2D uiuii
v TexStorage2DMultisample uiuiib
v TexStorage3D uiuiii
v Uniform1i ii
v UseProgram u
v VertexAttribDivisor uu
v VertexAttribPointer uiubip
v Viewport iiii
u CheckFramebufferStatus u
u CreateProgram
u CreateShader u
u GetError
i GetAttribLocation us
i GetUniformLocation us
"""
HAND = """BufferData CompressedTexSubImage2D CompressedTexSubImage3D TexImage2D TexSubImage2D TexSubImage3D
DeleteBuffers DeleteFramebuffers DeleteRenderbuffers DeleteSamplers DeleteTextures DeleteVertexArrays
GenBuffers GenFramebuffers GenRenderbuffers GenSamplers GenTextures GenVertexArrays
DrawBuffers GetIntegerv GetInternalformativ GetProgramBinary GetProgramInfoLog GetProgramiv GetShaderInfoLog GetShaderiv
GetString GetStringi InvalidateFramebuffer PixelStorei ProgramBinary ReadPixels ShaderSource
Uniform1fv Uniform2fv Uniform3fv Uniform4fv Uniform1iv Uniform2iv Uniform3iv Uniform4iv
UniformMatrix2fv UniformMatrix3fv UniformMatrix4fv""".split()
EGL = "ChooseConfig GetConfigAttrib CreateContext CreateSurface DestroyContext DestroySurface MakeCurrent Swap Hello".split()
CT = {'u': 'unsigned', 'i': 'int', 'f': 'float', 'b': 'unsigned char', 'p': 'const void *', 's': 'const char *'}
ops, g, h, decl, load = [], [], [], [], []
for line in SPEC.strip().splitlines():
    p = line.split(); ret, name, sig = p[0], p[1], p[2] if len(p) > 2 else ''
    ops.append(name)
    args = ', '.join(f'{CT[c]} a{i}' for i, c in enumerate(sig)) or 'void'
    rt = {'v': 'void', 'u': 'unsigned', 'i': 'int'}[ret]
    enc = []
    strs = [i for i, c in enumerate(sig) if c == 's']
    for i, c in enumerate(sig):
        if c == 'f': enc.append(f'fbits(a{i})')
        elif c == 'p': enc.append(f'(unsigned long)a{i}')
        elif c == 's': enc.append(f'strlen(a{i}) + 1')
        elif c == 'i': enc.append(f'(unsigned long)(long)a{i}')
        else: enc.append(f'(unsigned long)a{i}')
    body = f'Ch *c = cur(); unsigned long v[] = {{ {", ".join(enc) or "0"} }}; msg(c, OP_{name}, {len(sig)}, v);'
    for i in strs: body += f' put(c, a{i}, strlen(a{i}) + 1);'
    body += ' pub(c);'
    if ret != 'v': body += f' unsigned long r; get(c, &r, 8); return ({rt})r;'
    g.append(f'{rt} gl{name}({args}) {{ {body} }}')
    # host
    pt = ', '.join(CT[c] for c in sig) or 'void'
    decl.append(f'static {rt} (*p_{name})({pt});')
    load.append(f'p_{name} = gp("gl{name}");')
    pre, call = '', []
    for i, c in enumerate(sig):
        if c == 'f': call.append(f'bitsf(a[{i}])')
        elif c == 'p': call.append(f'(const void *)a[{i}]')
        elif c == 's':
            pre += f'char *s{i} = scratch(c, a[{i}]); rd(c, s{i}, a[{i}]); '
            call.append(f's{i}')
        elif c == 'i': call.append(f'(int)a[{i}]')
        elif c == 'b': call.append(f'(unsigned char)a[{i}]')
        else: call.append(f'(unsigned)a[{i}]')
    c0 = f'p_{name}({", ".join(call)})'
    if ret == 'v': h.append(f'case OP_{name}: {pre}{c0}; break;')
    else: h.append(f'case OP_{name}: {{ {pre}unsigned long r = (unsigned long)(long){c0}; wr(c, &r, 8); }} break;')
all_ops = ops + HAND + ['EGL' + e for e in EGL]
with open('gen_ops.h', 'w') as f:
    f.write('enum {\n' + ''.join(f'  OP_{n} = {i + 1},\n' for i, n in enumerate(all_ops)) + '};\n')
open('gen_guest.inc', 'w').write('\n'.join(g) + '\n')
with open('gen_host.inc', 'w') as f:
    f.write('#ifdef GEN_DECL\n' + '\n'.join(decl) + '\nstatic void gen_load(void) {\n' + '\n'.join(load) + '\n}\n#endif\n')
    f.write('#ifdef GEN_CASE\n' + '\n'.join(h) + '\n#endif\n')
names = ['gl' + n for n in ops + HAND]
open('gen_names.inc', 'w').write(''.join(f'X({n})\n' for n in names))

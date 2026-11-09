// Protocolo guest -> host da ponte EGL/GLES3 do iDrive 7: [u32 op][u32 len][payload]. Respostas síncronas: [u32 len][payload].
enum {
  OP_NOP, OP_INIT_SURFACE, OP_SWAP, OP_GEN, OP_DELETE, OP_CREATE_SHADER, OP_CREATE_PROGRAM, OP_DELETE_SHADER, OP_DELETE_PROGRAM,
  OP_SIMPLE,            // [fn:u32][nargs:u32][args as u64 or f32 bits]
  OP_SHADER_SOURCE, OP_BUFFER_DATA, OP_TEX_IMAGE, OP_TEX_SUBIMAGE, OP_COMPRESSED_SUBIMAGE, OP_UNIFORMV, OP_DRAW_BUFFERS,
  OP_GET_INTEGERV, OP_GET_SHADERIV, OP_GET_PROGRAMIV, OP_GET_SHADER_LOG, OP_GET_PROGRAM_LOG, OP_GET_ATTRIB_LOC, OP_GET_UNIFORM_LOC,
  OP_CHECK_FB, OP_READ_PIXELS, OP_FINISH, OP_BUFFER_SUBDATA
};

// ---- anel em memória compartilhada (dispositivo PCI idemu-shm 1b36:1d3a, BAR0 de SHM_SIZE bytes; no guest: /sys/bus/pci/devices/.../resource0) ----
// A mesma sequência de bytes que ia pela serial vai por dois anéis: guest->host (comandos) e host->guest (respostas).
// Só o dono de cada índice o escreve: guest = g_tail e h_head; host = g_head e h_tail.
#define SHM_SIZE   (128u << 20)
#define SHM_MAGIC  0x49444d47u
#define G_SIZE     (64u << 20)            // anel de comandos (potência de 2)
#define H_SIZE     (4u << 20)             // anel de respostas
#define G_OFF      4096u
#define H_OFF      (4096u + G_SIZE)
struct shm_hdr {
  volatile unsigned int magic, epoch;                       // epoch muda quando o guest reinicia o fluxo (g_start = onde o fluxo novo começa)
  volatile unsigned long long g_start; volatile unsigned int host_idle; unsigned char pad0[36];   // host_idle = 1: o host espera uma mensagem nova (fronteira de mensagem; ponto seguro para tirar o snapshot)
  volatile unsigned long long g_tail; unsigned char pad1[56];   // guest escreve
  volatile unsigned long long g_head; unsigned char pad2[56];   // host escreve
  volatile unsigned long long h_tail; unsigned char pad3[56];   // host escreve
  volatile unsigned long long h_head; unsigned char pad4[56];   // guest escreve
};

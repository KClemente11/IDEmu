/*
 * IDEmu: BMW CIC High (iDrive 4, Harman "BMW L6") — placa mínima para o QNX 6.3 / SH7785.
 *
 * Base: hw/sh4/sh7750.c (registros da CPU, TLB mapeado) + periféricos on-chip do SH7785.
 * O hardware da placa que o QEMU não tem (FPGA, Carmine, V850...) vai sendo adicionado
 * conforme o firmware original o toca.
 */
#include "qemu/osdep.h"
#include "qemu/log.h"
#include "qemu/units.h"
#include "qapi/error.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "hw/sh4/sh.h"
#include "hw/core/boards.h"
#include "hw/core/loader.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/qdev-properties-system.h"
#include "hw/core/cpu.h"
#include "hw/misc/unimp.h"
#include "system/system.h"
#include "system/reset.h"
#include "target/sh4/cpu.h"
#include "exec/cputlb.h"
#include "hw/sh4/sh_intc.h"
#include "hw/timer/tmu012.h"
#include "hw/block/flash.h"
#include "system/blockdev.h"
#include "hw/core/qdev-properties.h"
#include "qemu/error-report.h"
#include "qemu/main-loop.h"
#include "qemu/thread.h"
#include <sys/socket.h>
#include <sys/un.h>
#include "cic.h"

#define RAM_BASE   0x08000000

#define MM_REGION_MASK   0x07000000
#define MM_ICACHE_ADDR   (0)
#define MM_ICACHE_DATA   (1)
#define MM_ITLB_ADDR     (2)
#define MM_ITLB_DATA     (3)
#define MM_OCACHE_ADDR   (4)
#define MM_OCACHE_DATA   (5)
#define MM_UTLB_ADDR     (6)
#define MM_UTLB_DATA     (7)
#define MM_REGION_TYPE(addr)  ((addr & MM_REGION_MASK) >> 24)

MemoryRegion *cic_oc;

void cic_map_dual(MemoryRegion *mr, hwaddr p4)
{
    MemoryRegion *a7 = g_new(MemoryRegion, 1);
    memory_region_add_subregion(cic_oc, p4, mr);
    memory_region_init_alias(a7, NULL, "a7", mr, 0, memory_region_size(mr));
    memory_region_add_subregion(cic_oc, p4 & 0x1fffffff, a7);
}

typedef struct CicState {
    SuperHCPU *cpu;
    MemoryRegion ccn, ccn_a7, mmct;
    uint32_t ccr, pascr, irmcr, qacr[2];
    uint8_t basr[2];
} CicState;

static CicState cic;

/* ------------------------------------------------------------------ CCN (0xFF000000) */
static uint64_t ccn_read(void *opaque, hwaddr a, unsigned size)
{
    CPUSH4State *env = &cic.cpu->env;
    SuperHCPUClass *scc = SUPERH_CPU_GET_CLASS(cic.cpu);
    switch (a) {
    case 0x00: return env->pteh;
    case 0x04: return env->ptel;
    case 0x08: return env->ttb;
    case 0x0c: return env->tea;
    case 0x10: return env->mmucr;
    case 0x14: return cic.basr[0];
    case 0x18: return cic.basr[1];
    case 0x1c: return cic.ccr;
    case 0x20: return env->tra;
    case 0x24: return env->expevt;
    case 0x28: return env->intevt;
    case 0x30: return scc->pvr;
    case 0x34: return env->ptea;
    case 0x38: return cic.qacr[0];
    case 0x3c: return cic.qacr[1];
    case 0x40: return scc->cvr;
    case 0x44: return scc->prr;
    case 0x70: return cic.pascr;
    case 0x78: return cic.irmcr;
    default:
        qemu_log_mask(LOG_UNIMP, "ccn: read  %02x (%u)\n", (unsigned)a, size);
        return 0;
    }
}

static void ccn_write(void *opaque, hwaddr a, uint64_t v, unsigned size)
{
    CPUSH4State *env = &cic.cpu->env;
    switch (a) {
    case 0x00:
        if ((env->pteh & 0xff) != (v & 0xff)) {
            tlb_flush(CPU(cic.cpu));
        }
        env->pteh = v; return;
    case 0x04: env->ptel = v; return;
    case 0x08: env->ttb = v; return;
    case 0x0c: env->tea = v; return;
    case 0x10:
        if (v & MMUCR_TI) {
            cpu_sh4_invalidate_tlb(env);
        }
        env->mmucr = v & ~MMUCR_TI; return;
    case 0x14: cic.basr[0] = v; return;
    case 0x18: cic.basr[1] = v; return;
    case 0x1c: cic.ccr = v; return;
    case 0x20: env->tra = v & 0x7ff; return;
    case 0x24: env->expevt = v & 0x7ff; return;
    case 0x28: env->intevt = v & 0x7ff; return;
    case 0x34: env->ptea = v & 0xf; return;
    case 0x38: cic.qacr[0] = v; return;
    case 0x3c: cic.qacr[1] = v; return;
    case 0x70: cic.pascr = v; return;
    case 0x78: cic.irmcr = v; return;
    default:
        qemu_log_mask(LOG_UNIMP, "ccn: write %02x = %08x (%u)\n", (unsigned)a, (unsigned)v, size);
    }
}

static const MemoryRegionOps ccn_ops = {
    .read = ccn_read, .write = ccn_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ------------------------------------------------------------------ cache e TLB mapeados (0xF0000000) */
static uint64_t mmct_read(void *opaque, hwaddr addr, unsigned size)
{
    CPUSH4State *env = &cic.cpu->env;
    switch (MM_REGION_TYPE(addr)) {
    case MM_ITLB_ADDR: return cpu_sh4_read_mmaped_itlb_addr(env, addr);
    case MM_ITLB_DATA: return cpu_sh4_read_mmaped_itlb_data(env, addr);
    case MM_UTLB_ADDR: return cpu_sh4_read_mmaped_utlb_addr(env, addr);
    case MM_UTLB_DATA: return cpu_sh4_read_mmaped_utlb_data(env, addr);
    default: return 0;
    }
}

static void mmct_write(void *opaque, hwaddr addr, uint64_t v, unsigned size)
{
    CPUSH4State *env = &cic.cpu->env;
    switch (MM_REGION_TYPE(addr)) {
    case MM_ITLB_ADDR: cpu_sh4_write_mmaped_itlb_addr(env, addr, v); break;
    case MM_ITLB_DATA: cpu_sh4_write_mmaped_itlb_data(env, addr, v); break;
    case MM_UTLB_ADDR: cpu_sh4_write_mmaped_utlb_addr(env, addr, v); break;
    case MM_UTLB_DATA: cpu_sh4_write_mmaped_utlb_data(env, addr, v); break;
    default: break;
    }
}

static const MemoryRegionOps mmct_ops = {
    .read = mmct_read, .write = mmct_write,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ------------------------------------------------------------------ entrada (controlador iDrive)
 * O HmiMain recebe rotor e botões como telegramas MTP (mensagens MOST do FBlock 0xE5) vindos do Root. O patch do HmiMain
 * (tools/cic/hmiinput.py) cria nele uma thread que pede telegramas ao QEMU com "trapa #0xC3" (r0 = 0x1DE30000 | op):
 *   op 0: classificar a thread (r4 = this, r5 = buf): 2 = 1ª chamada (criar a thread de injeção), 0 = thread real, 1 = thread de injeção
 *   op 1: próximo telegrama da fila: devolve o tamanho (0 = nenhum) e o torna o atual
 *   op 2: palavra de 32 bits (little-endian) do telegrama atual no deslocamento r4
 *   op 3/4/5: telegrama que o HMI enviou ao FBlock 0xE5 (início com r4 = tamanho; byte r5 no deslocamento r4; fim)
 * Os telegramas chegam pelo socket Unix de datagramas CIC_INPUT, uma linha por telegrama: "t <hex>" (o IDEmu monta os telegramas);
 * os enviados pelo HMI ao controlador saem como "x <hex>" para o socket CIC_OUTPUT (o controlador virtual do IDEmu responde).
 * CIC_INPUT_DEBUG=1 mostra cada telegrama no stderr. */
#define TEL_MAX 512
#define TEL_Q 256
typedef struct Tel { uint16_t len; uint8_t d[TEL_MAX]; } Tel;
static Tel telq[TEL_Q], tel_cur;
static unsigned telq_r, telq_w;
static QemuMutex tel_lock;
static uint32_t hc_this, hc_buf;
static int in_fd = -1, out_fd = -1;
static struct sockaddr_un out_addr;
static uint8_t tx_buf[TEL_MAX];
static unsigned tx_len;
static bool in_dbg;

static int hexv(int c)
{
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

static void cic_input_line(char *s)
{
    Tel t = { 0 };
    if (s[0] != 't' || s[1] != ' ') {
        return;
    }
    for (s += 2; *s && t.len < TEL_MAX; ) {
        if (*s == ' ') {
            s++;
            continue;
        }
        int h = hexv(s[0]), l = hexv(s[1]);
        if (h < 0 || l < 0) {
            return;
        }
        t.d[t.len++] = h << 4 | l;
        s += 2;
    }
    if (t.len < 4) {
        return;
    }
    qemu_mutex_lock(&tel_lock);
    if (telq_w - telq_r < TEL_Q) {
        telq[telq_w++ % TEL_Q] = t;
    }
    qemu_mutex_unlock(&tel_lock);
    if (in_dbg) {
        fprintf(stderr, "cic: telegrama na fila (%u bytes)\n", t.len);
    }
}

static void cic_input_read(void *opaque)
{
    char b[4096], *save = NULL;
    ssize_t n = recv(in_fd, b, sizeof(b) - 1, 0);
    if (n <= 0) {
        return;
    }
    b[n] = 0;
    for (char *l = strtok_r(b, "\r\n", &save); l; l = strtok_r(NULL, "\r\n", &save)) {
        cic_input_line(l);
    }
}

/* telegrama que o HMI mandou ao FBlock 0xE5: vai como "x <hex>" para o socket CIC_OUTPUT (do IDEmu), se existir */
static void cic_output_tel(void)
{
    char line[8 + TEL_MAX * 2];
    int n = snprintf(line, sizeof(line), "x ");
    for (unsigned i = 0; i < tx_len; i++) {
        n += snprintf(line + n, sizeof(line) - n, "%02x", tx_buf[i]);
    }
    if (in_dbg) {
        fprintf(stderr, "cic: HMI enviou ao controlador: %s\n", line + 2);
    }
    if (out_fd >= 0 && out_addr.sun_path[0]) {
        sendto(out_fd, line, n, MSG_DONTWAIT, (struct sockaddr *)&out_addr, sizeof(out_addr));
    }
}

static bool cic_hypercall(CPUSH4State *env)
{
    uint32_t r0 = env->gregs[0], ret = 0;
    if ((r0 & 0xffff0000) != 0x1de30000) {
        return false;
    }
    switch (r0 & 0xffff) {
    case 0:
        if (env->gregs[4] != hc_this || !hc_buf) {
            hc_this = env->gregs[4];
            hc_buf = env->gregs[5];
            ret = 2;
            fprintf(stderr, "cic: entrada do controlador ativa no HmiMain (this=%08x)\n", hc_this);
        } else {
            ret = env->gregs[5] == hc_buf ? 0 : 1;
        }
        break;
    case 1:
        qemu_mutex_lock(&tel_lock);
        if (telq_r != telq_w) {
            tel_cur = telq[telq_r++ % TEL_Q];
            ret = tel_cur.len;
        }
        qemu_mutex_unlock(&tel_lock);
        if (ret && in_dbg) {
            fprintf(stderr, "cic: telegrama entregue ao HmiMain:");
            for (int i = 0; i < tel_cur.len; i++) {
                fprintf(stderr, " %02x", tel_cur.d[i]);
            }
            fprintf(stderr, "\n");
        }
        break;
    case 2: {
        uint32_t o = env->gregs[4];
        for (int i = 3; i >= 0; i--) {
            ret = ret << 8 | (o + i < tel_cur.len ? tel_cur.d[o + i] : 0);
        }
        break;
    }
    case 3:                                     /* envio do HMI para 0xE5: início (r4 = tamanho) */
        tx_len = MIN(env->gregs[4], TEL_MAX);
        memset(tx_buf, 0, sizeof(tx_buf));
        break;
    case 4:                                     /* byte r5 no deslocamento r4 */
        if (env->gregs[4] < tx_len) {
            tx_buf[env->gregs[4]] = env->gregs[5];
        }
        break;
    case 5:                                     /* fim: repassa ao IDEmu */
        cic_output_tel();
        break;
    default:
        return false;
    }
    env->gregs[0] = ret;
    return true;
}

static void cic_input_init(void)
{
    const char *path = getenv("CIC_INPUT");
    qemu_mutex_init(&tel_lock);
    in_dbg = getenv("CIC_INPUT_DEBUG") != NULL;
    sh4_cic_hypercall = cic_hypercall;
    {
        const char *op = getenv("CIC_OUTPUT");
        if (op && *op && strlen(op) < sizeof(out_addr.sun_path)) {
            out_addr.sun_family = AF_UNIX;
            strcpy(out_addr.sun_path, op);
            out_fd = socket(AF_UNIX, SOCK_DGRAM, 0);
        }
    }
    if (!path || !*path) {
        return;
    }
    struct sockaddr_un sa = { .sun_family = AF_UNIX };
    if (strlen(path) >= sizeof(sa.sun_path)) {
        error_report("cic: caminho de CIC_INPUT longo demais");
        return;
    }
    strcpy(sa.sun_path, path);
    unlink(path);
    in_fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (in_fd < 0 || bind(in_fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        error_report("cic: não consegui abrir %s", path);
        if (in_fd >= 0) {
            close(in_fd);
        }
        in_fd = -1;
        return;
    }
    fcntl(in_fd, F_SETFL, fcntl(in_fd, F_GETFL) | O_NONBLOCK);
    qemu_set_fd_handler(in_fd, cic_input_read, NULL, NULL);
}

/* ------------------------------------------------------------------ máquina */
typedef struct ResetData { SuperHCPU *cpu; uint32_t vector; } ResetData;

static void main_cpu_reset(void *opaque)
{
    ResetData *s = opaque;
    cpu_reset(CPU(s->cpu));
    s->cpu->env.pc = s->vector;
    hc_this = hc_buf = 0;
}

static void cic_init(MachineState *machine)
{
    MemoryRegion *sysmem = get_system_memory();
    MemoryRegion *ram = g_new(MemoryRegion, 1);
    SuperHCPU *cpu = SUPERH_CPU(cpu_create(machine->cpu_type));
    ResetData *rd = g_new0(ResetData, 1);

    cic.cpu = cpu;
    rd->cpu = cpu; rd->vector = cpu->env.pc;
    qemu_register_reset(main_cpu_reset, rd);

    /* 256 MB na área 2 (0x08000000); o que passar disso fica no segundo banco DDR, em 0x58000000 (o startup do QNX o declara assim) */
    {
        uint64_t first = MIN(machine->ram_size, 256 * MiB);
        memory_region_init_ram(ram, NULL, "cic.ram", first, &error_fatal);
        memory_region_add_subregion(sysmem, RAM_BASE, ram);
        if (machine->ram_size > first) {
            MemoryRegion *ram2 = g_new(MemoryRegion, 1);
            memory_region_init_ram(ram2, NULL, "cic.ram2", machine->ram_size - first, &error_fatal);
            memory_region_add_subregion(sysmem, 0x58000000, ram2);
        }
    }

    cic_oc = g_new(MemoryRegion, 1);
    memory_region_init(cic_oc, NULL, "sh7785-onchip", 0x100000000ULL);
    {
        MemoryRegion *p4 = g_new(MemoryRegion, 1), *a7 = g_new(MemoryRegion, 1);
        memory_region_init_alias(p4, NULL, "oc-p4", cic_oc, 0xe0000000ULL, 0x20000000);
        memory_region_add_subregion(sysmem, 0xe0000000, p4);
        memory_region_init_alias(a7, NULL, "oc-a7", cic_oc, 0x1c000000ULL, 0x04000000);
        memory_region_add_subregion(sysmem, 0x1c000000, a7);
    }
    /* registradores da CPU: 0xFF000000 (e o espelho físico 0x1F000000) */
    memory_region_init_io(&cic.ccn, NULL, &ccn_ops, NULL, "cic-ccn", 0x80);
    cic_map_dual(&cic.ccn, 0xff000000);
    memory_region_init_io(&cic.mmct, NULL, &mmct_ops, NULL, "cic-mmct", 0x08000000);
    memory_region_add_subregion(sysmem, 0xf0000000, &cic.mmct);

    /* NOR de 128 MB em 0x0 (S29GL01GP, CFI AMD, 16 bits, setores de 128 KB): IPL/IFS/IFS2/EFS_RO */
    {
        DriveInfo *dinfo = drive_get(IF_PFLASH, 0, 0);
        pflash_cfi02_register(0x0, "cic.flash", 128 * MiB, dinfo ? blk_by_legacy_dinfo(dinfo) : NULL,
                              128 * KiB, 1, 2, 0x0001, 0x227e, 0x2228, 0x2201, 0x555, 0x2aa, 0);
    }

    cic_soc_init(sysmem, cpu, machine);
    cic_input_init();
}

static void cic_machine_init(MachineClass *mc)
{
    mc->desc = "BMW CIC High (iDrive 4, Harman L6) - SH7785";
    mc->init = cic_init;
    mc->default_cpu_type = TYPE_SH7785_CPU;
    mc->default_ram_size = 256 * MiB;
    mc->default_ram_id = "cic.ram.default";
}

DEFINE_MACHINE("cic", cic_machine_init)

/*
 * IDEmu CIC: PCI da placa. Ponte do SH7785 (PCIC em 0xFE040000, config por PAR=+0x1c0 / PDR=+0x220),
 * FPGA Xilinx da Harman (10EE:7534) e Fujitsu Carmine (10CF:202B), no início só como memória/registradores simples.
 */
#include "qemu/osdep.h"
#ifndef _WIN32
#include <sys/mman.h>
#endif
#include "cpu.h"
#include "ui/console.h"
#include "system/runstate.h"
#include "qemu/log.h"
#include "qemu/error-report.h"
#include "qemu/timer.h"
#include "qapi/error.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "hw/sh4/sh.h"
#include "hw/pci/pci_device.h"
#include "hw/pci/pci_host.h"
#include "system/system.h"
#include "qemu/timer.h"
#include "qom/object.h"
#include "cic.h"

#define TYPE_CIC_PCIC "cic-pcic"
OBJECT_DECLARE_SIMPLE_TYPE(CicPcic, CIC_PCIC)

struct CicPcic {
    PCIHostState parent_obj;
    PCIDevice *dev;
    qemu_irq irq[PCI_NUM_PINS];
    MemoryRegion regs;
    MemoryRegion pcimem;
    MemoryRegion win, win2;
    uint32_t par;
    uint32_t regfile[0x100];     /* 0x100..0x1bc e 0x1d0..: registradores do PCIC guardados como RAM */
};

static uint64_t pcic_read(void *p, hwaddr a, unsigned size)
{
    CicPcic *s = p;
    PCIHostState *phb = PCI_HOST_BRIDGE(s);
    switch (a) {
    case 0 ... 0xfc:
        return ldl_le_p(s->dev->config + a);
    case 0x1c0: return s->par;
    case 0x220: {
        /* dispositivo ausente lê 0 (como no PCIC real com este driver), não 0xffffffff */
        PCIDevice *pd = pci_find_device(phb->bus, (s->par >> 16) & 0xff, (s->par >> 8) & 0xff);
        return pd ? pci_data_read(phb->bus, s->par, 4) : 0;
    }
    default:
        qemu_log_mask(LOG_UNIMP, "pcic: R %03x = %08x\n", (unsigned)a, a < 0x400 ? s->regfile[a >> 2] : 0);
        if (a < 0x400) {
            return s->regfile[a >> 2];
        }
        return 0;
    }
}

static void pcic_write(void *p, hwaddr a, uint64_t v, unsigned size)
{
    CicPcic *s = p;
    PCIHostState *phb = PCI_HOST_BRIDGE(s);
    switch (a) {
    case 0 ... 0xfc:
        stl_le_p(s->dev->config + a, v);
        break;
    case 0x1c0: s->par = v; break;
    case 0x220:
        pci_data_write(phb->bus, s->par, v, 4); break;
    default:
        qemu_log_mask(LOG_UNIMP, "pcic: W %03x = %08x\n", (unsigned)a, (unsigned)v);
        if (a < 0x400) {
            s->regfile[a >> 2] = v;
        }
    }
}

static const MemoryRegionOps pcic_ops = {
    .read = pcic_read, .write = pcic_write, .endianness = DEVICE_NATIVE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

static int pcic_map_irq(PCIDevice *d, int irq_num) { return PCI_SLOT(d->devfn) == 5 ? 1 : 0; }   /* FPGA (slot 1) -> irq[0], Carmine (slot 5) -> irq[1] */
static void pcic_set_irq(void *opaque, int irq_num, int level)
{
    qemu_irq *pic = opaque;
    qemu_set_irq(pic[irq_num], level);
}

static void pcic_realize(DeviceState *dev, Error **errp)
{
    SysBusDevice *sbd = SYS_BUS_DEVICE(dev);
    CicPcic *s = CIC_PCIC(dev);
    PCIHostState *phb = PCI_HOST_BRIDGE(s);
    for (int i = 0; i < PCI_NUM_PINS; i++) {
        sysbus_init_irq(sbd, &s->irq[i]);
    }
    memory_region_init(&s->pcimem, OBJECT(s), "cic-pci-mem", 0x100000000ULL);
    memory_region_init_alias(&s->win, OBJECT(s), "cic-pci-win", &s->pcimem, 0xd0000000ULL, 0x10000000);
    memory_region_add_subregion_overlap(get_system_memory(), 0xd0000000, &s->win, 1);   /* endereçamento de 32 bits: físico = endereço PCI */
    phb->bus = pci_register_root_bus(dev, "pci", pcic_set_irq, pcic_map_irq, s->irq,
                                     &s->pcimem, get_system_io(),
                                     PCI_DEVFN(0, 0), PCI_NUM_PINS, TYPE_PCI_BUS);
    memory_region_init_io(&s->regs, OBJECT(s), &pcic_ops, s, "cic-pcic", 0x400);
    sysbus_init_mmio(sbd, &s->regs);
    s->dev = pci_create_simple(phb->bus, PCI_DEVFN(0, 0), "cic-pcic-bridge");
}

static void pcic_class_init(ObjectClass *oc, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->realize = pcic_realize;
}

/* ---- parte PCI da ponte (slot 0) */
static void bridge_class_init(ObjectClass *oc, const void *data)
{
    PCIDeviceClass *k = PCI_DEVICE_CLASS(oc);
    DeviceClass *dc = DEVICE_CLASS(oc);
    k->vendor_id = 0x1912;           /* Renesas */
    k->device_id = 0x0002;           /* SH7785 PCIC */
    k->class_id = PCI_CLASS_BRIDGE_HOST;
    dc->user_creatable = false;
}

/* ---- dispositivos de memória simples (FPGA, Carmine) */
typedef struct CicPciMem {
    PCIDevice parent_obj;
    MemoryRegion bar0, bar1;
    uint32_t *regs;
    uint8_t *vram;
    QemuConsole *con;
} CicPciMem;

/* FPGA: banco de registradores de 16 MB com log; valores iniciais em fpga_init_regs() */
static void fpga_init_regs(uint32_t *r)
{
    r[0x24 / 4] = 0x00010D00;       /* versão do FPGA (sysregs-l6-7534.cfg) */
    /* experimentos: CIC_FPGA_INIT="off=val,off=val" (hex) */
    const char *e = getenv("CIC_FPGA_INIT");
    while (e && *e) {
        char *end; unsigned long o = strtoul(e, &end, 16);
        if (*end != '=') break;
        unsigned long v = strtoul(end + 1, &end, 16);
        if (o < 0x1000000) r[o / 4] = v;
        e = (*end == ',') ? end + 1 : end;
    }
}


/*
 * Núcleo IPC do FPGA (BAR0+0xB0000) e a IOC (ST10) do outro lado, no nível do enlace do dev-ipc:
 *   +0x10 janela de dados (leitura = próximo quadro recebido, 4 bytes por palavra; escrita = quadro a enviar)
 *   +0x14 comando (grava): 0x01 inicia leitura do quadro, 0x02 zera o buffer de TX, 0x10 envia o quadro,
 *                          0x40 libera o quadro lido, 0x20 / 0x80 reconhecem os bits 5 / 7 do status
 *   +0x18 status:  bit 5 = há quadro recebido (RX), bit 7 = envio concluído (TX)
 *   +0x1c máscara de interrupção (bits 5 e 7)
 * Quadro: [len][canal][b2][b3] + dados, total len+2 bytes. Canal 0 = controle; tipo 0x10 = lista de clientes:
 * b2 = 0x10, b3 = n, depois n entradas [canal, nº de clientes, fluxo(1 = liberado), 0].
 */
#define IPC_FRAMES 64
#define IPC_MAXLEN 300
typedef struct { uint8_t d[IPC_MAXLEN]; int n; } IpcFrame;
static struct {
    CicPciMem *dev;
    uint32_t status, mask;
    IpcFrame rx[IPC_FRAMES];
    int rxh, rxt, rxc;                   /* fila de quadros da IOC para a CPU */
    int rdpos;                           /* posição de leitura no quadro da frente */
    uint8_t tx[IPC_MAXLEN + 8];
    int txn;
    bool ioc_up;
    QEMUTimer *t_txdone, *t_ioc, *t_ch2, *t_late;
    IpcFrame late[8];                    /* respostas da IOC com atraso (EEPROM etc.) */
    int late_n;
    int ioc_pending;                     /* respostas da IOC a enviar */
} ipc;

static void ipc_reset(void);

static void ipc_irq(void)
{
    if (ipc.dev) {
        qemu_log_mask(LOG_UNIMP, "ipc: irq=%d status=%02x mask=%02x\n", (ipc.status & ipc.mask) != 0, ipc.status, ipc.mask);
        pci_set_irq(PCI_DEVICE(ipc.dev), (ipc.status & ipc.mask) != 0);
    }
}

static void ipc_rx_push(const uint8_t *f, int n)
{
    if (ipc.rxc >= IPC_FRAMES || n > IPC_MAXLEN) {
        return;
    }
    memcpy(ipc.rx[ipc.rxt].d, f, n);
    ipc.rx[ipc.rxt].n = n;
    ipc.rxt = (ipc.rxt + 1) % IPC_FRAMES;
    ipc.rxc++;
    ipc.status |= 0x20;
    ipc_irq();
}

/* lista de clientes da IOC: canal 0 = liga a comunicação, canais 1..8 com 1 cliente cada */
static void ioc_send_list(void)
{
    uint8_t f[4 + 4 * 9];
    f[0] = 4 * 9 + 2; f[1] = 0; f[2] = 0x10; f[3] = 9;
    for (int c = 0; c < 9; c++) {
        f[4 + 4 * c] = c; f[5 + 4 * c] = 1; f[6 + 4 * c] = 1; f[7 + 4 * c] = 0;
    }
    ipc_rx_push(f, sizeof(f));
}

static void ipc_ioc_tick(void *o)
{
    ioc_send_list();
}

/*
 * Canal 2 (on/off): mensagens de 9 bytes nos dois sentidos. [0]=0x12 versão, [1]=motivo de wake-up, [3]=estado externo
 * (bits 0-3 MOST, bit 4 CAN), [4]=Ethernet da IOC (1/2), [5]=tensão bruta, [6]=evento (0 = nenhum), [7]=parâmetro do evento.
 */
static void ipc_ch2_tick(void *o)
{
    uint8_t f[2 + 9] = { 9, 2, 0x12, 0x06, 0x00, 0x00, 0x01, 0x74, 0x00, 0x00, 0x02 };
    if (getenv("CIC_WUR")) {
        f[3] = strtoul(getenv("CIC_WUR"), NULL, 0);          /* motivo de wake-up */
    }
    if (getenv("CIC_IOC3")) {
        f[5] = strtoul(getenv("CIC_IOC3"), NULL, 0);         /* estado externo (MOST/CAN) */
    }
    if (ipc.rxc >= 8) {
        /* o driver parou de ler (dev-ipc morreu no desligamento): descarta a fila e solta a linha de interrupção */
        ipc.rxh = ipc.rxt = ipc.rxc = 0;
        ipc.rdpos = 0;
        ipc.status &= ~0x20u;
        ipc_irq();
        return;
    }
    ipc_rx_push(f, sizeof(f));
    /* a IOC real publica o estado periodicamente; o app dá timeout se ficar mais de ~1,5 s sem mensagem */
    timer_mod(ipc.t_ch2, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 250 * SCALE_MS);
}

static void ipc_txdone_tick(void *o)
{
    ipc.status |= 0x80;
    ipc_irq();
}


/* respostas com atraso: a IOC leva alguns ms para responder */
static void ipc_late_tick(void *o)
{
    for (int i = 0; i < ipc.late_n; i++) {
        ipc_rx_push(ipc.late[i].d, ipc.late[i].n);
    }
    ipc.late_n = 0;
}

static void ipc_push_late(uint8_t ch, const uint8_t *payload, int n)
{
    if (ipc.late_n >= 8 || n + 2 > IPC_MAXLEN) {
        return;
    }
    IpcFrame *f = &ipc.late[ipc.late_n++];
    f->d[0] = n; f->d[1] = ch;
    memcpy(f->d + 2, payload, n);
    f->n = n + 2;
    if (!timer_pending(ipc.t_late)) {
        timer_mod(ipc.t_late, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 2 * SCALE_MS);
    }
}

/*
 * Canal 6 (túnel): o primeiro byte do payload escolhe o subcanal (3 = E2P, a EEPROM que fica atrás da IOC).
 * O vdev-eeprom manda [cmd, end_lo, end_hi, tam, chk] (cmd 1 = ler, 2 = gravar) e espera de volta
 *   (1) ACK de 5 bytes: [0xAA, ...]   (2) mensagem de dados [3, end_lo, end_hi, tam, dados...].
 */
#define E2P_SIZE 0x1000
static uint8_t e2p[E2P_SIZE];

static void ioc_tunnel_rx(const uint8_t *p, int n)
{
    if (n < 6 || p[0] != 3) {
        return;
    }
    unsigned cmd = p[1], addr = p[2] | (p[3] << 8), len = p[4];
    uint8_t ack[1 + 5] = { 3, 0xAA, 0x00, 0x00, 0x00, 0x01 };
    qemu_log_mask(LOG_UNIMP, "ipc: E2P cmd=%u addr=0x%x len=%u\n", cmd, addr, len);
    if (cmd == 1) {
        uint8_t d[1 + 4 + 255];
        d[0] = 3; d[1] = 3; d[2] = addr & 0xff; d[3] = addr >> 8; d[4] = len;
        for (unsigned i = 0; i < len; i++) {
            d[5 + i] = e2p[(addr + i) % E2P_SIZE];
        }
        ipc_push_late(6, ack, sizeof(ack));
        ipc_push_late(6, d, 5 + len);
    } else if (cmd == 2) {
        for (unsigned i = 0; i < len && 5 + i < (unsigned)n; i++) {
            e2p[(addr + i) % E2P_SIZE] = p[5 + i];
        }
        ipc_push_late(6, ack, sizeof(ack));
    }
}

static void ipc_tx_commit(void)
{
    int len = ipc.txn >= 1 ? ipc.tx[0] + 2 : 0;
    qemu_log_mask(LOG_UNIMP, "ipc: TX quadro len=%d ch=%d b2=%02x b3=%02x (%d bytes gravados)\n",
                  len, ipc.tx[1], ipc.tx[2], ipc.tx[3], ipc.txn);
    if (qemu_loglevel_mask(LOG_UNIMP)) {
        char hex[3 * 64 + 1];
        int n = MIN(ipc.txn, 64);
        for (int i = 0; i < n; i++) {
            snprintf(hex + 3 * i, 4, "%02x ", ipc.tx[i]);
        }
        hex[3 * n] = 0;
        qemu_log_mask(LOG_UNIMP, "ipc: TX dados %s\n", hex);
    }
    if (len >= 4 && ipc.tx[1] == 0 && ipc.tx[2] == 0x10 && !ipc.ioc_up) {
        ipc.ioc_up = true;                           /* a IOC responde à primeira lista com a dela */
        timer_mod(ipc.t_ioc, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 20 * SCALE_MS);
    }
    if (len >= 8 && ipc.tx[1] == 6) {
        ioc_tunnel_rx(ipc.tx + 2, ipc.tx[0]);
    }
    if (len >= 11 && ipc.tx[1] == 2 && ipc.tx[2] == 0x12 && ipc.tx[3] == 1) {
        /* o SH4 pediu à IOC que o reinicie (requestReset): a IOC corta e religa a CPU */
        qemu_log_mask(LOG_UNIMP, "ipc: SH4 pediu reset à IOC\n");
        if (!getenv("CIC_NORESET")) {
            qemu_system_reset_request(SHUTDOWN_CAUSE_GUEST_RESET);
        }
    }
    if (len >= 11 && ipc.tx[1] == 2 && ipc.tx[2] == 0x12 && !timer_pending(ipc.t_ch2)) {
        timer_mod(ipc.t_ch2, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 3 * SCALE_MS);
    }
    timer_mod(ipc.t_txdone, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 1 * SCALE_MS);
    ipc.txn = 0;
}

static void ipc_cmd(uint32_t v)
{
    if (v & 0x20) { ipc.status &= ~0x20u; }
    if (v & 0x80) { ipc.status &= ~0x80u; }
    if (v & 0x02) { ipc.txn = 0; }
    if (v & 0x10) { ipc_tx_commit(); }
    if (v & 0x01) { ipc.rdpos = 0; }
    if (v & 0x40) {                                  /* quadro lido: libera */
        if (ipc.rxc > 0) {
            ipc.rxh = (ipc.rxh + 1) % IPC_FRAMES;
            ipc.rxc--;
        }
        ipc.rdpos = 0;
        if (ipc.rxc > 0) {
            ipc.status |= 0x20;
        }
    }
    ipc_irq();
}

static uint32_t ipc_data_read(void)
{
    uint32_t v = 0;
    if (ipc.rxc > 0) {
        IpcFrame *f = &ipc.rx[ipc.rxh];
        for (int i = 0; i < 4; i++) {
            int p = ipc.rdpos + i;
            if (p < f->n) {
                v |= (uint32_t)f->d[p] << (8 * i);
            }
        }
    }
    ipc.rdpos += 4;
    return v;
}

static void ipc_data_write(uint32_t v)
{
    for (int i = 0; i < 4 && ipc.txn < IPC_MAXLEN; i++) {
        ipc.tx[ipc.txn++] = v >> (8 * i);
    }
}

static void ipc_init(CicPciMem *s)
{
    memset(e2p, getenv("CIC_E2P_FILL") ? (int)strtoul(getenv("CIC_E2P_FILL"), NULL, 0) : 0, sizeof(e2p));
    ipc.dev = s;
    ipc.t_txdone = timer_new_ns(QEMU_CLOCK_VIRTUAL, ipc_txdone_tick, NULL);
    ipc.t_ioc = timer_new_ns(QEMU_CLOCK_VIRTUAL, ipc_ioc_tick, NULL);
    ipc.t_ch2 = timer_new_ns(QEMU_CLOCK_VIRTUAL, ipc_ch2_tick, NULL);
    ipc.t_late = timer_new_ns(QEMU_CLOCK_VIRTUAL, ipc_late_tick, NULL);
}

static uint8_t mlb_idx_v;
uint8_t cic_mlb_idx_set(uint8_t v) { mlb_idx_v = v; return v; }

static uint32_t fpga_special(CicPciMem *s, hwaddr a, bool *hit)
{
    static const uint8_t mlb_ver[4] = { 0x55, 0x01, 0x00, 0x00 };   /* versão do núcleo MLB: 0x55010000 */
    *hit = true;
    switch (a) {
    case 0x8001c:                                       /* índice do byte da versão do núcleo MLB */
        return mlb_ver[mlb_idx_v & 3];
    /* IDE do FPGA (0x60000 mestre, 0x800000 escravo): sem disco -> status 0 */
    case 0x6005c: case 0x60070: case 0x80005c: case 0x800070:
        return 0;
    /* núcleo IPC (0xB0000): 0xB0034 é um registrador indexado (o dev-ipc grava 0,4,5,6 e lê o byte):
     * 0 = módulo (0x0A), 4/5/6 = ano/semana/revisão da versão (exige >= 04 49 2A) */
    case 0xb0010: return ipc_data_read();
    case 0xb0018: return ipc.status;
    case 0xb001c: return ipc.mask;
    case 0xb0034: {
        static const uint8_t ipc_id[8] = { 0x0a, 0, 0, 0, 0x04, 0x49, 0x2a, 0 };
        return ipc_id[s->regs[0xb0034 >> 2] & 7];
    }
    }
    *hit = false;
    return 0;
}

static uint64_t fpga_read(void *o, hwaddr a, unsigned size)
{
    CicPciMem *s = o;
    bool hit;
    uint32_t v = fpga_special(s, a & ~3ULL, &hit);
    if (!hit) {
        v = s->regs[a >> 2];
    }
    qemu_log_mask(LOG_UNIMP, "fpga: R %06x/%u = %08x\n", (unsigned)a, size, v);
    if (size == 4) return v;
    return (v >> ((a & 3) * 8)) & (size == 2 ? 0xffff : 0xff);
}

static void fpga_write(void *o, hwaddr a, uint64_t v, unsigned size)
{
    CicPciMem *s = o;
    qemu_log_mask(LOG_UNIMP, "fpga: W %06x/%u = %08x\n", (unsigned)a, size, (unsigned)v);
    switch (a & ~3ULL) {
    case 0xb0010: ipc_data_write(v); return;
    case 0xb0014: ipc_cmd(v); return;
    case 0xb0018: return;
    case 0xb001c: ipc.mask = v; ipc_irq(); return;
    case 0xb0034:
        if (v == 0) {
            ipc_reset();                    /* o dev-ipc está (re)inicializando: o SH4 reiniciou, a IOC recomeça a conversa */
        }
        break;
    }
    if ((a & ~3ULL) == 0x8001c) {
        s->regs[a >> 2] = v;
        extern uint8_t cic_mlb_idx_set(uint8_t);
        cic_mlb_idx_set(v & 3);
    }
    if (size == 4) { s->regs[a >> 2] = v; return; }
    uint32_t sh = (a & 3) * 8, m = (size == 2 ? 0xffff : 0xff) << sh;
    s->regs[a >> 2] = (s->regs[a >> 2] & ~m) | ((v << sh) & m);
}

static const MemoryRegionOps fpga_ops = {
    .read = fpga_read, .write = fpga_write, .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};
#define CIC_PCIMEM(o) ((CicPciMem *)(o))

typedef struct { uint16_t vid, did, cls; uint32_t b0, b1; } CicPciInfo;
static const CicPciInfo fpga_info = { 0x10ee, 0x7534, 0x1180, 0x1000000, 0 };
static const CicPciInfo carmine_info = { 0x10cf, 0x202b, 0x0380, 0x1000000, 0x8000000 };

static void pcimem_realize(PCIDevice *d, Error **errp)
{
    CicPciMem *s = CIC_PCIMEM(d);
    s->regs = g_malloc0(0x1000000);
    fpga_init_regs(s->regs);
    ipc_init(s);
    memory_region_init_io(&s->bar0, OBJECT(d), &fpga_ops, s, "cic-fpga", 0x1000000);
    pci_register_bar(d, 0, PCI_BASE_ADDRESS_SPACE_MEMORY, &s->bar0);
    d->config[PCI_INTERRUPT_PIN] = 1;
}

/* Carmine (Fujitsu MB86297): BAR0 = registradores (modelo mínimo, com log), BAR1 = memória de vídeo */
static uint64_t carmine_read(void *o, hwaddr a, unsigned size)
{
    CicPciMem *s = o;
    uint32_t v = s->regs[a >> 2];
    if ((a & ~3ULL) == 0x30000c) {
        v &= ~0xfu;                       /* controlador DDR: os bits de comando se limpam sozinhos quando termina */
    }
    if ((a & ~3ULL) == 0x28000) {
        v = 0x3f8000;                     /* FIFO de comandos: bit 14 = cheio (0), bits 21:15 = posições livres (máximo) */
    }
    if (size < 4) {
        v = (v >> ((a & 3) * 8)) & (size == 2 ? 0xffff : 0xff);
    }
    if (current_cpu) {
        qemu_log_mask(LOG_UNIMP, "carmine: R %06x/%u = %08x pc=%08x pr=%08x\n", (unsigned)a, size, v,
                      (unsigned)SUPERH_CPU(current_cpu)->env.pc, (unsigned)SUPERH_CPU(current_cpu)->env.pr);
    } else {
        qemu_log_mask(LOG_UNIMP, "carmine: R %06x/%u = %08x\n", (unsigned)a, size, v);
    }
    return v;
}

/*
 * FIFO de comandos (0x28400): os comandos são palavras de 32 bits; por enquanto só interpretamos o "store" (0x34000000, endereço, valor),
 * que o driver usa como marca de sincronismo.
 */
static struct { uint32_t w[4]; int n; } cfifo;

static QEMUTimer *carmine_vsync_timer;

static void carmine_irq_update(CicPciMem *s)
{
    pci_set_irq(PCI_DEVICE(s), (s->regs[0x400000 >> 2] & s->regs[0x400004 >> 2]) != 0);
}

static void carmine_cmd_word(CicPciMem *s, uint32_t w)
{
    cfifo.w[cfifo.n++] = w;
    if ((cfifo.w[0] >> 24) == 0x34 && cfifo.n == 3) {
        uint32_t addr = cfifo.w[1];
        if (s->vram && addr + 4 <= 0x8000000) {
            stl_le_p(s->vram + addr, cfifo.w[2]);
        }
        s->regs[0x400000 >> 2] |= 0x800;          /* sync concluído (IRQ 0x800: o ISR do driver acorda o wait_idle) */
        carmine_irq_update(s);
        cfifo.n = 0;
    } else if ((cfifo.w[0] >> 24) != 0x34 || cfifo.n >= 4) {
        qemu_log_mask(LOG_UNIMP, "carmine: cmd %08x (+%d)\n", cfifo.w[0], cfifo.n - 1);
        cfifo.n = 0;
    }
}

static void carmine_write(void *o, hwaddr a, uint64_t v, unsigned size)
{
    CicPciMem *s = o;
    if (a == 0x28400 && size == 4) {
        carmine_cmd_word(s, v);
    }
    if (a == 0x400000 && size == 4) {                /* status de interrupção: escrever 1 limpa */
        s->regs[a >> 2] &= ~(uint32_t)v;
        carmine_irq_update(s);
        return;
    }
    if (current_cpu) {
        qemu_log_mask(LOG_UNIMP, "carmine: W %06x/%u = %08x pc=%08x pr=%08x\n", (unsigned)a, size, (unsigned)v,
                      (unsigned)SUPERH_CPU(current_cpu)->env.pc, (unsigned)SUPERH_CPU(current_cpu)->env.pr);
    } else {
        qemu_log_mask(LOG_UNIMP, "carmine: W %06x/%u = %08x\n", (unsigned)a, size, (unsigned)v);
    }
    if (size == 4) {
        s->regs[a >> 2] = v;
    } else {
        uint32_t sh = (a & 3) * 8, m = (size == 2 ? 0xffff : 0xff) << sh;
        s->regs[a >> 2] = (s->regs[a >> 2] & ~m) | ((v << sh) & m);
    }
    if (a == 0x400004) {
        carmine_irq_update(s);
    }
}

static const MemoryRegionOps carmine_ops = {
    .read = carmine_read, .write = carmine_write, .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/*
 * Saída de vídeo: composição das camadas do display 0 (registradores em 0x100000, layout do MB86297 "Carmine"): L0 (baixo) ... L5 (topo)
 * sobre fundo preto. Camada ligada = bit 31 do Ln_EXT_MODE (0x110 + 0x10*n); Ln_MODE_W_H: bits 16..27 = largura da linha em unidades de
 * 64 bytes, bits 0..11 = altura-1; Ln_ORG_ADR = endereço na VRAM. Pixel de 32 bits R<<24|G<<16|B<<8|A com alpha por pixel não
 * pré-multiplicado. A imagem composta fica em cfb[] (0xffRRGGBB) e vai para a janela do QEMU e/ou para o arquivo de quadros do IDEmu
 * (CIC_FRAME=caminho: cabeçalho 'IDFR', seq, largura, altura em 32 bytes + RGB, o formato do frame.rgb dos outros ambientes).
 */
#define CFB_W 1280
#define CFB_H 480
static uint32_t cfb[CFB_W * CFB_H];
static uint32_t cfb_seq;

static void carmine_compose(CicPciMem *s)
{
    static const uint32_t mode_reg[6] = { 0x20, 0x30, 0x40, 0x58, 0x70, 0x88 };
    static const uint32_t org_reg[6] = { 0x24, 0x34, 0x44, 0x5c, 0x74, 0x8c };
    /* só recompõe se a configuração das camadas mudou ou se a VRAM de alguma camada ligada foi escrita (dirty log VGA): a composição
       roda com o lock global e, feita a cada atualização, atrasava o guest */
    static uint32_t last_cfg[18];
    uint32_t cfg[18];
    bool dirty = false;
    for (int n = 0; n < 6; n++) {
        cfg[n * 3] = s->regs[(0x100110 + 0x10 * n) >> 2];
        cfg[n * 3 + 1] = s->regs[(0x100000 + mode_reg[n]) >> 2];
        cfg[n * 3 + 2] = s->regs[(0x100000 + org_reg[n]) >> 2];
    }
    if (memcmp(cfg, last_cfg, sizeof(cfg)) != 0) {
        memcpy(last_cfg, cfg, sizeof(cfg));
        dirty = true;
    }
    if (memory_region_is_ram(&s->bar1)) {
        for (int n = 0; n < 6; n++) {
            uint32_t ls = ((cfg[n * 3 + 1] >> 16) & 0xfff) * 64, lh2 = (cfg[n * 3 + 1] & 0xfff) + 1, b = cfg[n * 3 + 2];
            if ((cfg[n * 3] & 0x80000000) && ls && b && b + (uint64_t)ls * lh2 <= 0x8000000) {
                DirtyBitmapSnapshot *snap = memory_region_snapshot_and_clear_dirty(&s->bar1, b, (hwaddr)ls * lh2, DIRTY_MEMORY_VGA);
                if (memory_region_snapshot_get_dirty(&s->bar1, snap, b, (hwaddr)ls * lh2)) {
                    dirty = true;
                }
                g_free(snap);
            }
        }
    } else {
        dirty = true;
    }
    if (!dirty) {
        return;
    }
    memset(cfb, 0, sizeof(cfb));
    for (int n = 0; n < 6; n++) {
        uint32_t ext = cfg[n * 3], mode = cfg[n * 3 + 1], base = cfg[n * 3 + 2];
        uint32_t lstride = ((mode >> 16) & 0xfff) * 64;
        int lh = (mode & 0xfff) + 1;
        if (!(ext & 0x80000000) || !lstride || !base) {
            continue;
        }
        int lw = MIN(CFB_W, (int)(lstride / 4));
        lh = MIN(lh, CFB_H);
        if (base + (uint64_t)lstride * lh > 0x8000000) {
            continue;
        }
        for (int y = 0; y < lh; y++) {
            const uint32_t *src = (const uint32_t *)(s->vram + base + (size_t)y * lstride);
            uint32_t *d = cfb + (size_t)y * CFB_W;
            for (int x = 0; x < lw; x++) {
                uint32_t v = ldl_le_p(src + x);
                /* O alpha da camada não é confiável aqui: o blend por software do libffb não grava o canal alpha (no Carmine o blend
                   o grava), então parte do conteúdo fica com alpha 0 e parte com o alpha parcial das imagens copiadas. A imagem certa
                   sai ignorando o alpha; só a cor de limpeza do HMI (branco transparente, 0xffffff00) é tratada como transparente. */
                if (v == 0xffffff00u) {
                    continue;
                }
                d[x] = 0xff000000 | (v >> 8);
            }
        }
    }
    cfb_seq++;
}

static bool carmine_gfx_update(void *opaque)
{
    CicPciMem *s = opaque;
    static uint32_t shown = ~0u;
    DisplaySurface *ds = qemu_console_surface(s->con);
    if (surface_width(ds) != CFB_W || surface_height(ds) != CFB_H) {
        qemu_console_resize(s->con, CFB_W, CFB_H);
        ds = qemu_console_surface(s->con);
        shown = ~0u;
    }
    carmine_compose(s);
    if (shown == cfb_seq) {
        return true;
    }
    shown = cfb_seq;
    uint8_t *dst = surface_data(ds);
    int stride = surface_stride(ds);
    for (int y = 0; y < CFB_H; y++) {
        memcpy(dst + (size_t)y * stride, cfb + (size_t)y * CFB_W, CFB_W * 4);
    }
    qemu_console_update_full(s->con);
    return true;
}

/* arquivo de quadros do IDEmu (CIC_FRAME): no máximo ~30 quadros/s, só quando a imagem muda */
static QEMUTimer *frame_timer;
static uint8_t *frame_map;
static void carmine_frame_tick(void *o)
{
    CicPciMem *s = o;
    static uint32_t written = ~0u, out_seq;
    carmine_compose(s);
    if (frame_map && written != cfb_seq) {
        written = cfb_seq;
        uint8_t *p = frame_map + 32;
        for (size_t i = 0; i < CFB_W * CFB_H; i++) {
            uint32_t v = cfb[i];
            p[0] = v >> 16; p[1] = v >> 8; p[2] = v;
            p += 3;
        }
        uint32_t hdr[4] = { 0x52464449, ++out_seq, CFB_W, CFB_H };
        smp_wmb();
        memcpy(frame_map, hdr, sizeof(hdr));
    }
    timer_mod(frame_timer, qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + 33);
}

static void carmine_frame_init(CicPciMem *s)
{
    const char *path = g_getenv("CIC_FRAME");
    if (!path || !*path) {
        return;
    }
    size_t sz = 32 + (size_t)CFB_W * CFB_H * 3;
#ifdef _WIN32
    g_autofree gunichar2 *wide_path = g_utf8_to_utf16(path, -1, NULL, NULL, NULL);
    if (!wide_path) {
        error_report("cic: invalid frame path %s", path);
        return;
    }
    HANDLE file = CreateFileW(wide_path, GENERIC_READ | GENERIC_WRITE,
                              FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) {
        error_report("cic: could not create %s (error %lu)", path, GetLastError());
        return;
    }
    HANDLE mapping = CreateFileMappingW(file, NULL, PAGE_READWRITE, 0, sz, NULL);
    CloseHandle(file);
    if (mapping) {
        frame_map = MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, sz);
        CloseHandle(mapping);
    }
    if (!frame_map) {
        error_report("cic: could not map frame file %s", path);
        return;
    }
#else
    int fd = open(path, O_RDWR | O_CREAT | O_TRUNC, 0644);
    if (fd < 0 || ftruncate(fd, sz) != 0) {
        error_report("cic: não consegui criar %s", path);
        if (fd >= 0) {
            close(fd);
        }
        return;
    }
    frame_map = mmap(NULL, sz, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (frame_map == MAP_FAILED) {
        frame_map = NULL;
        return;
    }
#endif
    frame_timer = timer_new_ms(QEMU_CLOCK_REALTIME, carmine_frame_tick, s);
    timer_mod(frame_timer, qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + 100);
}

static const GraphicHwOps carmine_gfx_ops = { .gfx_update = carmine_gfx_update };

static void carmine_vsync_tick(void *o)
{
    CicPciMem *s = o;
    s->regs[0x400000 >> 2] |= 0x4;                   /* vsync do display principal (~60 Hz) */
    carmine_irq_update(s);
    timer_mod(carmine_vsync_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + NANOSECONDS_PER_SECOND / 60);
}

/* diagnóstico: CIC_VRAM_TRACE=1 troca a VRAM por uma região de E/S que registra as primeiras escritas da CPU */
static uint64_t vtr_read(void *o, hwaddr a, unsigned size)
{
    CicPciMem *s = o;
    uint64_t v = 0;
    memcpy(&v, s->vram + a, size);
    return v;
}
static void vtr_write(void *o, hwaddr a, uint64_t v, unsigned size)
{
    static int n;
    CicPciMem *s = o;
    memcpy(s->vram + a, &v, size);
    {
        /* CIC_VRAM_TRACE=0xVALOR: registra quem grava esse valor de 32 bits (até 4 vezes por par pc/pr) */
        static uint32_t want; static int init; static uint32_t seen[512][3];
        if (!init) { const char *e = getenv("CIC_VRAM_TRACE"); want = e ? strtoul(e, NULL, 0) : 0; init = 1; }
        if (want > 1 && size == 4 && (uint32_t)v == want && current_cpu) {
            CPUSH4State *env = &SUPERH_CPU(current_cpu)->env;
            unsigned h = ((env->pc >> 1) ^ (env->pr >> 3)) & 511;
            if (seen[h][0] != env->pc || seen[h][1] != env->pr) { seen[h][0] = env->pc; seen[h][1] = env->pr; seen[h][2] = 0; }
            if (seen[h][2]++ < 4) {
                qemu_log_mask(LOG_UNIMP, "vramval: W %08x = %08x pc=%08x pr=%08x\n", (unsigned)a, (unsigned)v, env->pc, env->pr);
            }
        }
    }
    if (n++ < 400 || (n % 100000) == 0) {
        qemu_log_mask(LOG_UNIMP, "vram: W %08x/%u = %08x pc=%08x (#%d)\n", (unsigned)a, size, (unsigned)v,
                      current_cpu ? (unsigned)SUPERH_CPU(current_cpu)->env.pc : 0, n);
    }
}
static const MemoryRegionOps vtr_ops = { .read = vtr_read, .write = vtr_write, .endianness = DEVICE_LITTLE_ENDIAN,
                                         .valid = { .min_access_size = 1, .max_access_size = 4 } };

static void carmine_realize(PCIDevice *d, Error **errp)
{
    CicPciMem *s = CIC_PCIMEM(d);
    carmine_vsync_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, carmine_vsync_tick, s);
    timer_mod(carmine_vsync_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + NANOSECONDS_PER_SECOND / 60);
    s->regs = g_malloc0(0x1000000);
    /* o devg-carmine usa BAR2 = memória de vídeo e BAR3 = registradores (6 MB mapeados) */
    if (getenv("CIC_VRAM_TRACE")) {
        s->vram = g_malloc0(0x8000000);
        memory_region_init_io(&s->bar1, OBJECT(d), &vtr_ops, s, "carmine-vram", 0x8000000);
    } else {
        memory_region_init_ram(&s->bar1, OBJECT(d), "carmine-vram", 0x8000000, errp);
        s->vram = memory_region_get_ram_ptr(&s->bar1);
        memory_region_set_log(&s->bar1, true, DIRTY_MEMORY_VGA);
    }
    s->con = qemu_graphic_console_create(DEVICE(d), 0, &carmine_gfx_ops, s);
    carmine_frame_init(s);
    memory_region_init_io(&s->bar0, OBJECT(d), &carmine_ops, s, "carmine-regs", 0x800000);
    pci_register_bar(d, 2, PCI_BASE_ADDRESS_SPACE_MEMORY, &s->bar1);
    pci_register_bar(d, 3, PCI_BASE_ADDRESS_SPACE_MEMORY, &s->bar0);
    d->config[PCI_INTERRUPT_PIN] = 1;
}

/* reset do sistema (a CPU reinicia, a IOC/FPGA continuam): o estado do IPC volta ao zero */
static void ipc_reset(void)
{
    if (!ipc.t_txdone) {
        return;
    }
    timer_del(ipc.t_txdone); timer_del(ipc.t_ioc); timer_del(ipc.t_ch2); timer_del(ipc.t_late);
    ipc.status = ipc.mask = 0;
    ipc.rxh = ipc.rxt = ipc.rxc = 0;
    ipc.rdpos = 0; ipc.txn = 0; ipc.late_n = 0;
    ipc.ioc_up = false;
    if (ipc.dev) {
        pci_set_irq(PCI_DEVICE(ipc.dev), 0);
    }
}

static void fpga_reset(DeviceState *dev)
{
    CicPciMem *s = CIC_PCIMEM(dev);
    if (s->regs) {
        memset(s->regs, 0, 0x1000000);
        fpga_init_regs(s->regs);
    }
    ipc_reset();
}

static void fpga_class_init(ObjectClass *oc, const void *data)
{
    PCIDeviceClass *k = PCI_DEVICE_CLASS(oc);
    device_class_set_legacy_reset(DEVICE_CLASS(oc), fpga_reset);
    k->vendor_id = fpga_info.vid; k->device_id = fpga_info.did; k->class_id = 0x1180;
    k->realize = pcimem_realize;
    DEVICE_CLASS(oc)->user_creatable = false;
}

static void carmine_class_init(ObjectClass *oc, const void *data)
{
    PCIDeviceClass *k = PCI_DEVICE_CLASS(oc);
    k->vendor_id = carmine_info.vid; k->device_id = carmine_info.did; k->class_id = 0x0380;
    k->realize = carmine_realize;
    DEVICE_CLASS(oc)->user_creatable = false;
}

static const TypeInfo cic_pci_types[] = {
    { .name = TYPE_CIC_PCIC, .parent = TYPE_PCI_HOST_BRIDGE, .instance_size = sizeof(CicPcic), .class_init = pcic_class_init },
    { .name = "cic-pcic-bridge", .parent = TYPE_PCI_DEVICE, .instance_size = sizeof(PCIDevice), .class_init = bridge_class_init,
      .interfaces = (const InterfaceInfo[]) { { INTERFACE_CONVENTIONAL_PCI_DEVICE }, { } } },
    { .name = "cic-fpga", .parent = TYPE_PCI_DEVICE, .instance_size = sizeof(CicPciMem), .class_init = fpga_class_init,
      .interfaces = (const InterfaceInfo[]) { { INTERFACE_CONVENTIONAL_PCI_DEVICE }, { } } },
    { .name = "cic-carmine", .parent = TYPE_PCI_DEVICE, .instance_size = sizeof(CicPciMem), .class_init = carmine_class_init,
      .interfaces = (const InterfaceInfo[]) { { INTERFACE_CONVENTIONAL_PCI_DEVICE }, { } } },
};
DEFINE_TYPES(cic_pci_types)

void cic_pci_init(MemoryRegion *sysmem, qemu_irq irq, qemu_irq irq_carmine)
{
    DeviceState *dev = qdev_new(TYPE_CIC_PCIC);
    SysBusDevice *sb = SYS_BUS_DEVICE(dev);
    PCIBus *bus;
    sysbus_realize_and_unref(sb, &error_fatal);
    cic_map_dual(sysbus_mmio_get_region(sb, 0), 0xfe040000);
    sysbus_connect_irq(sb, 0, irq);
    sysbus_connect_irq(sb, 1, irq_carmine);
    bus = PCI_HOST_BRIDGE(dev)->bus;
    if (!getenv("CIC_NOFPGA")) {
        pci_create_simple(bus, PCI_DEVFN(1, 0), "cic-fpga");
    }
    if (!getenv("CIC_NOCARMINE")) {
        pci_create_simple(bus, PCI_DEVFN(5, 0), "cic-carmine");
    }
    if (getenv("CIC_NOFPGA")) {
        /* diagnóstico */
    }
}

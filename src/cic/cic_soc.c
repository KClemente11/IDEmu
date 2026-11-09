/* IDEmu CIC: periféricos on-chip do SH7785 e da placa. */
#include "qemu/osdep.h"
#include "qemu/log.h"
#include "qapi/error.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "hw/sh4/sh.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/qdev-properties-system.h"
#include "hw/misc/unimp.h"
#include "system/system.h"
#include "hw/sh4/sh_intc.h"
#include "hw/timer/tmu012.h"
#include "cic.h"

/*
 * Controlador de interrupções INT2 do SH7785 (INTEVT 0x400..0xFE0): o QNX (callouts da página de
 * sistema) lê o código em INTEVT, calcula o campo de prioridade em INT2PRIn (0xFFD40000 + off) pelo
 * índice (INTEVT-0x400)/0x20 e mascara/desmascara escrevendo 0/valor nesse campo de 8 bits.
 * A tabela abaixo foi lida da memória do guest (callout "id" do startup 008_090_002).
 */
enum {
    UNUSED = 0,
    TMU0, TMU1, TMU2_TUNI, TMU2_TICPI,
    SCIF0_ERI, SCIF0_RXI, SCIF0_BRI, SCIF0_TXI,
    SCIF1_ERI, SCIF1_RXI, SCIF1_BRI, SCIF1_TXI,
    SCIF2, SCIF3, WDT,
    SCIF0, SCIF1,           /* grupos (um campo de prioridade para os 4 eventos) */
    PCIB,                   /* interrupção do Carmine (PCI INTA do slot 5): irq 2 do QNX = IRL 2 = INTEVT 0x240 */
    PCIA,                   /* interrupção do FPGA (PCI INTA): irq 10 do QNX (vetor 106 do kernel) = IRL 10 = INTEVT 0x340 */
    NR_SOURCES,
};

#define FPGA_IRL 10
#define CARMINE_IRL 2

static struct intc_vect vectors[] = {
    INTC_VECT(WDT, 0x560),
    INTC_VECT(TMU0, 0x580), INTC_VECT(TMU1, 0x5a0),
    INTC_VECT(TMU2_TUNI, 0x5c0), INTC_VECT(TMU2_TICPI, 0x5e0),
    INTC_VECT(SCIF0_ERI, 0x700), INTC_VECT(SCIF0_RXI, 0x720),
    INTC_VECT(SCIF0_BRI, 0x740), INTC_VECT(SCIF0_TXI, 0x760),
    INTC_VECT(SCIF1_ERI, 0x780), INTC_VECT(SCIF1_RXI, 0x7a0),
    INTC_VECT(SCIF1_BRI, 0x7c0), INTC_VECT(SCIF1_TXI, 0x7e0),
    INTC_VECT(SCIF2, 0x980), INTC_VECT(SCIF3, 0x9a0),
    INTC_VECT(PCIB, 0x200 + CARMINE_IRL * 0x20),
    INTC_VECT(PCIA, 0x200 + FPGA_IRL * 0x20),     /* IRL n = INTEVT 0x200 + n*0x20 (callout id do QNX) */
};

static struct intc_group groups[] = {
    INTC_GROUP(SCIF0, SCIF0_ERI, SCIF0_RXI, SCIF0_BRI, SCIF0_TXI),
    INTC_GROUP(SCIF1, SCIF1_ERI, SCIF1_RXI, SCIF1_BRI, SCIF1_TXI),
};

static struct intc_prio_reg prio_registers[] = {
    { 0xffd40000, 0, 32, 8, { TMU0, TMU1, TMU2_TUNI, TMU2_TICPI } },       /* INT2PRI0 */
    { 0xffd40008, 0, 32, 8, { SCIF0, SCIF1, SCIF2, SCIF3 } },              /* INT2PRI2 */
    { 0xffd4000c, 0, 32, 8, { 0, 0, WDT, 0 } },                            /* INT2PRI3 */
    { 0xffd40100, 0, 32, 8, { PCIA, PCIB, 0, 0 } },                           /* fictício: só para a fonte existir (habilitada pelo INT2PRI4 abaixo) */
};

static struct intc_desc intc;

/*
 * Máscara das interrupções IRL no INT2: o callout de id do QNX mascara a fonte escrevendo 1<<(31-n) em INT2MSKR
 * (0xffd40080) e o de unmask limpa o bit em INT2MSKCR (0xffd40084). 0xffd00024 (status do INTC) precisa ser > 0x0f000000
 * para o callout aceitar o evento.
 */
static uint32_t irl_mask = 0xffffffff;
static bool pci_line[2];                       /* 0 = FPGA (IRL 10), 1 = Carmine (IRL 2) */
static const int pci_irl[2] = { FPGA_IRL, CARMINE_IRL };
static const int pci_src[2] = { PCIA, PCIB };

static void fpga_update(void)
{
    for (int i = 0; i < 2; i++) {
        qemu_set_irq(intc.irqs[pci_src[i]], pci_line[i] && !(irl_mask & (1u << (31 - pci_irl[i]))));
    }
}

static uint64_t msk_read(void *o, hwaddr a, unsigned sz) { return irl_mask; }
static void msk_write(void *o, hwaddr a, uint64_t v, unsigned sz)
{
    if (a == 0) {
        irl_mask |= v;
    } else {
        irl_mask &= ~v;
    }
    fpga_update();
}
static const MemoryRegionOps msk_ops = { .read = msk_read, .write = msk_write, .endianness = DEVICE_NATIVE_ENDIAN,
                                         .valid.min_access_size = 4, .valid.max_access_size = 4 };
static uint64_t st_read(void *o, hwaddr a, unsigned sz) { return 0x1f000000; }
static void st_write(void *o, hwaddr a, uint64_t v, unsigned sz) { }
static const MemoryRegionOps st_ops = { .read = st_read, .write = st_write, .endianness = DEVICE_NATIVE_ENDIAN,
                                        .valid.min_access_size = 4, .valid.max_access_size = 4 };

static void fpga_irq_set(void *o, int n, int level)   /* n = 0 FPGA, 1 Carmine */
{
    pci_line[n & 1] = level;
    fpga_update();
}

static DeviceState *cic_scif(MemoryRegion *sysmem, hwaddr base, int idx,
                             int eri, int rxi, int bri, int txi)
{
    DeviceState *dev = qdev_new("cic-scif");
    SysBusDevice *sb = SYS_BUS_DEVICE(dev);
    qdev_prop_set_chr(dev, "chardev", serial_hd(idx));
    sysbus_realize_and_unref(sb, &error_fatal);
    cic_map_dual(sysbus_mmio_get_region(sb, 0), base);
    qdev_connect_gpio_out_named(dev, "eri", 0, intc.irqs[eri]);
    qdev_connect_gpio_out_named(dev, "rxi", 0, intc.irqs[rxi]);
    qdev_connect_gpio_out_named(dev, "txi", 0, intc.irqs[txi]);
    qdev_connect_gpio_out_named(dev, "bri", 0, intc.irqs[bri]);
    return dev;
}

void cic_soc_init(MemoryRegion *sysmem, SuperHCPU *cpu, MachineState *machine)
{
    MemoryRegion *rootmem = sysmem;
    /* resto: registra acessos (-d unimp) em vez de abortar (prioridade baixa: dispositivos reais vencem) */
    if (getenv("CIC_CATCHALL")) {
        create_unimplemented_device("catch-all", 0x0, 0x100000000ULL);
    }
    create_unimplemented_device("sh7785-p4", 0xfc000000, 0x04000000);
    create_unimplemented_device("sh7785-a7", 0x1c000000, 0x04000000);

    /* periféricos on-chip só existem em P4 (0xE0000000+): contêiner próprio exposto por um alias */
    sysmem = cic_oc;

    sh_intc_init(sysmem, &intc, NR_SOURCES, NULL, 0, _INTC_ARRAY(prio_registers));
    sh_intc_register_sources(&intc, _INTC_ARRAY(vectors), _INTC_ARRAY(groups));
    cpu->env.intc_handle = &intc;

    tmu012_init(sysmem, 0x1fd80000, TMU012_FEAT_TOCR | TMU012_FEAT_3CHAN | TMU012_FEAT_EXTCLK,
                49500000, intc.irqs[TMU0], intc.irqs[TMU1], intc.irqs[TMU2_TUNI], intc.irqs[TMU2_TICPI]);

    cic_scif(sysmem, 0xffea0000, 0, SCIF0_ERI, SCIF0_RXI, SCIF0_BRI, SCIF0_TXI);
    cic_scif(sysmem, 0xffeb0000, 1, SCIF1_ERI, SCIF1_RXI, SCIF1_BRI, SCIF1_TXI);

    {
        /*
         * Interrupção do FPGA (IRL 10, INTEVT 0x340) ligada à CPU; CIC_FPGA_IRQ=0 desliga (depuração).
         */
        if (!(getenv("CIC_FPGA_IRQ") && getenv("CIC_FPGA_IRQ")[0] == '0')) {
            static MemoryRegion msk_mr, st_mr;
            memory_region_init_io(&msk_mr, NULL, &msk_ops, NULL, "int2mskr", 8);
            cic_map_dual(&msk_mr, 0xffd40080);
            memory_region_init_io(&st_mr, NULL, &st_ops, NULL, "intc-status", 4);
            cic_map_dual(&st_mr, 0xffd00024);
            sh_intc_toggle_source(&intc.sources[PCIA], 1, 0);
            sh_intc_toggle_source(&intc.sources[PCIB], 1, 0);
        }
    }
    cic_pci_init(rootmem, qemu_allocate_irq(fpga_irq_set, NULL, 0), qemu_allocate_irq(fpga_irq_set, NULL, 1));

}

/*
 * Minimal OMAP5432 uEVM-like board, just enough to run QNX startup-omap5432uevm.
 * Not a faithful model: most of the L4 peripheral space is a write-through
 * register file with a few lock/idle-status tricks.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/log.h"
#include "hw/core/sysbus.h"
#include "hw/arm/boot.h"
#include "hw/arm/machines-qom.h"
#include "hw/core/boards.h"
#include "hw/char/serial-mm.h"
#include "hw/cpu/a15mpcore.h"
#include "system/system.h"
#include "system/address-spaces.h"
#include "hw/core/qdev-properties.h"
#include "qemu/units.h"
#include "qom/object.h"
#include "target/arm/cpu-qom.h"
#include <sys/socket.h>
#include <sys/un.h>

#define TYPE_OMAP5_UEVM MACHINE_TYPE_NAME("omap5-uevm")

#define OMAP5_RAM_BASE   0x80000000ULL
#define OMAP5_PERIPHBASE 0x48240000ULL   /* A15 MPCore private: GIC at +0x1000/+0x2000 */
#define OMAP5_L4_BASE    0x40000000ULL
#define OMAP5_L4_SIZE    0x20000000ULL
#define OMAP5_NUM_IRQ    192

typedef struct Omap5Regs {
    MemoryRegion iomem;
    uint8_t *store;
    uint8_t *seen;
    bool trace;
} Omap5Regs;

/* OMAP5_SETBITS="addr=mask,addr=mask" / OMAP5_CLRBITS: force bits in reads */
static uint32_t omap5_env_mask(const char *var, hwaddr a)
{
    const char *e = getenv(var);
    uint32_t m = 0;
    while (e && *e) {
        char *end;
        unsigned long long ea = strtoull(e, &end, 0);
        if (*end != '=') break;
        unsigned long long em = strtoull(end + 1, &end, 0);
        if (ea == a) m |= (uint32_t)em;
        e = (*end == ',') ? end + 1 : end;
        if (*end != ',' && *end) break;
    }
    return m;
}

static uint32_t omap5_get32(Omap5Regs *r, hwaddr a)
{
    uint32_t v;
    memcpy(&v, r->store + (a & ~3ULL), 4);
    return v;
}

static uint64_t omap5_regs_read(void *opaque, hwaddr off, unsigned size)
{
    Omap5Regs *r = opaque;
    hwaddr a = OMAP5_L4_BASE + off;
    uint32_t w = omap5_get32(r, off);

    /* DPLL: CM_CLKMODE_DPLL_x at N (PRCM windows), CM_IDLEST_DPLL_x at N+4 */
    if (a >= 0x4a004000 && a < 0x4a00a000 && (off & 4)) {
        uint32_t prev = omap5_get32(r, off - 4);
        if ((prev & 7) == 7) {
            w = (w & ~0x101u) | 1;         /* locked */
        } else if ((prev & 7) == 5 || (prev & 7) == 6) {
            w = (w & ~0x101u) | 0x100;     /* bypass */
        }
    }
    /* OMAP IP convention: SYSCONFIG@0x10 (SOFTRESET=bit1 self-clears),
     * SYSSTATUS@0x14 (RESETDONE=bit0) */
    if (a >= 0x48000000 && a < 0x4b000000) {
        if ((a & 0xff) == 0x10) {
            w &= ~2u;
        } else if ((a & 0xff) == 0x14) {
            w |= 1;
        }
    }
    /* PRM_VC_VAL_BYPASS: VALID bit (24) self-clears when the command is done */
    if (a == 0x4ae07ca0) {
        w &= ~(1u << 24);
    }
    w |= omap5_env_mask("OMAP5_SETBITS", a & ~3ULL);
    w &= ~omap5_env_mask("OMAP5_CLRBITS", a & ~3ULL);
    if (r->trace && !r->seen[(off & ~3ULL) >> 2]) {
        r->seen[(off & ~3ULL) >> 2] = 1;
        fprintf(stderr, "OMAP5 R%u 0x%08" PRIx64 " -> 0x%08x\n", size, a, w);
    }
    return (w >> ((off & 3) * 8)) & ((size == 4) ? 0xffffffffu : ((1u << (size * 8)) - 1));
}

static void omap5_regs_write(void *opaque, hwaddr off, uint64_t val,
                             unsigned size)
{
    Omap5Regs *r = opaque;
    if (r->trace) {
        fprintf(stderr, "OMAP5 W%u 0x%08" PRIx64 " <- 0x%08" PRIx64 "\n", size,
                (uint64_t)(OMAP5_L4_BASE + off), val);
    }
    memcpy(r->store + off, &val, size);
}

static const MemoryRegionOps omap5_regs_ops = {
    .read = omap5_regs_read,
    .write = omap5_regs_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 1,
    .valid.max_access_size = 4,
};

/* ---- GL bridge: guest GLES stub <-> host renderer over a unix socket ---- */
#define GLB_REGS   0x7ff00000ULL
#define GLB_BUF    0x7e000000ULL
#define GLB_BUFSZ  0x01000000
#define GLB_HALF   0x00800000
typedef struct GlBridge {
    MemoryRegion mmio, buf;
    uint8_t *ptr;
    int fd;
    uint32_t replylen;
} GlBridge;

static int glb_rw(int fd, void *b, size_t n, bool wr)
{
    uint8_t *p = b;
    while (n) {
        ssize_t r = wr ? send(fd, p, n, 0) : recv(fd, p, n, 0);
        if (r <= 0) {
            return -1;
        }
        p += r;
        n -= r;
    }
    return 0;
}

static int glb_connect(void)
{
    const char *path = getenv("OMAP5_GLSOCK");
    struct sockaddr_un sa = { .sun_family = AF_UNIX };
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }
    snprintf(sa.sun_path, sizeof(sa.sun_path), "%s", path ? path : "/tmp/glbridge.sock");
    if (connect(fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static void glb_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
    GlBridge *g = opaque;
    uint32_t len = val, rl = 0;
    if (off != 0) {
        return;
    }
    g->replylen = 0;
    if (g->fd < 0) {
        g->fd = glb_connect();
    }
    if (g->fd < 0 || len > GLB_HALF) {
        return;
    }
    if (glb_rw(g->fd, &len, 4, true) || glb_rw(g->fd, g->ptr, len, true) ||
        glb_rw(g->fd, &rl, 4, false) || rl > GLB_HALF ||
        glb_rw(g->fd, g->ptr + GLB_HALF, rl, false)) {
        close(g->fd);
        g->fd = -1;
        return;
    }
    g->replylen = rl;
}

static uint64_t glb_read(void *opaque, hwaddr off, unsigned size)
{
    GlBridge *g = opaque;
    switch (off) {
    case 8: return g->replylen;
    case 12: return g->fd >= 0;
    }
    return 0;
}

static const MemoryRegionOps glb_ops = {
    .read = glb_read, .write = glb_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 4, .valid.max_access_size = 4,
};

static void glb_init(MemoryRegion *sysmem)
{
    GlBridge *g = g_new0(GlBridge, 1);
    g->fd = -1;
    memory_region_init_io(&g->mmio, NULL, &glb_ops, g, "omap5.glb.regs", 0x1000);
    memory_region_add_subregion(sysmem, GLB_REGS, &g->mmio);
    memory_region_init_ram(&g->buf, NULL, "omap5.glb.buf", GLB_BUFSZ, &error_fatal);
    memory_region_add_subregion(sysmem, GLB_BUF, &g->buf);
    g->ptr = memory_region_get_ram_ptr(&g->buf);
}

static void omap5_uevm_init(MachineState *machine)
{
    MemoryRegion *sysmem = get_system_memory();
    MemoryRegion *ram = g_new(MemoryRegion, 1);
    Omap5Regs *regs = g_new0(Omap5Regs, 1);
    DeviceState *gic;
    SysBusDevice *gicbus;
    qemu_irq pic[OMAP5_NUM_IRQ];
    int n, ncpu = machine->smp.cpus;

    for (n = 0; n < ncpu; n++) {
        Object *cpuobj = object_new(machine->cpu_type);
        object_property_set_int(cpuobj, "reset-cbar", OMAP5_PERIPHBASE,
                                &error_abort);
        qdev_realize(DEVICE(cpuobj), NULL, &error_fatal);
    }

    gic = qdev_new(TYPE_A15MPCORE_PRIV);
    qdev_prop_set_uint32(gic, "num-cpu", ncpu);
    qdev_prop_set_uint32(gic, "num-irq", OMAP5_NUM_IRQ + 32);
    gicbus = SYS_BUS_DEVICE(gic);
    sysbus_realize_and_unref(gicbus, &error_fatal);
    sysbus_mmio_map(gicbus, 0, OMAP5_PERIPHBASE);
    for (n = 0; n < OMAP5_NUM_IRQ; n++) {
        pic[n] = qdev_get_gpio_in(gic, n);
    }
    for (n = 0; n < ncpu; n++) {
        DeviceState *cpudev = DEVICE(qemu_get_cpu(n));
        sysbus_connect_irq(gicbus, n, qdev_get_gpio_in(cpudev, ARM_CPU_IRQ));
        sysbus_connect_irq(gicbus, n + ncpu, qdev_get_gpio_in(cpudev, ARM_CPU_FIQ));
        sysbus_connect_irq(gicbus, n + 2 * ncpu, qdev_get_gpio_in(cpudev, ARM_CPU_VIRQ));
        sysbus_connect_irq(gicbus, n + 3 * ncpu, qdev_get_gpio_in(cpudev, ARM_CPU_VFIQ));
    }

    memory_region_add_subregion(sysmem, OMAP5_RAM_BASE, machine->ram);
    (void)ram;

    /* catch-all register file over the L4 space */
    regs->store = g_malloc0(OMAP5_L4_SIZE);
    regs->seen = g_malloc0(OMAP5_L4_SIZE >> 2);
    {   /* register reset values the startup insists on */
        static const struct { hwaddr a; uint32_t v; } rst[] = {
            { 0x4ae06110, 4 },   /* CM_SYS_CLKSEL: 19.2 MHz */
            { 0x4a00416c, 0x3200 }, /* DPLL_USB CLKSEL: M=50 N=0 */
            { 0x4a004170, 1 },      /* DPLL_USB DIV_M2 */
        };
        for (n = 0; n < ARRAY_SIZE(rst); n++) {
            memcpy(regs->store + (rst[n].a - OMAP5_L4_BASE), &rst[n].v, 4);
        }
    }
    regs->trace = getenv("OMAP5_TRACE") != NULL;
    memory_region_init_io(&regs->iomem, NULL, &omap5_regs_ops, regs,
                          "omap5.l4", OMAP5_L4_SIZE);
    memory_region_add_subregion_overlap(sysmem, OMAP5_L4_BASE, &regs->iomem, -1);

    /* "eMMC" RAM disk window: host-prepared disk images get loaded here */
    {
        /* sda (OS, QNX4): 0x60000000-0x7e000000; sdb (HMI data, QNX6): 0x01000000-0x40000000 */
        MemoryRegion *disk = g_new(MemoryRegion, 1);
        memory_region_init_ram(disk, NULL, "omap5.sda", 0x1e000000, &error_fatal);
        memory_region_add_subregion(sysmem, 0x60000000, disk);
        MemoryRegion *disk2 = g_new(MemoryRegion, 1);
        memory_region_init_ram(disk2, NULL, "omap5.sdb", 0x3f000000, &error_fatal);
        memory_region_add_subregion(sysmem, 0x01000000, disk2);
        /* Shim disk below sda; 0x7e000000 onward belongs to the GLES bridge. */
        MemoryRegion *disk3 = g_new(MemoryRegion, 1);
        memory_region_init_ram(disk3, NULL, "omap5.shim", 0x02000000, &error_fatal);
        memory_region_add_subregion(sysmem, 0x5e000000, disk3);
    }

    glb_init(sysmem);

    /* UART3 (console) 16550, regshift 2, SPI 106 */
    serial_mm_init(sysmem, 0x48020000, 2, pic[74], 48000000 / 16,
                   serial_hd(0), DEVICE_LITTLE_ENDIAN);
    serial_mm_init(sysmem, 0x4806c000, 2, pic[73], 48000000 / 16,
                   serial_hd(1), DEVICE_LITTLE_ENDIAN);
    /* UART1 (SPI 72) and UART4 (SPI 70): IDEmu shell / data channels */
    serial_mm_init(sysmem, 0x4806a000, 2, pic[72], 48000000 / 16,
                   serial_hd(2), DEVICE_LITTLE_ENDIAN);
    serial_mm_init(sysmem, 0x4806e000, 2, pic[70], 48000000 / 16,
                   serial_hd(3), DEVICE_LITTLE_ENDIAN);
}

static void omap5_uevm_class_init(ObjectClass *oc, const void *data)
{
    static const char * const valid_cpu_types[] = {
        ARM_CPU_TYPE_NAME("cortex-a15"), NULL
    };
    MachineClass *mc = MACHINE_CLASS(oc);

    mc->desc = "TI OMAP5432 uEVM stub (for QNX startup experiments)";
    mc->init = omap5_uevm_init;
    mc->valid_cpu_types = valid_cpu_types;
    mc->default_cpu_type = ARM_CPU_TYPE_NAME("cortex-a15");
    mc->default_ram_size = 1 * GiB;
    mc->default_ram_id = "omap5.ram";
    mc->max_cpus = 2;
    mc->default_cpus = 1;
}

static const TypeInfo omap5_uevm_info = {
    .name = TYPE_OMAP5_UEVM,
    .parent = TYPE_MACHINE,
    .class_init = omap5_uevm_class_init,
    .interfaces = arm_machine_interfaces,
};

static void omap5_uevm_register(void)
{
    type_register_static(&omap5_uevm_info);
}
type_init(omap5_uevm_register)

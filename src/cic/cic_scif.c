/*
 * IDEmu CIC: SCIF do SH7785 (uma instância por canal).
 *
 * Diferente do sh_serial do QEMU (feito para o Linux: IRQ de TX por nível enquanto TIE=1), aqui as flags
 * TDFE/TEND/RDF/DR seguem o manual: TDFE só é limpo por software se, depois de gravar no FIFO, restar mais
 * que o gatilho (TTRG), e volta quando o FIFO "esvazia" (temporizador por baud). Evita a tempestade de
 * interrupções do devc-sersci do QNX.
 */
#include "qemu/osdep.h"
#include "qemu/log.h"
#include "qemu/timer.h"
#include "qapi/error.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/qdev-properties-system.h"
#include "chardev/char-fe.h"
#include "qom/object.h"

#define TYPE_CIC_SCIF "cic-scif"
OBJECT_DECLARE_SIMPLE_TYPE(CicScif, CIC_SCIF)

#define SCSCR_TIE  (1 << 7)
#define SCSCR_RIE  (1 << 6)
#define SCSCR_TE   (1 << 5)
#define SCSCR_RE   (1 << 4)
#define SCSCR_REIE (1 << 3)

#define FSR_ER   (1 << 7)
#define FSR_TEND (1 << 6)
#define FSR_TDFE (1 << 5)
#define FSR_BRK  (1 << 4)
#define FSR_RDF  (1 << 1)
#define FSR_DR   (1 << 0)

#define RXFIFO 16

struct CicScif {
    SysBusDevice parent;
    MemoryRegion iomem;
    CharFrontend chr;
    qemu_irq eri, rxi, bri, txi;
    uint16_t smr, scr, fsr, fcr, sptr, lsr, rer;
    uint8_t brr;
    uint8_t rx[RXFIFO];
    int rxh, rxt, rxc;
    int txc;                 /* bytes "no FIFO de TX" */
    QEMUTimer *txtimer;
    QEMUTimer *rxtimer;
    uint64_t etu;            /* ns por caractere (10 bits), usado na recepção */
    uint64_t tx_etu;         /* ns por caractere na transmissão: quase instantânea (o kernel espera ativamente cada caractere) */
};

static int ttrg(CicScif *s)
{
    static const int t[4] = { 8, 4, 2, 0 };
    return t[(s->fcr >> 4) & 3];
}

static int rtrg(CicScif *s)
{
    static const int t[4] = { 1, 4, 8, 14 };
    return t[(s->fcr >> 6) & 3];
}

static void cic_scif_irq(CicScif *s)
{
    qemu_set_irq(s->txi, (s->scr & SCSCR_TIE) && (s->fsr & FSR_TDFE));
    qemu_set_irq(s->rxi, (s->scr & SCSCR_RIE) && (s->fsr & (FSR_RDF | FSR_DR)));
    qemu_set_irq(s->eri, (s->scr & SCSCR_REIE) && (s->fsr & FSR_ER));
    qemu_set_irq(s->bri, (s->scr & SCSCR_REIE) && (s->fsr & FSR_BRK));
}

static void cic_scif_tx_tick(void *opaque)
{
    CicScif *s = opaque;
    if (s->txc > 0) {
        s->txc--;
    }
    if (s->txc <= ttrg(s)) {
        s->fsr |= FSR_TDFE;
    }
    if (s->txc == 0) {
        s->fsr |= FSR_TEND;
    } else {
        timer_mod(s->txtimer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + s->tx_etu);
    }
    cic_scif_irq(s);
}

static void cic_scif_rx_timeout(void *opaque)
{
    CicScif *s = opaque;
    if (s->rxc > 0 && s->rxc < rtrg(s)) {
        s->fsr |= FSR_DR;
    }
    cic_scif_irq(s);
}

static uint64_t cic_scif_read(void *opaque, hwaddr off, unsigned size)
{
    CicScif *s = opaque;
    uint32_t v = 0;
    switch (off) {
    case 0x00: v = s->smr; break;
    case 0x04: v = s->brr; break;
    case 0x08: v = s->scr; break;
    case 0x10: v = s->fsr; break;
    case 0x14:
        if (s->rxc > 0) {
            v = s->rx[s->rxt];
            s->rxt = (s->rxt + 1) % RXFIFO;
            s->rxc--;
        }
        break;
    case 0x18: v = s->fcr; break;
    /* SH7785: FIFOs com contadores separados (o devc-sersci lê a contagem de RX em +0x20) */
    case 0x1c: v = s->txc & 0x1f; break;                /* SCTFDR */
    case 0x20: v = s->rxc & 0x1f; break;                /* SCRFDR */
    case 0x24: v = s->sptr; break;                      /* SCSPTR */
    case 0x28: v = s->lsr; break;                       /* SCLSR (bit 0 = ORER) */
    default:
        qemu_log_mask(LOG_UNIMP, "cic-scif: leitura %02x\n", (unsigned)off);
    }
    return v;
}

static void cic_scif_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
    CicScif *s = opaque;
    uint8_t ch;

    switch (off) {
    case 0x00: s->smr = val; break;
    case 0x04: s->brr = val; break;
    case 0x08:
        s->scr = val;
        break;
    case 0x0c:
        ch = val;
        if (qemu_chr_fe_backend_connected(&s->chr)) {
            qemu_chr_fe_write_all(&s->chr, &ch, 1);
        }
        s->txc++;
        s->fsr &= ~FSR_TEND;
        timer_mod(s->txtimer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + s->tx_etu);
        break;
    case 0x10: {
        /* bit a bit: escrever 0 limpa (se a condição não valer mais) */
        uint16_t keep = val | ~(FSR_ER | FSR_TEND | FSR_TDFE | FSR_BRK | FSR_RDF | FSR_DR);
        uint16_t cleared = s->fsr & ~keep;
        s->fsr &= keep;        /* escrever 0 limpa o evento, mas ele permanece se a condição ainda vale (como no hardware) */
        if ((cleared & FSR_RDF) && s->rxc >= rtrg(s)) {
            s->fsr |= FSR_RDF;
        }
        if ((cleared & FSR_DR) && s->rxc > 0 && s->rxc < rtrg(s)) {
            s->fsr |= FSR_DR;
        }
        if ((cleared & FSR_TDFE) && s->txc <= ttrg(s)) {
            s->fsr |= FSR_TDFE;
        }
        if ((cleared & FSR_TEND) && s->txc == 0) {
            s->fsr |= FSR_TEND;
        }
        break;
    }
    case 0x18:
        s->fcr = val;
        if (val & 2) {                      /* RFRST */
            s->rxh = s->rxt = s->rxc = 0;
            s->fsr &= ~(FSR_RDF | FSR_DR);
        }
        if (val & 4) {                      /* TFRST */
            s->txc = 0;
            s->fsr |= FSR_TDFE | FSR_TEND;
        }
        break;
    case 0x1c: case 0x20: break;                        /* contadores: somente leitura */
    case 0x24: s->sptr = val; break;
    case 0x28: s->lsr = val; break;
    default:
        qemu_log_mask(LOG_UNIMP, "cic-scif: escrita %02x = %x\n", (unsigned)off, (unsigned)val);
    }
    cic_scif_irq(s);
}

static const MemoryRegionOps cic_scif_ops = {
    .read = cic_scif_read, .write = cic_scif_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

static int cic_scif_can_rx(void *opaque)
{
    CicScif *s = opaque;
    return (s->scr & SCSCR_RE) ? RXFIFO - s->rxc : 0;
}

static void cic_scif_rx(void *opaque, const uint8_t *buf, int size)
{
    CicScif *s = opaque;
    for (int i = 0; i < size; i++) {
        if (s->rxc < RXFIFO) {
            s->rx[s->rxh] = buf[i];
            s->rxh = (s->rxh + 1) % RXFIFO;
            s->rxc++;
        }
    }
    if (s->rxc >= rtrg(s)) {
        s->fsr |= FSR_RDF;
    } else {
        timer_mod(s->rxtimer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 15 * s->etu / 10);
    }
    cic_scif_irq(s);
}

static void cic_scif_event(void *opaque, QEMUChrEvent ev)
{
    CicScif *s = opaque;
    if (ev == CHR_EVENT_BREAK) {
        s->fsr |= FSR_BRK;
        cic_scif_irq(s);
    }
}

static void cic_scif_reset(DeviceState *dev)
{
    CicScif *s = CIC_SCIF(dev);
    s->smr = 0; s->brr = 0xff; s->scr = 0; s->fsr = FSR_TEND | FSR_TDFE; s->fcr = 0;
    s->sptr = 0; s->lsr = 0; s->rer = 0;
    s->rxh = s->rxt = s->rxc = 0; s->txc = 0;
}

static void cic_scif_realize(DeviceState *d, Error **errp)
{
    CicScif *s = CIC_SCIF(d);
    memory_region_init_io(&s->iomem, OBJECT(d), &cic_scif_ops, s, "cic-scif", 0x100);
    sysbus_init_mmio(SYS_BUS_DEVICE(d), &s->iomem);
    qdev_init_gpio_out_named(d, &s->eri, "eri", 1);
    qdev_init_gpio_out_named(d, &s->rxi, "rxi", 1);
    qdev_init_gpio_out_named(d, &s->bri, "bri", 1);
    qdev_init_gpio_out_named(d, &s->txi, "txi", 1);
    if (qemu_chr_fe_backend_connected(&s->chr)) {
        qemu_chr_fe_set_handlers(&s->chr, cic_scif_can_rx, cic_scif_rx, cic_scif_event, NULL, s, NULL, true);
    }
    s->txtimer = timer_new_ns(QEMU_CLOCK_VIRTUAL, cic_scif_tx_tick, s);
    s->rxtimer = timer_new_ns(QEMU_CLOCK_VIRTUAL, cic_scif_rx_timeout, s);
    s->etu = NANOSECONDS_PER_SECOND / 5760;      /* 57600 baud, 10 bits por caractere */
    s->tx_etu = getenv("CIC_SCIF_SLOW") ? s->etu : 1000;   /* 1 µs por caractere (CIC_SCIF_SLOW volta aos 57600 baud) */
}

static const Property cic_scif_props[] = {
    DEFINE_PROP_CHR("chardev", CicScif, chr),
};

static void cic_scif_class_init(ObjectClass *oc, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    device_class_set_props(dc, cic_scif_props);
    dc->realize = cic_scif_realize;
    device_class_set_legacy_reset(dc, cic_scif_reset);
    dc->user_creatable = false;
}

static const TypeInfo cic_scif_types[] = {
    { .name = TYPE_CIC_SCIF, .parent = TYPE_SYS_BUS_DEVICE, .instance_size = sizeof(CicScif),
      .class_init = cic_scif_class_init },
};

DEFINE_TYPES(cic_scif_types)

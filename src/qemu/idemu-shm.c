/*
 * IDEmu: memória compartilhada guest <-> processo do host (no lugar do ivshmem, que só compila no Linux).
 *
 * Dispositivo PCI com um BAR de memória (prefetchable, 64 bits) apoiado num objeto POSIX shm_open() que o processo
 * glhost7 do IDEmu também mapeia. O convidado mapeia o BAR pelo sysfs (resource0), sem driver, e usa como anel
 * de comandos GL (iDrive 7).
 *
 *   -device idemu-shm,shm-name=/idemu-gl-123,size=128M
 *
 * Licença GPL v2 ou posterior, como o resto do QEMU.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "hw/pci/pci_device.h"
#include "hw/core/qdev-properties.h"
#include "system/memory.h"
#include "qemu/module.h"
#include "qemu/units.h"
#include "migration/vmstate.h"
#include "qom/object.h"

#define TYPE_IDEMU_SHM "idemu-shm"
OBJECT_DECLARE_SIMPLE_TYPE(IdemuShm, IDEMU_SHM)

struct IdemuShm {
    PCIDevice parent_obj;
    MemoryRegion bar;
    char *shm_name;
    uint64_t size;
    int fd;
};

static void idemu_shm_realize(PCIDevice *dev, Error **errp)
{
    IdemuShm *s = IDEMU_SHM(dev);
    int fd;

    if (!s->shm_name || s->shm_name[0] != '/') {
        error_setg(errp, "idemu-shm: informe shm-name=/nome");
        return;
    }
    if (s->size < 4096 || (s->size & (s->size - 1))) {
        error_setg(errp, "idemu-shm: size deve ser potência de 2 (>= 4K)");
        return;
    }
    fd = shm_open(s->shm_name, O_CREAT | O_RDWR, 0600);
    if (fd < 0) {
        error_setg_errno(errp, errno, "idemu-shm: shm_open(%s)", s->shm_name);
        return;
    }
    if (ftruncate(fd, s->size) < 0) {
        error_setg_errno(errp, errno, "idemu-shm: ftruncate");
        close(fd);
        return;
    }
    if (!memory_region_init_ram_from_fd(&s->bar, OBJECT(dev), "idemu-shm", s->size,
                                        RAM_SHARED, fd, 0, errp)) {
        close(fd);
        return;
    }
    s->fd = fd;
    vmstate_register_ram(&s->bar, DEVICE(dev));      /* sem isto o bloco de RAM não tem nome e não entra no snapshot */
    pci_register_bar(dev, 0, PCI_BASE_ADDRESS_SPACE_MEMORY |
                     PCI_BASE_ADDRESS_MEM_PREFETCH | PCI_BASE_ADDRESS_MEM_TYPE_64, &s->bar);
}

static void idemu_shm_exit(PCIDevice *dev)
{
    IdemuShm *s = IDEMU_SHM(dev);
    vmstate_unregister_ram(&s->bar, DEVICE(dev));
    if (s->shm_name) {
        shm_unlink(s->shm_name);
    }
}

static const VMStateDescription vmstate_idemu_shm = {
    .name = TYPE_IDEMU_SHM,
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_PCI_DEVICE(parent_obj, IdemuShm),
        VMSTATE_END_OF_LIST()
    }
};

static const Property idemu_shm_properties[] = {
    DEFINE_PROP_STRING("shm-name", IdemuShm, shm_name),
    DEFINE_PROP_SIZE("size", IdemuShm, size, 64 * MiB),
};

static void idemu_shm_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    PCIDeviceClass *k = PCI_DEVICE_CLASS(klass);

    k->realize = idemu_shm_realize;
    k->exit = idemu_shm_exit;
    k->vendor_id = PCI_VENDOR_ID_REDHAT;
    k->device_id = 0x1d3a;
    k->revision = 1;
    k->class_id = PCI_CLASS_MEMORY_RAM;
    dc->vmsd = &vmstate_idemu_shm;          /* o estado do PCI (BARs) entra nos snapshots; o conteúdo do BAR vai como RAM */
    device_class_set_props(dc, idemu_shm_properties);
    set_bit(DEVICE_CATEGORY_MISC, dc->categories);
    dc->desc = "IDEmu shared memory";
}

static const TypeInfo idemu_shm_info = {
    .name = TYPE_IDEMU_SHM,
    .parent = TYPE_PCI_DEVICE,
    .instance_size = sizeof(IdemuShm),
    .class_init = idemu_shm_class_init,
    .interfaces = (const InterfaceInfo[]) {
        { INTERFACE_CONVENTIONAL_PCI_DEVICE },
        { },
    },
};

static void idemu_shm_register_types(void)
{
    type_register_static(&idemu_shm_info);
}

type_init(idemu_shm_register_types)

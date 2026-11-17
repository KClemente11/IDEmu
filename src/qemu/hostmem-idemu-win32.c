/* IDEmu MGU22 shared guest RAM. GPL-2.0-or-later, like QEMU.
 * Python creates and initializes the named mapping before QEMU opens it.
 * This is a HostMemoryBackend, not the iDrive 7 PCI BAR device.
 */
#include "qemu/osdep.h"
#include "system/hostmem.h"
#include "qapi/error.h"
#include "qom/object.h"
#include "qemu/module.h"

#define TYPE_MEMORY_BACKEND_IDEMU "memory-backend-idemu"
OBJECT_DECLARE_SIMPLE_TYPE(HostMemoryBackendIdemu, MEMORY_BACKEND_IDEMU)

struct HostMemoryBackendIdemu {
    HostMemoryBackend parent_obj;
    char *mapping_name;
    HANDLE mapping;
    void *view;
};

static bool idemu_alloc(HostMemoryBackend *backend, Error **errp)
{
    HostMemoryBackendIdemu *s = MEMORY_BACKEND_IDEMU(backend);
    g_autofree char *name = host_memory_backend_get_name(backend);
    if (!s->mapping_name || !*s->mapping_name || !backend->size || !backend->share) {
        error_setg(errp, "memory-backend-idemu needs mapping-name, size and share=on");
        return false;
    }
    s->mapping = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, s->mapping_name);
    if (!s->mapping) {
        error_setg_win32(errp, GetLastError(), "OpenFileMapping(%s)", s->mapping_name);
        return false;
    }
    s->view = MapViewOfFile(s->mapping, FILE_MAP_ALL_ACCESS, 0, 0, backend->size);
    if (!s->view) {
        error_setg_win32(errp, GetLastError(), "MapViewOfFile(%s)", s->mapping_name);
        CloseHandle(s->mapping);
        s->mapping = NULL;
        return false;
    }
    memory_region_init_ram_ptr(&backend->mr, OBJECT(backend), name, backend->size, s->view);
    return true;
}

static void idemu_init(Object *obj)
{
    MEMORY_BACKEND(obj)->share = true;
}

static void idemu_finalize(Object *obj)
{
    HostMemoryBackendIdemu *s = MEMORY_BACKEND_IDEMU(obj);
    if (s->view) UnmapViewOfFile(s->view);
    if (s->mapping) CloseHandle(s->mapping);
    g_free(s->mapping_name);
}

static void idemu_set_name(Object *obj, const char *value, Error **errp)
{
    HostMemoryBackendIdemu *s = MEMORY_BACKEND_IDEMU(obj);
    if (host_memory_backend_mr_inited(MEMORY_BACKEND(obj))) {
        error_setg(errp, "mapping-name cannot change after allocation");
        return;
    }
    g_free(s->mapping_name);
    s->mapping_name = g_strdup(value);
}

static char *idemu_get_name(Object *obj, Error **errp)
{
    return g_strdup(MEMORY_BACKEND_IDEMU(obj)->mapping_name);
}

static void idemu_class_init(ObjectClass *oc, const void *data)
{
    MEMORY_BACKEND_CLASS(oc)->alloc = idemu_alloc;
    object_class_property_add_str(oc, "mapping-name", idemu_get_name, idemu_set_name);
}

static const TypeInfo idemu_info = {
    .name = TYPE_MEMORY_BACKEND_IDEMU,
    .parent = TYPE_MEMORY_BACKEND,
    .instance_size = sizeof(HostMemoryBackendIdemu),
    .instance_init = idemu_init,
    .instance_finalize = idemu_finalize,
    .class_init = idemu_class_init,
};

static void idemu_register(void) { type_register_static(&idemu_info); }
type_init(idemu_register);

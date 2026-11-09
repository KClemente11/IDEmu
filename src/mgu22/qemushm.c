// Carregada no QEMU (DYLD_INSERT_LIBRARIES): faz o memory-backend-shm usar o objeto POSIX que run.py criou,
// para o mguhost enxergar a RAM do guest sem passar por arquivo.
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
static int my_shm_open(const char *name, int flags, ...) {
  va_list ap; va_start(ap, flags); int mode = va_arg(ap, int); va_end(ap);
  const char *n = getenv("IDEMU_SHM_NAME");
  if (n) return shm_open(n, O_RDWR);
  return shm_open(name, flags, mode);
}
static int my_shm_unlink(const char *name) { if (getenv("IDEMU_SHM_NAME")) return 0; return shm_unlink(name); }
static int my_ftruncate(int fd, off_t len) {
  int r = ftruncate(fd, len);
  if (r && errno == EINVAL) { struct stat st; if (!fstat(fd, &st) && st.st_size == len) return 0; errno = EINVAL; }
  return r;
}
#define I(a, b) __attribute__((used, section("__DATA,__interpose"))) static struct { const void *n, *o; } in_##b = { a, b };
I(my_shm_open, shm_open) I(my_shm_unlink, shm_unlink) I(my_ftruncate, ftruncate)

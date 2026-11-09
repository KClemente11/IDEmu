/* Win32 plumbing for the native renderer. Wire messages match the Unix host. */
#ifndef IDEMU_WIN32_HOST_H
#define IDEMU_WIN32_HOST_H

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

static SOCKET bind_loopback(int type, unsigned *port)
{
  SOCKET fd = socket(AF_INET, type, 0);
  struct sockaddr_in addr = {0};
  int len = sizeof(addr);
  BOOL exclusive = TRUE;
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (fd == INVALID_SOCKET) return fd;
  if (setsockopt(fd, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char *)&exclusive, sizeof(exclusive)) ||
      bind(fd, (struct sockaddr *)&addr, sizeof(addr)) ||
      getsockname(fd, (struct sockaddr *)&addr, &len)) {
    closesocket(fd);
    return INVALID_SOCKET;
  }
  *port = ntohs(addr.sin_port);
  return fd;
}

static unsigned char *frame_mapping(const char *path, size_t size)
{
  HANDLE file = CreateFileA(path, GENERIC_READ | GENERIC_WRITE,
                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                            NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
  if (file == INVALID_HANDLE_VALUE) return NULL;
  HANDLE mapping = CreateFileMappingA(file, NULL, PAGE_READWRITE, 0, (DWORD)size, NULL);
  CloseHandle(file);
  if (!mapping) return NULL;
  unsigned char *data = MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, size);
  CloseHandle(mapping);
  return data;
}

#endif

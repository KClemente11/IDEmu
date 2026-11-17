/* Native plumbing for MGU22. All protocol types are defined separately in chan.h. */
#ifndef IDEMU_WIN32_HOST8_H
#define IDEMU_WIN32_HOST8_H
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <mmsystem.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>

__declspec(dllexport) DWORD NvOptimusEnablement = 1;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;
static _Thread_local unsigned win8_last_op;
static LONG WINAPI win8_crash(EXCEPTION_POINTERS *exception) {
  char line[256]; DWORD written;
  int n = snprintf(line, sizeof line, "mguhost: crash %08lx at %p, thread %lu, guest op %u\n",
                   exception->ExceptionRecord->ExceptionCode, exception->ExceptionRecord->ExceptionAddress,
                   GetCurrentThreadId(), win8_last_op);
  if (n > 0) WriteFile(GetStdHandle(STD_ERROR_HANDLE), line, (DWORD)n, &written, NULL);
  return EXCEPTION_EXECUTE_HANDLER;
}

static void *win_open_ram(const char *name, size_t size) {
  HANDLE h = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, name);
  if (!h) return NULL;
  void *p = MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, size);
  CloseHandle(h);
  return p;
}

static void *win_frame(const char *name, size_t size) {
  HANDLE f = CreateFileA(name, GENERIC_READ | GENERIC_WRITE,
                        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                        NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
  if (f == INVALID_HANDLE_VALUE) return NULL;
  HANDLE h = CreateFileMappingA(f, NULL, PAGE_READWRITE, (DWORD)((uint64_t)size >> 32), (DWORD)size, NULL);
  CloseHandle(f);
  if (!h) return NULL;
  void *p = MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, size);
  CloseHandle(h);
  return p;
}

static void *win_symbol(void *module, const char *name) { return (void *)GetProcAddress(module, name); }
static double win_now(void) {
  LARGE_INTEGER f, t; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&t);
  return (double)t.QuadPart / (double)f.QuadPart;
}
/* Avoid a system-tick sleep for each idle ring read. */
static void win_usleep(unsigned us) {
  if (us < 1000) SwitchToThread(); else Sleep((us + 999) / 1000);
}
#define usleep win_usleep
#define dlsym win_symbol
#endif

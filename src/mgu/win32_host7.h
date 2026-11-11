/* Win32 plumbing for glhost7 (iDrive 7 renderer). The macOS build does not include this file.
 *
 *   OpenGL 4.1 core context through WGL + GLEW, on a hidden window (macOS: CGL, off screen)
 *   the command ring: the named file mapping the QEMU device idemu-shm creates (macOS: shm_open)
 *   frame.rgba: a file mapping the app reads (macOS: mmap)
 *
 * Built by tools/qemu/build-windows-native.sh in MSYS2 UCRT64.
 */
#ifndef IDEMU_WIN32_HOST7_H
#define IDEMU_WIN32_HOST7_H

#include <GL/glew.h>
#include <GL/wglew.h>
#include <windows.h>
#include <mmsystem.h>
#include <direct.h>
#include <immintrin.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
/* Laptops with two GPUs: ask for the fast one. */
__declspec(dllexport) DWORD NvOptimusEnablement = 1;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;

/* After the headers above, which declare the one-argument mkdir() and the deprecated usleep(). */
#define mkdir(path, mode) _mkdir(path)
#define usleep(us) Sleep(((us) + 999) / 1000)
#define memmem idemu_memmem

static void *idemu_memmem(const void *hay, size_t hlen, const void *needle, size_t nlen)
{
  const char *h = hay;
  if (!nlen) return (void *)hay;
  for (; hlen >= nlen; h++, hlen--) {
    if (*h == *(const char *)needle && !memcmp(h, needle, nlen)) return (void *)h;
  }
  return NULL;
}

static unsigned long long win_nsec(void)
{
  static LARGE_INTEGER freq;
  LARGE_INTEGER now;
  if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
  QueryPerformanceCounter(&now);
  return (unsigned long long)(now.QuadPart / freq.QuadPart) * 1000000000ull +
         (unsigned long long)(now.QuadPart % freq.QuadPart) * 1000000000ull / freq.QuadPart;
}

/* Diagnostics. A crash would otherwise end the renderer without a word, so it says what failed and during which
 * guest command, and the first commands of a run are listed. Written straight to the log handle, not through stdio. */
static volatile unsigned win_last_op = ~0u, win_last_fn = ~0u, win_last_len;
static volatile unsigned long long win_ops;
static volatile LONG win_trace_left = 80, win_reports_left = 6;

static void win_log(const char *fmt, ...)
{
  char line[512];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(line, sizeof line, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  if (n > (int)sizeof line - 1) n = sizeof line - 1;
  DWORD done;
  WriteFile(GetStdHandle(STD_ERROR_HANDLE), line, (DWORD)n, &done, NULL);
}
#define WIN_TRACE(...) do { if (InterlockedDecrement(&win_trace_left) >= 0) win_log(__VA_ARGS__); } while (0)

static void win_report(const char *what, EXCEPTION_POINTERS *e)
{
  const EXCEPTION_RECORD *r = e->ExceptionRecord;
  HMODULE module = NULL;
  char name[MAX_PATH] = "?", where[MAX_PATH + 64] = "", access[96] = "";
  int found = r->ExceptionAddress && GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                                      (LPCSTR)r->ExceptionAddress, &module) && module;
  if (found) {
    GetModuleFileNameA(module, name, sizeof name);
    snprintf(where, sizeof where, " = %s+0x%llx", name, (unsigned long long)((const char *)r->ExceptionAddress - (const char *)module));
  }
  if (r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters >= 2) {
    snprintf(access, sizeof access, " (%s address %p)", r->ExceptionInformation[0] == 1 ? "writing" : r->ExceptionInformation[0] == 8 ? "executing" : "reading",
             (void *)r->ExceptionInformation[1]);
  }
  win_log("glhost7: %s: exception %08lx at %p%s%s; thread %lu; guest command %llu: op %d, %u bytes, function %d\n", what,
          (unsigned long)r->ExceptionCode, r->ExceptionAddress, where, access, (unsigned long)GetCurrentThreadId(),
          win_ops, (int)win_last_op, win_last_len, (int)win_last_fn);
}

static LONG WINAPI win_crash(EXCEPTION_POINTERS *e)
{
  win_report("crash", e);
  return EXCEPTION_EXECUTE_HANDLER;
}

/* Runs before any other handler, so it also sees a fault that something else (the C runtime, the graphics driver)
 * would swallow. Only hardware-style errors are reported; the search for a handler goes on. */
static LONG CALLBACK win_first_chance(EXCEPTION_POINTERS *e)
{
  if ((e->ExceptionRecord->ExceptionCode & 0xF0000000u) == 0xC0000000u && InterlockedDecrement(&win_reports_left) >= 0) {
    win_report("fault", e);
  }
  return EXCEPTION_CONTINUE_SEARCH;
}

static void win_at_exit(void) { win_log("glhost7: exit() after %llu guest commands\n", win_ops); }

/* Wait for the guest without the 1 ms (or coarser) floor of Sleep(): spin, then give up the time slice, then sleep. */
static void win_idle(unsigned n)
{
  if (n < 2000) { _mm_pause(); return; }
  if (n < 20000) { SwitchToThread(); return; }
  Sleep(1);
}

/* The ring QEMU created ("-device idemu-shm,shm-name=/name"): same name without the leading slash. */
static void *win_open_ring(const char *name, size_t size)
{
  HANDLE mapping = NULL;
  if (*name == '/') name++;
  for (int i = 0; i < 1200 && !mapping; i++) {          /* QEMU creates it while starting */
    mapping = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, name);
    if (!mapping) Sleep(100);
  }
  if (!mapping) return NULL;
  void *view = MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, size);
  CloseHandle(mapping);
  return view;
}

/* frame.rgba: shared for reading, writing and deleting so the app can map it and remove it on the next start. */
static unsigned char *win_frame_mapping(const char *path, size_t size)
{
  HANDLE file = CreateFileA(path, GENERIC_READ | GENERIC_WRITE,
                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                            NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
  if (file == INVALID_HANDLE_VALUE) return NULL;
  HANDLE mapping = CreateFileMappingA(file, NULL, PAGE_READWRITE, (DWORD)((unsigned long long)size >> 32), (DWORD)size, NULL);
  CloseHandle(file);
  if (!mapping) return NULL;
  unsigned char *data = MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, size);
  CloseHandle(mapping);
  return data;
}

/* OpenGL 4.1 core, like the macOS renderer. Returns NULL on success or what failed. */
static const char *win_init_gl(void)
{
  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
  SetUnhandledExceptionFilter(win_crash);
  AddVectoredExceptionHandler(1, win_first_chance);
  atexit(win_at_exit);
  WNDCLASSA wc;
  memset(&wc, 0, sizeof wc);
  wc.style = CS_OWNDC; wc.lpfnWndProc = DefWindowProcA; wc.hInstance = GetModuleHandleA(NULL); wc.lpszClassName = "idemu-glhost7";
  if (!RegisterClassA(&wc)) return "RegisterClass";
  HWND window = CreateWindowA(wc.lpszClassName, "glhost7", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, NULL, NULL, wc.hInstance, NULL);   /* never shown */
  if (!window) return "CreateWindow";
  HDC dc = GetDC(window);
  PIXELFORMATDESCRIPTOR pfd;
  memset(&pfd, 0, sizeof pfd);
  pfd.nSize = sizeof pfd; pfd.nVersion = 1; pfd.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
  pfd.iPixelType = PFD_TYPE_RGBA; pfd.cColorBits = 24; pfd.cDepthBits = 24; pfd.cStencilBits = 8;
  int format = ChoosePixelFormat(dc, &pfd);
  if (!format || !SetPixelFormat(dc, format, &pfd)) return "SetPixelFormat";
  HGLRC legacy = wglCreateContext(dc);                    /* needed to reach wglCreateContextAttribsARB */
  if (!legacy || !wglMakeCurrent(dc, legacy)) return "wglCreateContext";
  glewExperimental = GL_TRUE;
  if (glewInit() != GLEW_OK) return "glewInit";
  if (!WGLEW_ARB_create_context || !WGLEW_ARB_create_context_profile) return "the graphics driver has no OpenGL core profile";
  const int attribs[] = { WGL_CONTEXT_MAJOR_VERSION_ARB, 4, WGL_CONTEXT_MINOR_VERSION_ARB, 1,
                          WGL_CONTEXT_PROFILE_MASK_ARB, WGL_CONTEXT_CORE_PROFILE_BIT_ARB, 0 };
  HGLRC core = wglCreateContextAttribsARB(dc, NULL, attribs);
  if (!core) return "the graphics driver does not offer OpenGL 4.1";
  wglMakeCurrent(dc, core);
  wglDeleteContext(legacy);
  if (glewInit() != GLEW_OK) return "glewInit (core)";
  while (glGetError() != GL_NO_ERROR) { }                 /* GLEW may leave an error behind in a core profile */
  if (!GLEW_VERSION_4_1) return "OpenGL 4.1 is required";
  SetUnhandledExceptionFilter(win_crash);                 /* again: the graphics driver may have installed its own */
  timeBeginPeriod(1);
  return NULL;
}

#endif

"""Windows process lifetime helpers for the native runtime.

QEMU and the renderer run without a console window, so they do not see the terminal closing and Windows does not
stop child processes when their parent exits. These helpers put them in a kill-on-close Job Object and let the
server stop them when the console window closes.
"""
import sys
import threading

_job = None
_job_lock = threading.Lock()
_console_handler = None

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes

    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)

    class _BasicLimits(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                                                         'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    _JOB_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _CLOSE_EVENTS = (2, 5, 6)  # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT

    _kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    _kernel.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    _kernel.SetInformationJobObject.restype = wintypes.BOOL
    _kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    _HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    _kernel.SetConsoleCtrlHandler.argtypes = (_HandlerRoutine, wintypes.BOOL)
    _kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL

    def _kill_on_close_job():
        global _job
        with _job_lock:
            if _job is None:
                job = _kernel.CreateJobObjectW(None, None)
                if not job:
                    raise ctypes.WinError(ctypes.get_last_error())
                info = _ExtendedLimits()
                info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not _kernel.SetInformationJobObject(job, _JOB_EXTENDED_LIMIT_INFORMATION,
                                                       ctypes.byref(info), ctypes.sizeof(info)):
                    error = ctypes.WinError(ctypes.get_last_error())
                    _kernel.CloseHandle(job)
                    raise error
                # Deliberately never closed: Windows closes it when IDEmu exits and then ends every process in the job.
                _job = job
            return _job


def contain(process):
    """Make a child process end when this process ends, however it ends. Returns False if Windows refused."""
    if sys.platform != 'win32':
        return False
    try:
        if not _kernel.AssignProcessToJobObject(_kill_on_close_job(), int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
    except OSError as error:
        print('[idemu] could not attach child process to the IDEmu job: %s' % error, file=sys.stderr, flush=True)
        return False
    return True


def on_console_close(callback):
    """Run callback when the console window closes or the user logs off. Ctrl+C keeps Python's default handling."""
    global _console_handler
    if sys.platform != 'win32' or _console_handler is not None:
        return False

    def handler(event):
        if event not in _CLOSE_EVENTS:
            return False
        try:
            callback()
        except Exception:
            pass
        return True

    _console_handler = _HandlerRoutine(handler)  # Keep a reference so the callback is not collected.
    return bool(_kernel.SetConsoleCtrlHandler(_console_handler, True))

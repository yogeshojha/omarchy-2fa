import ctypes
import signal

_PR_SET_PDEATHSIG = 1

# dlopen after fork() is not async-signal-safe.
try:
    _libc = ctypes.CDLL("libc.so.6", use_errno=True)
except OSError:
    _libc = None


# PR_SET_PDEATHSIG fires even when the parent is killed with SIGKILL.
def die_with_parent():
    if _libc is not None:
        _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)

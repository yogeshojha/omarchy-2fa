import shutil
import subprocess
import threading

_QUIET = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


class ClipboardError(Exception):
    pass


def available():
    return shutil.which("wl-copy") is not None


# --sensitive sets the password-manager hint Omarchy's clipboard history skips.
def copy(text, wipe_after=0):
    if not available():
        raise ClipboardError("wl-copy is not installed")

    subprocess.run(
        ["wl-copy", "--sensitive", "--trim-newline"],
        input=text.encode("utf-8"),
        check=True,
        **_QUIET,
    )

    if wipe_after > 0:
        timer = threading.Timer(wipe_after, _wipe, args=(text,))
        timer.daemon = True
        timer.start()


# The user may have copied something else since.
def _wipe(expected):
    if shutil.which("wl-paste") is None:
        return
    result = subprocess.run(
        ["wl-paste", "--no-newline"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
    )
    if result.returncode != 0:
        return
    if result.stdout.decode("utf-8", "replace") != expected:
        return
    subprocess.run(["wl-copy", "--clear"], check=False, **_QUIET)

import shutil
import subprocess
import threading

from .process import die_with_parent

DEFAULT_TIMEOUT = 45

_TOOL = "zbarcam"
_ARGS = ["--nodisplay", "--quiet", "--raw", "--oneshot", "-Sdisable", "-Sqrcode.enable"]


class CameraError(Exception):
    pass


def available():
    return shutil.which(_TOOL) is not None


# zbarcam in a thread, polled through finished and outcome().
class Scanner:
    def __init__(self, device=None, timeout=DEFAULT_TIMEOUT):
        self.device = device
        self.timeout = max(1, int(timeout or DEFAULT_TIMEOUT))
        self._process = None
        self._thread = None
        self._guard = threading.Lock()
        self._payloads = None
        self._message = None
        self._cancelled = False
        self._finished = False

    @property
    def finished(self):
        with self._guard:
            return self._finished

    def outcome(self):
        with self._guard:
            return self._payloads, self._message, self._cancelled

    def start(self):
        if not available():
            raise CameraError("zbarcam is not installed")
        command = [_TOOL, *_ARGS] + ([self.device] if self.device else [])
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                preexec_fn=die_with_parent,
            )
        except OSError as error:
            raise CameraError(f"the camera could not be opened: {error}") from error
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        with self._guard:
            self._cancelled = True
        self._terminate()

    def _run(self):
        payloads = None
        message = None
        try:
            output, _ = self._process.communicate(timeout=self.timeout)
            lines = [line.strip() for line in output.decode("utf-8", "replace").splitlines() if line.strip()]
            if lines:
                payloads = lines
            else:
                message = "the camera did not see a QR code"
        except subprocess.TimeoutExpired:
            self._terminate()
            message = "the camera did not see a QR code"
        except Exception as error:
            self._terminate()
            message = str(error) or "the camera stopped unexpectedly"

        with self._guard:
            self._payloads = payloads
            self._message = message
            self._finished = True

    def _terminate(self):
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

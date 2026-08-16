import contextlib
import json
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from . import camera, capture, clipboard, migration
from .accounts import merge, summarize
from .otp import SecretError
from .vault import PassphraseError, Vault, VaultError

VAULT_MISSING = "missing"
VAULT_LOCKED = "locked"
VAULT_UNLOCKED = "unlocked"

_LINK_SCHEMES = (migration.OTPAUTH_SCHEME, migration.MIGRATION_SCHEME)


class SessionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# Holds the decrypted accounts while the vault is unlocked.
class Session:
    def __init__(self, vault=None):
        self._vault = vault or Vault()
        self._guard = threading.RLock()
        self._accounts = None
        self._passphrase = None
        self._auto_lock_seconds = 0
        self._auto_lock_timer = None
        self._camera = None

    def status(self, _request=None):
        with self._guard:
            if self._accounts is None:
                return {"vault": VAULT_LOCKED if self._vault.exists() else VAULT_MISSING}
            return {"vault": VAULT_UNLOCKED, "count": len(self._accounts)}

    def create(self, request):
        with self._guard:
            if self._vault.exists():
                raise SessionError("vault-exists", "a vault already exists")
            passphrase = str(request.get("passphrase") or "")
            self._vault.save([], passphrase)
            self._adopt([], passphrase)
            return self.status()

    def unlock(self, request):
        with self._guard:
            passphrase = str(request.get("passphrase") or "")
            self._adopt(self._vault.load(passphrase), passphrase)
            return self.status()

    def lock(self, _request=None):
        with self._guard:
            self._stop_camera()
            self._accounts = None
            self._passphrase = None
            self._cancel_auto_lock()
            return self.status()

    def codes(self, _request=None):
        with self._guard:
            self._require_unlocked()
            now = time.time()
            return {"now": now, "accounts": [self._describe(a, now) for a in self._accounts]}

    def copy(self, request):
        with self._guard:
            self._require_unlocked()
            account = self._find(request.get("id"))
            if not account.supported:
                raise SessionError("unsupported", "counter-based accounts cannot be copied yet")
            try:
                code = account.code(time.time())
            except SecretError as error:
                raise SessionError("invalid-secret", str(error)) from error
            try:
                clipboard.copy(code, self._seconds(request.get("seconds")))
            except subprocess.CalledProcessError as error:
                raise SessionError("clipboard", "wl-copy could not take the clipboard") from error
            return {"name": account.name}

    def scan(self, _request=None):
        with self._guard:
            self._require_unlocked()
            return self._absorb(capture.scan_region(capture.select_region()))

    def add(self, request):
        with self._guard:
            self._require_unlocked()
            text = str(request.get("text") or "").strip()
            if not text:
                raise SessionError("empty", "there is nothing to import")
            if urlsplit(text).scheme.lower() in _LINK_SCHEMES:
                return self._absorb([text])
            return self._absorb(capture.scan_file(text))

    def camera_start(self, request):
        with self._guard:
            self._require_unlocked()
            if self._camera is not None and not self._camera.finished:
                raise SessionError("busy", "a camera scan is already running")
            scanner = camera.Scanner(request.get("device"), request.get("timeout"))
            scanner.start()
            self._camera = scanner
            return {"scanning": True}

    # Reports ok with a done flag even when nothing was found.
    def camera_status(self, _request=None):
        with self._guard:
            scanner = self._camera
            if scanner is None:
                return {"scanning": False, "done": False}
            if not scanner.finished:
                return {"scanning": True, "done": False}

            self._camera = None
            payloads, message, cancelled = scanner.outcome()
            if cancelled:
                return {"scanning": False, "done": True, "cancelled": True}
            if not payloads:
                return {"scanning": False, "done": True, "message": message}
            try:
                result = self._absorb(payloads)
            except migration.ParseError as error:
                return {"scanning": False, "done": True, "message": str(error)}
            result.update({"scanning": False, "done": True})
            return result

    def camera_stop(self, _request=None):
        with self._guard:
            self._stop_camera()
            return {"scanning": False}

    def remove(self, request):
        with self._guard:
            self._require_unlocked()
            account = self._find(request.get("id"))
            remaining = [entry for entry in self._accounts if entry.id != account.id]
            self._vault.save(remaining, self._passphrase, keep_previous=False)
            self._accounts = remaining
            self._touch()
            return {"removed": account.name, "count": len(remaining)}

    def set_auto_lock(self, request):
        with self._guard:
            self._auto_lock_seconds = self._seconds(request.get("seconds"))
            self._touch()
            return {"seconds": self._auto_lock_seconds}

    def set_passphrase(self, request):
        with self._guard:
            self._require_unlocked()
            if str(request.get("current") or "") != self._passphrase:
                raise SessionError("wrong-current", "the current passphrase is wrong")
            following = str(request.get("next") or "")
            self._vault.save(self._accounts, following)
            self._passphrase = following
            self._touch()
            return {}

    # -- internals ---------------------------------------------------------

    def _adopt(self, accounts, passphrase):
        self._accounts = accounts
        self._passphrase = passphrase
        self._touch()

    def _require_unlocked(self):
        if self._accounts is None:
            raise SessionError("locked", "the vault is locked")

    def _find(self, identifier):
        for account in self._accounts:
            if account.id == identifier:
                return account
        raise SessionError("not-found", "that account is no longer in the vault")

    def _describe(self, account, now):
        entry = {
            "id": account.id,
            "issuer": account.issuer,
            "label": account.label,
            "name": account.name,
            "type": account.type,
            "digits": account.digits,
            "period": account.period,
            "supported": account.supported,
            "expiresAt": account.expires_at(now),
            "code": None,
            "error": None,
        }
        if not account.supported:
            entry["error"] = "counter-based"
            return entry
        try:
            entry["code"] = account.code(now)
        except SecretError as error:
            entry["error"] = str(error)
        return entry

    def _absorb(self, payloads):
        if not payloads:
            raise SessionError("no-qr", "no QR code was found there")
        incoming = migration.parse_many(payloads)
        merged, added = merge(self._accounts, incoming)
        if added:
            self._vault.save(merged, self._passphrase)
            self._accounts = merged
        self._touch()
        return summarize(incoming, added)

    @staticmethod
    def _seconds(value):
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _touch(self):
        self._cancel_auto_lock()
        if self._accounts is None or self._auto_lock_seconds <= 0:
            return
        self._auto_lock_timer = threading.Timer(self._auto_lock_seconds, self.lock)
        self._auto_lock_timer.daemon = True
        self._auto_lock_timer.start()

    def _stop_camera(self):
        if self._camera is not None:
            self._camera.stop()
            self._camera = None

    def _cancel_auto_lock(self):
        if self._auto_lock_timer is not None:
            self._auto_lock_timer.cancel()
            self._auto_lock_timer = None


COMMANDS = {
    "status": Session.status,
    "create": Session.create,
    "unlock": Session.unlock,
    "lock": Session.lock,
    "codes": Session.codes,
    "copy": Session.copy,
    "scan": Session.scan,
    "add": Session.add,
    "remove": Session.remove,
    "cameraStart": Session.camera_start,
    "cameraStatus": Session.camera_status,
    "cameraStop": Session.camera_stop,
    "setAutoLock": Session.set_auto_lock,
    "setPassphrase": Session.set_passphrase,
}

_ERROR_CODES = (
    (SessionError, None),
    (PassphraseError, "bad-passphrase"),
    (camera.CameraError, "camera"),
    (capture.CaptureCancelled, "cancelled"),
    (capture.CaptureError, "capture-failed"),
    (migration.ParseError, "unreadable"),
    (clipboard.ClipboardError, "clipboard"),
    (VaultError, "vault-error"),
)


def _respond(sequence, payload=None, message=None, code=None):
    response = {"ok": message is None}
    if sequence is not None:
        response["seq"] = sequence
    if message is None:
        response.update(payload or {})
    else:
        response["error"] = code or "error"
        response["message"] = message
    return response


# The reply carries vault state.
def _failure(session, sequence, error, code):
    response = _respond(sequence, message=str(error) or error.__class__.__name__, code=code)
    response.update(session.status())
    return response


def _run(session, request):
    sequence = request.get("seq")
    try:
        command = COMMANDS.get(str(request.get("cmd") or ""))
        if command is None:
            raise SessionError("unknown-command", f"unknown command {request.get('cmd')!r}")
        return _respond(sequence, command(session, request) or {})
    except Exception as error:
        for kind, code in _ERROR_CODES:
            if isinstance(error, kind):
                return _failure(session, sequence, error, code or getattr(error, "code", "error"))
        return _failure(session, sequence, error, "error")


def serve(source=None, sink=None, vault=None):
    source = source or sys.stdin
    sink = sink or sys.stdout
    session = Session(vault)

    # SIGTERM would skip the finally below and leave the camera on.
    def shutdown(_signum, _frame):
        raise SystemExit(0)

    with contextlib.suppress(ValueError):
        signal.signal(signal.SIGTERM, shutdown)

    try:
        _serve_loop(session, source, sink)
    finally:
        session.camera_stop()
    return 0


def _serve_loop(session, source, sink):
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("a request must be a JSON object")
        except ValueError as error:
            response = _respond(None, message=str(error), code="bad-request")
        else:
            response = _run(session, request)
        sink.write(json.dumps(response) + "\n")
        sink.flush()

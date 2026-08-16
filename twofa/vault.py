import json
import os
import subprocess
import tempfile
from pathlib import Path

from .accounts import Account

FORMAT_VERSION = 1

_GPG_COMMON = [
    "gpg",
    "--batch",
    "--quiet",
    "--yes",
    "--no-symkey-cache",
    "--pinentry-mode",
    "loopback",
]

_GPG_ENCRYPT = [
    "--symmetric",
    "--cipher-algo",
    "AES256",
    "--s2k-mode",
    "3",
    "--s2k-digest-algo",
    "SHA512",
    "--s2k-count",
    "65011712",
    "--compress-algo",
    "none",
]


class VaultError(Exception):
    pass


class PassphraseError(VaultError):
    pass


def default_path():
    data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data_home) / "omafob" / "vault.gpg"


def check_passphrase(passphrase):
    text = str(passphrase or "")
    if not text:
        raise PassphraseError("the passphrase is empty")
    # gpg reads --passphrase-fd only up to the first newline.
    if "\n" in text or "\r" in text:
        raise PassphraseError("the passphrase cannot contain a line break")
    return text


# argv is world readable through /proc, so the passphrase goes on its own fd.
def _run_gpg(arguments, passphrase, payload):
    reader, writer = os.pipe()
    os.set_inheritable(reader, True)
    try:
        with os.fdopen(writer, "wb") as sink:
            sink.write(check_passphrase(passphrase).encode("utf-8"))
        return subprocess.run(
            _GPG_COMMON + ["--passphrase-fd", str(reader)] + arguments,
            input=payload,
            capture_output=True,
            pass_fds=(reader,),
            check=False,
        )
    except FileNotFoundError as error:
        raise VaultError("gpg is not installed") from error
    finally:
        os.close(reader)


class Vault:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()

    def exists(self):
        return self.path.is_file()

    def load(self, passphrase):
        if not self.exists():
            raise VaultError("there is no vault yet")

        result = _run_gpg(["--decrypt"], passphrase, self.path.read_bytes())
        if result.returncode != 0:
            raise PassphraseError("that passphrase does not open the vault")

        try:
            document = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise VaultError("the vault contents are unreadable") from error

        version = document.get("version")
        if version != FORMAT_VERSION:
            raise VaultError(f"unsupported vault format {version!r}")

        return [Account.from_dict(entry) for entry in document.get("accounts") or []]

    # Deleting an account also drops .previous, which still holds it.
    def save(self, accounts, passphrase, keep_previous=True):
        payload = json.dumps(
            {"version": FORMAT_VERSION, "accounts": [account.to_dict() for account in accounts]},
            indent=2,
            sort_keys=True,
        ).encode("utf-8")

        result = _run_gpg(_GPG_ENCRYPT, passphrase, payload)
        if result.returncode != 0:
            raise VaultError(result.stderr.decode("utf-8", "replace").strip() or "gpg could not encrypt the vault")

        self._write(result.stdout, keep_previous)

    # Written to a temp file and renamed, so a crash leaves the old vault in place.
    def _write(self, ciphertext, keep_previous=True):
        directory = self.path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        previous = directory / (self.path.name + ".previous")

        handle, staged = tempfile.mkstemp(dir=directory, prefix=".vault-", suffix=".gpg")
        try:
            with os.fdopen(handle, "wb") as sink:
                sink.write(ciphertext)
                sink.flush()
                os.fsync(sink.fileno())
            os.chmod(staged, 0o600)
            if self.exists() and keep_previous:
                self.path.replace(previous)
            os.replace(staged, self.path)
            if not keep_previous:
                previous.unlink(missing_ok=True)
        except BaseException:
            Path(staged).unlink(missing_ok=True)
            raise

import argparse
import getpass
import sys
import time
from urllib.parse import urlsplit

from . import VERSION, camera, capture, migration, protocol
from .accounts import merge, summarize
from .vault import Vault, VaultError


class CliError(Exception):
    pass


def _ask(prompt="Vault passphrase: "):
    return getpass.getpass(prompt)


def _ask_new():
    passphrase = _ask("New passphrase: ")
    if passphrase != _ask("Repeat passphrase: "):
        raise CliError("the passphrases do not match")
    return passphrase


def _open(vault):
    if not vault.exists():
        raise CliError("no vault yet. run `omafob scan` or `omafob add <link>` to create one")
    passphrase = _ask()
    return vault.load(passphrase), passphrase


def _open_or_create(vault):
    if vault.exists():
        return _open(vault)
    print(f"Creating a new vault at {vault.path}")
    passphrase = _ask_new()
    vault.save([], passphrase)
    return [], passphrase


def _matching(accounts, query):
    needle = query.lower()
    return [account for account in accounts if needle in account.name.lower()]


def _sole(accounts, query):
    found = _matching(accounts, query)
    if not found:
        raise CliError(f"no account matches {query!r}")
    if len(found) > 1:
        names = ", ".join(account.name for account in found)
        raise CliError(f"{query!r} matches several accounts: {names}")
    return found[0]


def _report(result):
    print(f"Imported {result['added']}, already present {result['skipped']}")
    for name in result["names"]:
        print(f"  {name}")
    if result["unsupported"]:
        print(f"{result['unsupported']} counter-based account(s) stored but not yet generated")


def _import(vault, payloads):
    accounts, passphrase = _open_or_create(vault)
    incoming = migration.parse_many(payloads)
    merged, added = merge(accounts, incoming)
    if added:
        vault.save(merged, passphrase)
    _report(summarize(incoming, added))
    return 0


def command_status(vault, _args):
    print(f"{vault.path}: {'present' if vault.exists() else 'missing'}")
    return 0


def command_list(vault, _args):
    accounts, _ = _open(vault)
    if not accounts:
        print("The vault is empty.")
        return 0
    width = max(len(account.name) for account in accounts)
    for account in accounts:
        kind = account.type if account.supported else f"{account.type} (not generated)"
        print(f"{account.name.ljust(width)}  {kind}  {account.digits} digits  {account.period}s")
    return 0


def command_code(vault, args):
    accounts, _ = _open(vault)
    account = _sole(accounts, args.query)
    if not account.supported:
        raise CliError(f"{account.name} is counter-based and is not generated yet")
    now = time.time()
    print(f"{account.code(now)}  {account.name}  {int(account.expires_at(now) - now)}s left")
    return 0


def command_add(vault, args):
    text = args.source.strip()
    if urlsplit(text).scheme.lower() in (migration.OTPAUTH_SCHEME, migration.MIGRATION_SCHEME):
        return _import(vault, [text])
    payloads = capture.scan_file(text)
    if not payloads:
        raise CliError("no QR code was found in that image")
    return _import(vault, payloads)


def command_scan(vault, _args):
    payloads = capture.scan_region(capture.select_region())
    if not payloads:
        raise CliError("no QR code was found in that region")
    return _import(vault, payloads)


def command_camera(vault, args):
    scanner = camera.Scanner(args.device, args.timeout)
    scanner.start()
    print("Hold the QR up to your camera…")
    try:
        while not scanner.finished:
            time.sleep(0.2)
    finally:
        scanner.stop()

    payloads, message, _ = scanner.outcome()
    if not payloads:
        raise CliError(message or "nothing was scanned")
    return _import(vault, payloads)


def command_remove(vault, args):
    accounts, passphrase = _open(vault)
    account = _sole(accounts, args.query)
    vault.save([entry for entry in accounts if entry.id != account.id], passphrase)
    print(f"Removed {account.name}")
    return 0


def command_passwd(vault, _args):
    accounts, _ = _open(vault)
    vault.save(accounts, _ask_new())
    print("Passphrase changed.")
    return 0


def command_agent(vault, _args):
    return protocol.serve(vault=vault)


def build_parser():
    parser = argparse.ArgumentParser(prog="omafob", description="Two-factor codes for the Omarchy bar")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--vault", help="path to the encrypted vault")

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show where the vault lives and whether it exists")
    commands.add_parser("list", help="list stored accounts")
    commands.add_parser("scan", help="import from a QR code on screen")

    webcam = commands.add_parser("camera", help="import by holding a QR up to the webcam")
    webcam.add_argument("--device", help="video device, e.g. /dev/video0")
    webcam.add_argument("--timeout", type=int, default=camera.DEFAULT_TIMEOUT, help="seconds to watch for")
    commands.add_parser("passwd", help="change the vault passphrase")
    commands.add_parser("agent", help="serve the JSON protocol the bar widget speaks")

    add = commands.add_parser("add", help="import from an otpauth link or an image file")
    add.add_argument("source")

    code = commands.add_parser("code", help="print the current code for one account")
    code.add_argument("query")

    remove = commands.add_parser("remove", help="delete one account")
    remove.add_argument("query")

    return parser


HANDLERS = {
    "status": command_status,
    "list": command_list,
    "code": command_code,
    "add": command_add,
    "scan": command_scan,
    "camera": command_camera,
    "remove": command_remove,
    "passwd": command_passwd,
    "agent": command_agent,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return HANDLERS[args.command](Vault(args.vault), args)
    except (CliError, VaultError, camera.CameraError, capture.CaptureError, migration.ParseError) as error:
        print(f"omafob: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

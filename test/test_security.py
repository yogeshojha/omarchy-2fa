import base64
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twofa import camera, clipboard, migration, otp
from twofa import vault as vault_module
from twofa.accounts import Account
from twofa.vault import PassphraseError, Vault

PASSPHRASE = "a passphrase that must never leak"
SECRET = otp.encode_secret(b"12345678901234567890")


class PassphraseHandlingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.vault = Vault(Path(self.directory.name) / "vault.gpg")
        self.addCleanup(self.directory.cleanup)

    def _capture_gpg_invocation(self):
        seen = {}
        real_run = vault_module.subprocess.run

        def spy(command, **kwargs):
            seen["command"] = list(command)
            seen["env"] = kwargs.get("env")
            return real_run(command, **kwargs)

        vault_module.subprocess.run = spy
        self.addCleanup(lambda: setattr(vault_module.subprocess, "run", real_run))
        self.vault.save([Account(issuer="GitHub", secret=SECRET)], PASSPHRASE)
        return seen

    # /proc/<pid>/cmdline is world readable.
    def test_the_passphrase_never_appears_in_the_gpg_command_line(self):
        seen = self._capture_gpg_invocation()
        self.assertNotIn(PASSPHRASE, " ".join(seen["command"]))
        for argument in seen["command"]:
            self.assertNotIn(PASSPHRASE, argument)

    def test_the_passphrase_is_handed_over_on_a_file_descriptor(self):
        seen = self._capture_gpg_invocation()
        self.assertIn("--passphrase-fd", seen["command"])
        self.assertIn("--batch", seen["command"])
        self.assertIn("--pinentry-mode", seen["command"])

    def test_gpg_agent_is_told_not_to_cache_the_passphrase(self):
        self.assertIn("--no-symkey-cache", self._capture_gpg_invocation()["command"])

    def test_the_passphrase_is_not_passed_through_the_environment(self):
        seen = self._capture_gpg_invocation()
        environment = seen["env"] or os.environ
        for key, value in environment.items():
            self.assertNotIn(PASSPHRASE, str(value), f"passphrase leaked into ${key}")

    def test_encryption_parameters_are_the_intended_ones(self):
        command = self._capture_gpg_invocation()["command"]
        self.assertIn("AES256", command)
        self.assertIn("SHA512", command)
        self.assertIn("--symmetric", command)


class OnDiskTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "nested"
        self.vault = Vault(self.root / "vault.gpg")
        self.addCleanup(self.directory.cleanup)

    def test_the_vault_and_its_directory_are_private(self):
        self.vault.save([Account(issuer="GitHub", secret=SECRET)], PASSPHRASE)
        self.assertEqual(self.vault.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_no_secret_survives_in_the_written_bytes(self):
        self.vault.save([Account(issuer="GitHub", label="yogesh", secret=SECRET)], PASSPHRASE)
        blob = self.vault.path.read_bytes()
        self.assertNotIn(SECRET.encode(), blob)
        self.assertNotIn(b"GitHub", blob)
        self.assertNotIn(PASSPHRASE.encode(), blob)

    def test_the_staging_file_is_not_left_behind(self):
        self.vault.save([Account(issuer="GitHub", secret=SECRET)], PASSPHRASE)
        leftovers = [p.name for p in self.root.iterdir() if p.name.startswith(".vault-")]
        self.assertEqual(leftovers, [])

    def test_a_failed_save_leaves_the_existing_vault_intact(self):
        self.vault.save([Account(issuer="GitHub", secret=SECRET)], PASSPHRASE)
        before = self.vault.path.read_bytes()

        with self.assertRaises(PassphraseError):
            self.vault.save([Account(issuer="AWS", secret=SECRET)], "bad\npassphrase")

        self.assertEqual(self.vault.path.read_bytes(), before)
        self.assertEqual([a.issuer for a in self.vault.load(PASSPHRASE)], ["GitHub"])


class HostileInputTest(unittest.TestCase):
    RANDOM = random.Random(20260816)

    def _migration_uri(self, payload):
        return "otpauth-migration://offline?data=" + base64.b64encode(payload).decode()

    # A QR payload is attacker-supplied input.
    def test_random_payloads_only_ever_raise_parse_errors(self):
        for _ in range(400):
            size = self.RANDOM.randrange(0, 64)
            payload = bytes(self.RANDOM.randrange(256) for _ in range(size))
            try:
                migration.parse(self._migration_uri(payload))
            except migration.ParseError:
                pass
            except Exception as error:
                self.fail(f"{type(error).__name__} escaped for payload {payload!r}: {error}")

    def test_truncated_payloads_only_ever_raise_parse_errors(self):
        from test_twofa import _migration_link

        link = _migration_link([("GitHub", "y", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 2, 0)])
        raw = base64.b64decode(link.split("data=", 1)[1].replace("%2B", "+").replace("%3D", "="))
        for cut in range(len(raw)):
            try:
                migration.parse(self._migration_uri(raw[:cut]))
            except migration.ParseError:
                pass
            except Exception as error:
                self.fail(f"{type(error).__name__} escaped at cut {cut}: {error}")

    def test_a_varint_cannot_be_spun_forever(self):
        # 0x80 continues the number.
        with self.assertRaises(migration.ParseError):
            migration.parse(self._migration_uri(b"\x08" + b"\x80" * 4096))

    def test_hostile_otpauth_links_do_not_escape_as_other_errors(self):
        hostile = [
            "otpauth://totp/" + "A" * 5000 + "?secret=" + SECRET,
            "otpauth://totp/../../etc/passwd?secret=" + SECRET,
            "otpauth://totp/x?secret=" + SECRET + "&digits=-1&period=0&counter=-5",
            "otpauth://totp/x?secret=" + SECRET + "&digits=999999999",
            "otpauth://totp/x?secret=%00%01%02",
            "otpauth://hotp/x",
            "otpauth://totp/x?secret=",
        ]
        for link in hostile:
            try:
                accounts = migration.parse(link)
            except migration.ParseError:
                continue
            except Exception as error:
                self.fail(f"{type(error).__name__} escaped for {link[:40]!r}: {error}")
            for account in accounts:
                self.assertGreaterEqual(account.digits, 6)
                self.assertLessEqual(account.digits, 10)
                self.assertGreater(account.period, 0)
                self.assertGreaterEqual(account.counter, 0)

    def test_a_traversal_label_stays_a_label(self):
        account = migration.parse("otpauth://totp/../../etc/passwd?secret=" + SECRET)[0]
        self.assertNotIn("/", account.issuer)
        self.assertIn("passwd", account.label + account.issuer)

    def test_an_unreadable_secret_is_refused_rather_than_guessed(self):
        account = migration.parse("otpauth://totp/x?secret=not-base32!!")[0]
        with self.assertRaises(otp.SecretError):
            account.code(0)


class ExternalCommandTest(unittest.TestCase):
    # Losing --sensitive silently starts recording every copied code.
    def test_copies_are_marked_sensitive(self):
        seen = {}
        real_run = clipboard.subprocess.run

        def spy(command, **kwargs):
            seen["command"] = list(command)

            class Result:
                returncode = 0

            return Result()

        clipboard.subprocess.run = spy
        self.addCleanup(lambda: setattr(clipboard.subprocess, "run", real_run))

        clipboard.copy("123456", wipe_after=0)
        self.assertIn("--sensitive", seen["command"])
        self.assertNotIn("123456", " ".join(seen["command"]))

    def test_the_camera_never_opens_a_preview_window(self):
        self.assertIn("--nodisplay", camera._ARGS)

    def test_the_camera_only_looks_for_qr_codes(self):
        self.assertIn("-Sdisable", camera._ARGS)
        self.assertIn("-Sqrcode.enable", camera._ARGS)

    def test_no_helper_command_is_run_through_a_shell(self):
        helper = Path(__file__).resolve().parents[1] / "twofa"
        sources = [helper / name for name in ("camera.py", "capture.py", "clipboard.py", "vault.py")]
        for source in sources:
            text = source.read_text()
            self.assertNotIn("shell=True", text, f"{source} runs a shell")
            self.assertNotIn("os.system", text, f"{source} runs a shell")


if __name__ == "__main__":
    unittest.main()

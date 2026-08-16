import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twofa import migration, otp, protocol
from twofa.accounts import HOTP, TOTP, Account, merge
from twofa.vault import PassphraseError, Vault

RFC_SECRET = otp.encode_secret(b"12345678901234567890")
PASSPHRASE = "correct horse battery staple"


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _length_field(number, payload):
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _varint_field(number, value):
    return _varint(number << 3 | 0) + _varint(value)


def _migration_link(entries):
    import base64
    from urllib.parse import quote

    payload = b""
    for issuer, name, secret, algorithm, digits, kind, counter in entries:
        parameters = (
            _length_field(1, secret)
            + _length_field(2, name.encode())
            + _length_field(3, issuer.encode())
            + _varint_field(4, algorithm)
            + _varint_field(5, digits)
            + _varint_field(6, kind)
            + _varint_field(7, counter)
        )
        payload += _length_field(1, parameters)
    payload += _varint_field(2, 1) + _varint_field(3, 1) + _varint_field(4, 0)
    return "otpauth-migration://offline?data=" + quote(base64.b64encode(payload))


class TotpTest(unittest.TestCase):
    # RFC 6238 appendix B, SHA-1 rows.
    VECTORS = (
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    )

    def test_rfc_6238_vectors(self):
        for at, expected in self.VECTORS:
            self.assertEqual(otp.totp(RFC_SECRET, at, digits=8), expected)

    def test_secret_accepts_lowercase_spaces_and_missing_padding(self):
        canonical = otp.decode_secret(RFC_SECRET)
        self.assertEqual(otp.decode_secret(RFC_SECRET.lower()), canonical)
        spaced = " ".join(RFC_SECRET[i : i + 4] for i in range(0, len(RFC_SECRET), 4))
        self.assertEqual(otp.decode_secret(spaced), canonical)

    def test_invalid_secret_is_rejected(self):
        for bad in ("", "not base32!", "1"):
            with self.assertRaises(otp.SecretError):
                otp.decode_secret(bad)

    def test_window_end_lands_on_the_next_boundary(self):
        self.assertEqual(otp.window_end(0, 30), 30)
        self.assertEqual(otp.window_end(29.9, 30), 30)
        self.assertEqual(otp.window_end(30, 30), 60)

    def test_unknown_algorithm_falls_back_to_sha1(self):
        self.assertEqual(otp.normalize_algorithm("sha-256"), "SHA256")
        self.assertEqual(otp.normalize_algorithm("whirlpool"), "SHA1")


class MigrationTest(unittest.TestCase):
    def test_reads_every_account_from_one_export(self):
        link = _migration_link(
            [
                ("GitHub", "yogesh@example.com", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 2, 0),
                ("AWS", "root", b"\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14", 2, 2, 2, 0),
                ("Legacy", "counter", b"\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e", 1, 1, 1, 7),
            ]
        )
        accounts = migration.parse(link)

        self.assertEqual([a.issuer for a in accounts], ["GitHub", "AWS", "Legacy"])
        self.assertEqual(accounts[0].label, "yogesh@example.com")
        self.assertEqual((accounts[1].algorithm, accounts[1].digits), ("SHA256", 8))
        self.assertEqual((accounts[2].type, accounts[2].counter), (HOTP, 7))
        self.assertFalse(accounts[2].supported)

    def test_strips_a_repeated_issuer_prefix_from_the_label(self):
        secret = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a"
        link = _migration_link([("GitHub", "GitHub:yogesh", secret, 1, 1, 2, 0)])
        self.assertEqual(migration.parse(link)[0].label, "yogesh")

    def test_reads_a_plain_otpauth_link(self):
        account = migration.parse(
            f"otpauth://totp/Acme%20Inc:yogesh%40example.com?secret={RFC_SECRET}&issuer=Acme%20Inc&digits=8&period=60&algorithm=SHA512"
        )[0]
        self.assertEqual((account.issuer, account.label), ("Acme Inc", "yogesh@example.com"))
        self.assertEqual((account.digits, account.period, account.algorithm), (8, 60, "SHA512"))

    def test_derives_the_issuer_from_the_label_when_absent(self):
        account = migration.parse(f"otpauth://totp/GitLab:yogesh?secret={RFC_SECRET}")[0]
        self.assertEqual((account.issuer, account.label), ("GitLab", "yogesh"))

    # parse_qs would turn the "+" of an unpadded base64 payload into a space.
    def test_keeps_plus_signs_in_a_hand_pasted_payload(self):
        for filler in range(256):
            link = _migration_link([("Plus", "sign", bytes([filler]) * 10, 1, 1, 2, 0)])
            raw = link.split("data=", 1)[1]
            if "%2B" in raw:
                break
        else:
            self.fail("no fixture produced a '+' in its base64 payload")

        literal = migration.parse("otpauth-migration://offline?data=" + raw.replace("%2B", "+"))
        self.assertEqual(literal[0].fingerprint, migration.parse(link)[0].fingerprint)

    def test_rejects_links_it_does_not_understand(self):
        for bad in ("https://example.com", "otpauth://totp/nobody", "otpauth-migration://offline?data=%%%"):
            with self.assertRaises(migration.ParseError):
                migration.parse(bad)


class AccountsTest(unittest.TestCase):
    def test_merge_skips_accounts_already_present(self):
        first = Account(issuer="GitHub", label="a", secret=RFC_SECRET)
        again = Account(issuer="GitHub", label="a", secret=RFC_SECRET)
        other = Account(issuer="AWS", label="b", secret=RFC_SECRET)

        merged, added = merge([first], [again, other])
        self.assertEqual(len(merged), 2)
        self.assertEqual([a.issuer for a in added], ["AWS"])

    def test_out_of_range_values_fall_back_to_the_defaults(self):
        account = Account(secret=RFC_SECRET, digits=99, period=0, algorithm="nope", counter=-4, type="weird")
        self.assertEqual((account.digits, account.period, account.algorithm), (10, 30, "SHA1"))
        self.assertEqual((account.counter, account.type), (0, TOTP))


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.vault = Vault(Path(self.directory.name) / "vault.gpg")
        self.addCleanup(self.directory.cleanup)

    def test_round_trips_accounts(self):
        original = [Account(issuer="GitHub", label="yogesh", secret=RFC_SECRET)]
        self.vault.save(original, PASSPHRASE)

        restored = self.vault.load(PASSPHRASE)
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].secret, RFC_SECRET)
        self.assertEqual(restored[0].id, original[0].id)

    def test_the_vault_file_is_private_and_not_plaintext(self):
        self.vault.save([Account(issuer="GitHub", secret=RFC_SECRET)], PASSPHRASE)
        self.assertEqual(self.vault.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(RFC_SECRET.encode(), self.vault.path.read_bytes())

    def test_a_wrong_passphrase_is_refused(self):
        self.vault.save([], PASSPHRASE)
        with self.assertRaises(PassphraseError):
            self.vault.load("something else")

    def test_a_passphrase_with_a_newline_is_refused(self):
        with self.assertRaises(PassphraseError):
            self.vault.save([], "first line\nsecond line")

    def test_saving_again_keeps_the_previous_file(self):
        self.vault.save([], PASSPHRASE)
        self.vault.save([Account(issuer="GitHub", secret=RFC_SECRET)], PASSPHRASE)
        self.assertTrue((self.vault.path.parent / (self.vault.path.name + ".previous")).is_file())


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.vault = Vault(Path(self.directory.name) / "vault.gpg")
        self.addCleanup(self.directory.cleanup)

    def converse(self, requests):
        source = io.StringIO("".join(json.dumps(request) + "\n" for request in requests))
        sink = io.StringIO()
        protocol.serve(source=source, sink=sink, vault=self.vault)
        return [json.loads(line) for line in sink.getvalue().splitlines()]

    def test_lifecycle_from_empty_to_unlocked_with_accounts(self):
        link = _migration_link([("GitHub", "yogesh", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 2, 0)])
        replies = self.converse(
            [
                {"seq": 1, "cmd": "status"},
                {"seq": 2, "cmd": "create", "passphrase": PASSPHRASE},
                {"seq": 3, "cmd": "add", "text": link},
                {"seq": 4, "cmd": "codes"},
                {"seq": 5, "cmd": "lock"},
                {"seq": 6, "cmd": "codes"},
                {"seq": 7, "cmd": "unlock", "passphrase": PASSPHRASE},
            ]
        )

        self.assertEqual(replies[0]["vault"], protocol.VAULT_MISSING)
        self.assertEqual(replies[1]["vault"], protocol.VAULT_UNLOCKED)
        self.assertEqual(replies[2]["added"], 1)

        entry = replies[3]["accounts"][0]
        self.assertEqual(entry["name"], "GitHub · yogesh")
        self.assertRegex(entry["code"], r"^\d{6}$")
        self.assertGreater(entry["expiresAt"], replies[3]["now"])

        self.assertEqual(replies[4]["vault"], protocol.VAULT_LOCKED)
        self.assertEqual(replies[5]["error"], "locked")
        self.assertEqual(replies[6]["count"], 1)

    def test_sequences_are_echoed_and_unknown_commands_are_named(self):
        replies = self.converse([{"seq": 42, "cmd": "nonsense"}])
        self.assertEqual(replies[0]["seq"], 42)
        self.assertEqual(replies[0]["error"], "unknown-command")

    # They shared a field once, which broke every copy and remove.
    def test_an_account_id_survives_alongside_a_sequence(self):
        link = _migration_link([("GitHub", "yogesh", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 2, 0)])
        setup = self.converse(
            [{"cmd": "create", "passphrase": PASSPHRASE}, {"cmd": "add", "text": link}, {"cmd": "codes"}]
        )
        account_id = setup[2]["accounts"][0]["id"]

        replies = self.converse(
            [
                {"seq": 9, "cmd": "unlock", "passphrase": PASSPHRASE},
                {"seq": 10, "cmd": "remove", "id": account_id},
            ]
        )
        self.assertEqual(replies[1]["seq"], 10)
        self.assertTrue(replies[1]["ok"], replies[1])
        self.assertEqual(replies[1]["count"], 0)

    def test_a_wrong_passphrase_reports_its_own_code(self):
        self.vault.save([], PASSPHRASE)
        replies = self.converse([{"cmd": "unlock", "passphrase": "wrong"}])
        self.assertEqual(replies[0]["error"], "bad-passphrase")

    def test_a_second_import_of_the_same_export_adds_nothing(self):
        link = _migration_link([("GitHub", "yogesh", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 2, 0)])
        replies = self.converse(
            [
                {"cmd": "create", "passphrase": PASSPHRASE},
                {"cmd": "add", "text": link},
                {"cmd": "add", "text": link},
            ]
        )
        self.assertEqual((replies[1]["added"], replies[1]["skipped"]), (1, 0))
        self.assertEqual((replies[2]["added"], replies[2]["skipped"]), (0, 1))

    def test_counter_based_accounts_are_kept_but_not_generated(self):
        link = _migration_link([("Legacy", "counter", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 1, 3)])
        replies = self.converse(
            [
                {"cmd": "create", "passphrase": PASSPHRASE},
                {"cmd": "add", "text": link},
                {"cmd": "codes"},
            ]
        )
        self.assertEqual(replies[1]["unsupported"], 1)

        entry = replies[2]["accounts"][0]
        self.assertFalse(entry["supported"])
        self.assertIsNone(entry["code"])
        self.assertEqual(entry["error"], "counter-based")

    def test_removing_an_account_survives_a_relock(self):
        link = _migration_link(
            [
                ("GitHub", "yogesh", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 2, 0),
                ("AWS", "root", b"\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14", 1, 1, 2, 0),
            ]
        )
        setup = self.converse(
            [{"cmd": "create", "passphrase": PASSPHRASE}, {"cmd": "add", "text": link}, {"cmd": "codes"}]
        )
        victim = setup[2]["accounts"][0]["id"]

        replies = self.converse(
            [
                {"cmd": "unlock", "passphrase": PASSPHRASE},
                {"cmd": "remove", "id": victim},
                {"cmd": "codes"},
            ]
        )
        self.assertEqual(replies[1]["count"], 1)
        self.assertEqual([a["issuer"] for a in replies[2]["accounts"]], ["AWS"])

    def test_changing_the_passphrase_retires_the_old_one(self):
        self.converse([{"cmd": "create", "passphrase": PASSPHRASE}])
        replies = self.converse(
            [
                {"cmd": "unlock", "passphrase": PASSPHRASE},
                {"cmd": "setPassphrase", "current": "wrong", "next": "next one"},
                {"cmd": "setPassphrase", "current": PASSPHRASE, "next": "next one"},
                {"cmd": "lock"},
                {"cmd": "unlock", "passphrase": PASSPHRASE},
                {"cmd": "unlock", "passphrase": "next one"},
            ]
        )
        self.assertEqual(replies[1]["error"], "wrong-current")
        self.assertTrue(replies[2]["ok"])
        self.assertEqual(replies[4]["error"], "bad-passphrase")
        self.assertEqual(replies[5]["vault"], protocol.VAULT_UNLOCKED)

    # An auto-lock between requests was invisible to the bar without this.
    def test_a_refused_command_reports_the_vault_state(self):
        self.vault.save([], PASSPHRASE)
        replies = self.converse(
            [
                {"cmd": "unlock", "passphrase": PASSPHRASE},
                {"cmd": "setAutoLock", "seconds": 1},
                {"cmd": "lock"},
                {"cmd": "codes"},
            ]
        )
        self.assertEqual(replies[3]["error"], "locked")
        self.assertEqual(replies[3]["vault"], protocol.VAULT_LOCKED)

    def test_removing_an_account_leaves_no_recoverable_backup(self):
        link = _migration_link(
            [
                ("GitHub", "yogesh", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 2, 0),
                ("AWS", "root", b"\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14", 1, 1, 2, 0),
            ]
        )
        setup = self.converse(
            [{"cmd": "create", "passphrase": PASSPHRASE}, {"cmd": "add", "text": link}, {"cmd": "codes"}]
        )
        victim = setup[2]["accounts"][0]

        backup = self.vault.path.parent / (self.vault.path.name + ".previous")
        self.assertTrue(backup.is_file(), "the import should have rotated a backup into place")

        self.converse(
            [{"cmd": "unlock", "passphrase": PASSPHRASE}, {"cmd": "remove", "id": victim["id"]}]
        )
        self.assertFalse(backup.exists(), "a removed secret must not survive in the backup")
        self.assertEqual([a.issuer for a in self.vault.load(PASSPHRASE)], ["AWS"])

    def test_a_passphrase_change_still_keeps_a_backup(self):
        self.converse([{"cmd": "create", "passphrase": PASSPHRASE}])
        self.converse(
            [
                {"cmd": "unlock", "passphrase": PASSPHRASE},
                {"cmd": "setPassphrase", "current": PASSPHRASE, "next": "second"},
            ]
        )
        backup = self.vault.path.parent / (self.vault.path.name + ".previous")
        self.assertTrue(backup.is_file())
        self.assertEqual(Vault(backup).load(PASSPHRASE), [])

    def test_a_malformed_line_does_not_kill_the_agent(self):
        source = io.StringIO('not json\n{"seq": 2, "cmd": "status"}\n')
        sink = io.StringIO()
        protocol.serve(source=source, sink=sink, vault=self.vault)
        replies = [json.loads(line) for line in sink.getvalue().splitlines()]

        self.assertEqual(replies[0]["error"], "bad-request")
        self.assertEqual(replies[1]["seq"], 2)


# Drives the camera state machine without touching real hardware.
class FakeScanner:
    instances = []

    def __init__(self, device=None, timeout=None):
        self.device = device
        self.timeout = timeout
        self.started = False
        self.stopped = False
        self.finished = False
        self._outcome = (None, None, False)
        FakeScanner.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def outcome(self):
        return self._outcome

    def resolve(self, payloads=None, message=None, cancelled=False):
        self._outcome = (payloads, message, cancelled)
        self.finished = True


class CameraTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.vault = Vault(Path(self.directory.name) / "vault.gpg")
        self.vault.save([], PASSPHRASE)
        self.addCleanup(self.directory.cleanup)

        FakeScanner.instances = []
        self.real_scanner = protocol.camera.Scanner
        protocol.camera.Scanner = FakeScanner
        self.addCleanup(lambda: setattr(protocol.camera, "Scanner", self.real_scanner))

        self.session = protocol.Session(self.vault)
        protocol._run(self.session, {"cmd": "unlock", "passphrase": PASSPHRASE})

    def run_command(self, **request):
        return protocol._run(self.session, request)

    def scanner(self):
        return FakeScanner.instances[-1]

    def test_a_locked_vault_will_not_open_the_camera(self):
        self.run_command(cmd="lock")
        reply = self.run_command(cmd="cameraStart")
        self.assertEqual(reply["error"], "locked")
        self.assertEqual(FakeScanner.instances, [])

    def test_status_reports_scanning_until_a_code_is_read(self):
        self.assertTrue(self.run_command(cmd="cameraStart")["scanning"])
        self.assertTrue(self.scanner().started)

        pending = self.run_command(cmd="cameraStatus")
        self.assertEqual((pending["scanning"], pending["done"]), (True, False))

        link = _migration_link([("GitHub", "yogesh", b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a", 1, 1, 2, 0)])
        self.scanner().resolve(payloads=[link])

        done = self.run_command(cmd="cameraStatus")
        self.assertEqual((done["scanning"], done["done"], done["added"]), (False, True, 1))
        self.assertEqual([a.issuer for a in self.vault.load(PASSPHRASE)], ["GitHub"])

    def test_seeing_nothing_still_reports_done(self):
        self.run_command(cmd="cameraStart")
        self.scanner().resolve(message="the camera did not see a QR code")

        done = self.run_command(cmd="cameraStatus")
        self.assertTrue(done["ok"])
        self.assertTrue(done["done"])
        self.assertEqual(done["message"], "the camera did not see a QR code")

    def test_cancelling_reports_done_without_a_complaint(self):
        self.run_command(cmd="cameraStart")
        self.scanner().resolve(cancelled=True)

        done = self.run_command(cmd="cameraStatus")
        self.assertTrue(done["done"])
        self.assertTrue(done["cancelled"])
        self.assertIsNone(done.get("message"))

    def test_unreadable_payloads_do_not_strand_the_panel(self):
        self.run_command(cmd="cameraStart")
        self.scanner().resolve(payloads=["https://example.com/not-an-otp"])

        done = self.run_command(cmd="cameraStatus")
        self.assertTrue(done["ok"])
        self.assertTrue(done["done"])
        self.assertTrue(done["message"])

    def test_stopping_releases_the_camera(self):
        self.run_command(cmd="cameraStart")
        self.run_command(cmd="cameraStop")
        self.assertTrue(self.scanner().stopped)

    def test_locking_the_vault_releases_the_camera(self):
        self.run_command(cmd="cameraStart")
        self.run_command(cmd="lock")
        self.assertTrue(self.scanner().stopped)

    def test_closing_the_agent_releases_the_camera(self):
        unlock = json.dumps({"cmd": "unlock", "passphrase": PASSPHRASE})
        source = io.StringIO(unlock + '\n{"cmd": "cameraStart"}\n')
        protocol.serve(source=source, sink=io.StringIO(), vault=self.vault)
        self.assertTrue(self.scanner().stopped)

    def test_two_scans_at_once_are_refused(self):
        self.run_command(cmd="cameraStart")
        self.assertEqual(self.run_command(cmd="cameraStart")["error"], "busy")


class ManifestTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def setUp(self):
        import json

        self.manifest = json.loads((self.ROOT / "manifest.json").read_text())
        self.widget = self.manifest["barWidget"]
        self.model = (self.ROOT / "Model.js").read_text()

    def model_array(self, name):
        import json
        import re

        return json.loads(re.search(rf"var {name} = (\[[^\]]*\])", self.model).group(1))

    # A drifted option silently falls back to the first one through oneOf().
    def test_enum_options_match_the_model(self):
        for key, constant in (
            ("barDisplay", "BAR_DISPLAYS"),
            ("autoLock", "AUTO_LOCK_OPTIONS"),
            ("clipboardWipe", "CLIPBOARD_OPTIONS"),
        ):
            entry = next(s for s in self.widget["schema"] if s["key"] == key)
            self.assertEqual(entry["options"], self.model_array(constant), key)

    def test_every_setting_has_a_matching_default(self):
        defaults = self.widget["defaults"]
        keys = {s["key"] for s in self.widget["schema"]}
        self.assertEqual(keys, set(defaults))
        for entry in self.widget["schema"]:
            self.assertEqual(defaults[entry["key"]], entry["defaultValue"], entry["key"])

    def test_the_entry_point_exists_and_the_id_is_loadable(self):
        self.assertTrue((self.ROOT / self.manifest["entryPoints"]["barWidget"]).is_file())
        self.assertFalse(self.manifest["id"].startswith("omarchy."))
        self.assertFalse(self.manifest["id"][0].isdigit())


if __name__ == "__main__":
    unittest.main()

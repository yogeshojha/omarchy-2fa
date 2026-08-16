import base64
import hashlib
import hmac
import struct

DEFAULT_ALGORITHM = "SHA1"
DEFAULT_DIGITS = 6
DEFAULT_PERIOD = 30

DIGEST_ALGORITHMS = {
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
    "MD5": hashlib.md5,
}


class SecretError(ValueError):
    pass


def normalize_algorithm(name):
    candidate = str(name or "").strip().upper().replace("-", "")
    return candidate if candidate in DIGEST_ALGORITHMS else DEFAULT_ALGORITHM


def decode_secret(secret):
    cleaned = "".join(str(secret or "").split()).replace("-", "").upper()
    if not cleaned:
        raise SecretError("the secret is empty")
    try:
        return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    except Exception as error:
        raise SecretError("the secret is not valid base32") from error


def encode_secret(raw):
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def hotp(secret, counter, digits=DEFAULT_DIGITS, algorithm=DEFAULT_ALGORITHM):
    digest = hmac.new(
        decode_secret(secret),
        struct.pack(">Q", max(0, int(counter))),
        DIGEST_ALGORITHMS[normalize_algorithm(algorithm)],
    ).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % 10**digits).zfill(digits)


def totp(secret, at, digits=DEFAULT_DIGITS, period=DEFAULT_PERIOD, algorithm=DEFAULT_ALGORITHM):
    return hotp(secret, int(at // max(1, int(period))), digits, algorithm)


def window_end(at, period=DEFAULT_PERIOD):
    step = max(1, int(period))
    return (int(at // step) + 1) * step

import base64
import binascii
from urllib.parse import unquote, urlsplit

from . import otp
from .accounts import HOTP, TOTP, Account

MIGRATION_SCHEME = "otpauth-migration"
OTPAUTH_SCHEME = "otpauth"

_ALGORITHM_BY_INDEX = {0: "SHA1", 1: "SHA1", 2: "SHA256", 3: "SHA512", 4: "MD5"}
_DIGITS_BY_INDEX = {0: 6, 1: 6, 2: 8}
_TYPE_BY_INDEX = {0: TOTP, 1: HOTP, 2: TOTP}

_WIRE_VARINT = 0
_WIRE_64BIT = 1
_WIRE_LENGTH = 2
_WIRE_32BIT = 5

_MIGRATION_ACCOUNT_FIELD = 1


class ParseError(ValueError):
    pass


def _read_varint(buffer, position):
    result = 0
    shift = 0
    while position < len(buffer) and shift <= 63:
        byte = buffer[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
        shift += 7
    raise ParseError("the payload ends inside a number")


def _read_fields(buffer):
    position = 0
    while position < len(buffer):
        key, position = _read_varint(buffer, position)
        number, wire = key >> 3, key & 0x07
        if wire == _WIRE_VARINT:
            value, position = _read_varint(buffer, position)
        elif wire == _WIRE_LENGTH:
            length, position = _read_varint(buffer, position)
            end = position + length
            if end > len(buffer):
                raise ParseError("the payload ends inside a field")
            value, position = buffer[position:end], end
        elif wire in (_WIRE_64BIT, _WIRE_32BIT):
            width = 8 if wire == _WIRE_64BIT else 4
            value, position = buffer[position : position + width], position + width
        else:
            raise ParseError(f"unsupported field encoding {wire}")
        yield number, value


# parse_qs would turn a literal "+" in the base64 payload into a space.
def _query_value(uri, key):
    for part in urlsplit(uri).query.split("&"):
        name, _, value = part.partition("=")
        if unquote(name) == key:
            return unquote(value)
    return ""


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _split_name(name, issuer):
    name = str(name or "").strip()
    issuer = str(issuer or "").strip()
    if issuer:
        prefix = issuer + ":"
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix) :].strip()
        return issuer, name
    if ":" in name:
        prefix, _, rest = name.partition(":")
        return prefix.strip(), rest.strip()
    return "", name


def _integer(value, fallback):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _account_from_parameters(buffer):
    secret = b""
    name = ""
    issuer = ""
    algorithm_index = 1
    digits_index = 1
    type_index = 2
    counter = 0

    for number, value in _read_fields(buffer):
        if number == 1:
            secret = value
        elif number == 2:
            name = _text(value)
        elif number == 3:
            issuer = _text(value)
        elif number == 4:
            algorithm_index = value
        elif number == 5:
            digits_index = value
        elif number == 6:
            type_index = value
        elif number == 7:
            counter = value

    if not isinstance(secret, (bytes, bytearray)) or not secret:
        raise ParseError("an exported account carries no secret")

    issuer, label = _split_name(name, issuer)
    return Account(
        issuer=issuer,
        label=label,
        secret=otp.encode_secret(secret),
        type=_TYPE_BY_INDEX.get(type_index, TOTP),
        digits=_DIGITS_BY_INDEX.get(digits_index, otp.DEFAULT_DIGITS),
        algorithm=_ALGORITHM_BY_INDEX.get(algorithm_index, otp.DEFAULT_ALGORITHM),
        counter=counter,
    )


def _parse_migration(uri):
    raw = _query_value(uri, "data")
    if not raw:
        return []
    try:
        payload = base64.b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError) as error:
        raise ParseError("the export payload is not valid base64") from error

    accounts = [
        _account_from_parameters(value)
        for number, value in _read_fields(payload)
        if number == _MIGRATION_ACCOUNT_FIELD and isinstance(value, (bytes, bytearray))
    ]
    if not accounts:
        raise ParseError("the export link contains no accounts")
    return accounts


def _parse_otpauth(uri):
    parts = urlsplit(uri)
    secret = _query_value(uri, "secret")
    if not secret:
        raise ParseError("the otpauth link carries no secret")

    issuer, label = _split_name(unquote(parts.path.lstrip("/")), _query_value(uri, "issuer"))
    return [
        Account(
            issuer=issuer,
            label=label,
            secret=secret,
            type=HOTP if (parts.netloc or "").lower() == HOTP else TOTP,
            digits=_integer(_query_value(uri, "digits"), otp.DEFAULT_DIGITS),
            period=_integer(_query_value(uri, "period"), otp.DEFAULT_PERIOD),
            algorithm=_query_value(uri, "algorithm") or otp.DEFAULT_ALGORITHM,
            counter=_integer(_query_value(uri, "counter"), 0),
        )
    ]


def parse(text):
    candidate = str(text or "").strip()
    scheme = urlsplit(candidate).scheme.lower()
    if scheme == MIGRATION_SCHEME:
        return _parse_migration(candidate)
    if scheme == OTPAUTH_SCHEME:
        return _parse_otpauth(candidate)
    raise ParseError("not an otpauth or Google Authenticator export link")


def parse_many(texts):
    accounts = []
    errors = []
    for text in texts:
        try:
            accounts.extend(parse(text))
        except ParseError as error:
            errors.append(str(error))
    if not accounts and errors:
        raise ParseError(errors[0])
    return accounts

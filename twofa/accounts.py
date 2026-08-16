import uuid
from dataclasses import asdict, dataclass, field

from . import otp

TOTP = "totp"
HOTP = "hotp"

MIN_DIGITS = 6
MAX_DIGITS = 10


def _coerce_digits(value):
    try:
        return min(MAX_DIGITS, max(MIN_DIGITS, int(value)))
    except (TypeError, ValueError):
        return otp.DEFAULT_DIGITS


def _coerce_period(value):
    try:
        period = int(value)
    except (TypeError, ValueError):
        return otp.DEFAULT_PERIOD
    return period if period > 0 else otp.DEFAULT_PERIOD


def _coerce_counter(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


@dataclass
class Account:
    issuer: str = ""
    label: str = ""
    secret: str = ""
    type: str = TOTP
    digits: int = otp.DEFAULT_DIGITS
    period: int = otp.DEFAULT_PERIOD
    algorithm: str = otp.DEFAULT_ALGORITHM
    counter: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        self.issuer = str(self.issuer or "").strip()
        self.label = str(self.label or "").strip()
        self.secret = "".join(str(self.secret or "").split()).upper()
        self.type = HOTP if str(self.type or "").lower() == HOTP else TOTP
        self.digits = _coerce_digits(self.digits)
        self.period = _coerce_period(self.period)
        self.algorithm = otp.normalize_algorithm(self.algorithm)
        self.counter = _coerce_counter(self.counter)

    @property
    def name(self):
        if self.issuer and self.label:
            return f"{self.issuer} · {self.label}"
        return self.issuer or self.label or "Unnamed account"

    @property
    def supported(self):
        return self.type == TOTP

    # Identity for dedupe on re-import.
    @property
    def fingerprint(self):
        return (self.type, self.secret, self.issuer.lower(), self.label.lower())

    def code(self, at):
        if self.type == HOTP:
            return otp.hotp(self.secret, self.counter, self.digits, self.algorithm)
        return otp.totp(self.secret, at, self.digits, self.period, self.algorithm)

    def expires_at(self, at):
        return otp.window_end(at, self.period)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in dict(data or {}).items() if key in known})


def summarize(incoming, added):
    return {
        "added": len(added),
        "skipped": len(incoming) - len(added),
        "unsupported": sum(1 for account in added if not account.supported),
        "names": [account.name for account in added],
    }


def merge(existing, incoming):
    seen = {account.fingerprint for account in existing}
    merged = list(existing)
    added = []
    for account in incoming:
        if account.fingerprint in seen:
            continue
        seen.add(account.fingerprint)
        merged.append(account)
        added.append(account)
    return merged, added

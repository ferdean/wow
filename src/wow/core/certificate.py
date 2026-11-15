"""Read the end of validity from an X.509 certificate.

The display's certificate is renewed on the laptop (AD-12), so the Pi
warns 30 days before it expires (APP-830). Python's standard library
reads certificates only from a TLS peer, so this reads the `notAfter`
of the DER encoding itself (RFC 5280, 4.1: Certificate, TBSCertificate,
Validity; 4.1.2.5: UTCTime years 50 to 99 are 19xx, 00 to 49 are 20xx).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

SEQUENCE: Final[int] = 0x30
EXPLICIT_VERSION: Final[int] = 0xA0
UTC_TIME: Final[int] = 0x17
GENERALIZED_TIME: Final[int] = 0x18
LONG_LENGTH: Final[int] = 0x80
LENGTH_BITS: Final[int] = 0x7F
CENTURY_PIVOT: Final[int] = 50
VALIDITY_FIELD: Final[int] = 3
UTC_FORMAT: Final[str] = "%y%m%d%H%M%SZ"
GENERALIZED_FORMAT: Final[str] = "%Y%m%d%H%M%SZ"


class CertificateError(ValueError):
    """The bytes are not a certificate this module can read."""


@dataclass(frozen=True)
class _Element:
    tag: int
    start: int
    end: int


def _element(data: bytes, at: int) -> _Element:
    if at + 2 > len(data):
        raise CertificateError("truncated element")
    tag, first = data[at], data[at + 1]
    start = at + 2
    if first & LONG_LENGTH:
        count = first & LENGTH_BITS
        if count == 0 or start + count > len(data):
            raise CertificateError("bad length")
        length = int.from_bytes(data[start:start + count], "big")
        start += count
    else:
        length = first
    if start + length > len(data):
        raise CertificateError("element longer than the data")
    return _Element(tag, start, start + length)


def _children(data: bytes, parent: _Element) -> list[_Element]:
    found, at = [], parent.start
    while at < parent.end:
        child = _element(data, at)
        found.append(child)
        at = child.end
    return found


def _time(data: bytes, element: _Element) -> datetime:
    text = data[element.start:element.end].decode("ascii")
    if element.tag == UTC_TIME:
        moment = datetime.strptime(text, UTC_FORMAT)
        if moment.year >= 2000 + CENTURY_PIVOT:
            moment = moment.replace(year=moment.year - 100)
    elif element.tag == GENERALIZED_TIME:
        moment = datetime.strptime(text, GENERALIZED_FORMAT)
    else:
        raise CertificateError(f"not a time: tag {element.tag:#04x}")
    return moment.replace(tzinfo=UTC)


def not_after(der: bytes) -> datetime:
    """Return the end of validity of a DER-encoded certificate."""
    certificate = _element(der, 0)
    if certificate.tag != SEQUENCE:
        raise CertificateError("not a sequence")
    parts = _children(der, certificate)
    if not parts:
        raise CertificateError("empty certificate")
    fields = _children(der, parts[0])
    if fields and fields[0].tag == EXPLICIT_VERSION:
        fields = fields[1:]
    if len(fields) <= VALIDITY_FIELD or (
            fields[VALIDITY_FIELD].tag != SEQUENCE):
        raise CertificateError("no validity")
    validity = _children(der, fields[VALIDITY_FIELD])
    if len(validity) != 2:
        raise CertificateError("validity needs two times")
    try:
        return _time(der, validity[1])
    except (UnicodeDecodeError, ValueError) as error:
        raise CertificateError(f"unreadable time: {error}") from error

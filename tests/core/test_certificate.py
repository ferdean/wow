"""End of validity of the display's certificate (S-CRT-01)."""

import ssl
from datetime import UTC, datetime

import pytest

from tests.support.timeline import TESTDATA
from wow.core.certificate import CertificateError, not_after


def tlv(tag: int, body: bytes) -> bytes:
    if len(body) < 0x80:
        return bytes([tag, len(body)]) + body
    size = len(body).to_bytes(2, "big")
    return bytes([tag, 0x80 | len(size)]) + size + body


def certificate(end: bytes, version: bool = True, pad: int = 0) -> bytes:
    fields = [
        tlv(0x02, b"\x01"),
        tlv(0x30, b"\x06\x03\x2a\x03\x04"),
        tlv(0x30, b"\x00" * pad),
        tlv(0x30, tlv(0x17, b"261112062756Z") + end),
    ]
    if version:
        fields.insert(0, tlv(0xA0, tlv(0x02, b"\x02")))
    return tlv(0x30, tlv(0x30, b"".join(fields)) + tlv(0x30, b""))


@pytest.mark.case("S-CRT-01")
def test_the_test_certificate_ends_in_2036() -> None:
    pem = (TESTDATA / "tls" / "server.crt").read_text(encoding="utf-8")
    assert not_after(ssl.PEM_cert_to_DER_cert(pem)) == datetime(
        2036, 11, 9, 6, 27, 56, tzinfo=UTC)


@pytest.mark.case("S-CRT-01")
def test_both_time_forms_and_long_lengths() -> None:
    assert not_after(certificate(tlv(0x17, b"491231235959Z"))) == datetime(
        2049, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert not_after(certificate(tlv(0x17, b"500101000000Z"))) == datetime(
        1950, 1, 1, tzinfo=UTC)
    assert not_after(certificate(tlv(0x18, b"20610101000000Z"),
                                 version=False, pad=300)) == datetime(
        2061, 1, 1, tzinfo=UTC)


@pytest.mark.case("S-CRT-01")
@pytest.mark.parametrize("data", [
    b"", b"\x30", b"\x02\x01\x00", b"\x30\x00", b"\x30\x85\x01",
    b"\x30\x05\x01", b"\x30\x80",
    certificate(tlv(0x04, b"261112062756Z")),
    certificate(tlv(0x17, b"not a time!!Z")),
    certificate(tlv(0x17, b"\xff\xfe")),
    tlv(0x30, tlv(0x30, tlv(0x02, b"\x01"))),
    tlv(0x30, tlv(0x30, tlv(0x02, b"\x01") + tlv(0x30, b"") + tlv(
        0x30, b"") + tlv(0x30, tlv(0x17, b"261112062756Z")))),
])
def test_anything_else_is_refused(data: bytes) -> None:
    with pytest.raises(CertificateError):
        not_after(data)

import asyncio
import ipaddress
import socket

import pytest

from app.core.config import settings
from app.services import ssrf
from app.services.ssrf import TargetRejected, blocked_reason, parse_target, validate_target

# Captured at import time, before the autouse `dns` fixture stubs the module attribute.
REAL_RESOLVE_HOST = ssrf._resolve_host

# --- address classification ---------------------------------------------------

BLOCKED_ADDRESSES = [
    "127.0.0.1", "127.255.255.254", "10.0.0.1", "10.255.255.255", "172.16.0.1",
    "172.31.255.255", "192.168.0.1", "192.168.255.255", "169.254.169.254",
    "169.254.170.2", "100.64.0.1", "100.127.255.255", "0.0.0.0", "0.1.2.3",
    "224.0.0.1", "239.255.255.250", "240.0.0.1", "255.255.255.255",
    "192.0.0.8", "198.18.0.1", "192.0.2.1", "198.51.100.7", "203.0.113.9",
    "::", "::1", "::2", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:8.8.8.8",
    "fc00::1", "fd12:3456:789a::1", "fe80::1", "febf::1", "fec0::1", "ff02::1",
    "ff05::2", "2001:db8::1", "2001::1", "100::1",
    "64:ff9b::7f00:1", "64:ff9b::a00:1", "64:ff9b::a9fe:a9fe",
    "2002:7f00:1::", "2002:a00:1::", "2002:a9fe:a9fe::",
]

ALLOWED_ADDRESSES = [
    "8.8.8.8", "1.1.1.1", "93.184.216.34", "172.15.255.255", "172.32.0.1",
    "100.63.255.255", "100.128.0.1", "169.253.0.1", "126.255.255.255",
    "2606:4700:4700::1111", "2a00:1450:4001:81b::200e", "64:ff9b::808:808",
]


def test_blocked_addresses_are_all_blocked():
    for text in BLOCKED_ADDRESSES:
        assert blocked_reason(ipaddress.ip_address(text)) is not None, text


def test_public_addresses_are_allowed():
    for text in ALLOWED_ADDRESSES:
        assert blocked_reason(ipaddress.ip_address(text)) is None, text


def test_metadata_address_has_a_readable_label():
    assert "metadata" in blocked_reason(ipaddress.ip_address("169.254.169.254"))
    assert blocked_reason(ipaddress.ip_address("127.0.0.1")) == "loopback"


# --- URL parsing: schemes and malformed input ---------------------------------

BAD_SCHEMES = [
    "ftp://example.com/", "file:///etc/passwd", "gopher://example.com/",
    "ws://example.com/", "wss://example.com/", "data:text/plain,hi",
    "javascript:alert(1)", "dict://example.com:11211/", "ldap://example.com/",
    "//example.com/", "example.com", "",
]


def test_non_http_schemes_are_rejected():
    for url in BAD_SCHEMES:
        with pytest.raises(TargetRejected):
            parse_target(url)


MALFORMED = [
    "http://exa mple.com/", "http://example.com/\r\nX-Evil: 1", "http://example.com/\x00",
    "http://127.0.0.1\\@example.com/", "http://user:pass@example.com/",
    "http://user@example.com/", "http://example.com:0/", "http://example.com:99999/",
    "http://[fe80::1%25eth0]/", "http://" + "a" * 3000 + ".com/", "http:///path",
]


def test_malformed_urls_and_credentials_are_rejected():
    for url in MALFORMED:
        with pytest.raises(TargetRejected):
            parse_target(url)


def test_valid_urls_are_normalised():
    parsed = parse_target("HTTPS://Example.COM./p?q=1")
    assert (parsed.scheme, parsed.host, parsed.port) == ("https", "example.com", 443)
    assert parse_target("http://example.com:8080/").port == 8080
    # Fragment tricks do not change the host that is checked and connected to.
    assert parse_target("http://example.com#@127.0.0.1/").host == "example.com"


# --- literal IPs in every encoding --------------------------------------------

LITERAL_BLOCKED_URLS = [
    "http://127.0.0.1/", "http://127.0.0.1:8000/", "https://127.0.0.1/",
    "http://2130706433/",           # decimal
    "http://017700000001/",         # octal, single number
    "http://0x7f000001/",           # hex, single number
    "http://0x7f.0.0.1/",           # hex octet
    "http://127.1/",                # short form
    "http://127.0.1/",
    "http://0/", "http://0.0.0.0/",
    "http://localhost/",            # resolved through the (fake) DNS below
    "http://[::1]/", "http://[0:0:0:0:0:0:0:1]/", "http://[::]/",
    "http://[::ffff:127.0.0.1]/", "http://[::ffff:7f00:1]/", "http://[::ffff:a00:1]/",
    "http://[fc00::1]/", "http://[fd00::1]/", "http://[fe80::1]/",
    "http://[64:ff9b::7f00:1]/", "http://[2002:7f00:1::]/",
    "http://10.0.0.1/", "http://10.1.2.3:9200/", "http://172.16.5.4/",
    "http://172.31.0.1/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://169.254.169.254./",
    "http://2852039166/",           # 169.254.169.254 as a decimal number
    "http://0xa9fea9fe/",
    "http://100.64.0.1/", "http://100.100.100.200/",
    "http://224.0.0.1/", "http://239.255.255.250/", "http://255.255.255.255/",
    "http://[ff02::1]/",
]


async def test_private_and_special_targets_are_rejected_in_every_encoding(dns):
    dns["localhost"] = ["127.0.0.1", "::1"]
    for url in LITERAL_BLOCKED_URLS:
        with pytest.raises(TargetRejected):
            await validate_target(url)


async def test_literal_ip_rejections_never_depend_on_dns(dns):
    # Literal addresses are judged without a lookup, so there is nothing to spoof.
    for url in ["http://2130706433/", "http://[::1]/", "http://169.254.169.254/"]:
        with pytest.raises(TargetRejected):
            await validate_target(url)
    assert dns.calls == []


async def test_rejection_message_names_the_category_but_not_the_address(dns):
    with pytest.raises(TargetRejected) as exc:
        await validate_target("http://169.254.169.254/")
    assert "metadata" in str(exc.value)
    assert "169.254" not in str(exc.value)


async def test_public_literals_and_hostnames_are_accepted(dns):
    target = await validate_target("https://8.8.8.8/dns")
    assert target.addresses == ["8.8.8.8"]
    target = await validate_target("http://example.com:8080/x")
    assert (target.host, target.port, target.addresses) == ("example.com", 8080, ["93.184.216.34"])
    target = await validate_target("http://[2606:4700:4700::1111]/")
    assert target.addresses == ["2606:4700:4700::1111"]


# --- hostnames that resolve to bad addresses -----------------------------------

async def test_hostname_resolving_to_private_ip_is_rejected(dns):
    for address in ["10.0.0.5", "192.168.1.10", "172.20.0.2", "127.0.0.1", "169.254.169.254",
                    "100.64.0.9", "::1", "fd00::5", "fe80::1", "::ffff:10.0.0.5"]:
        dns["internal.example.test"] = [address]
        with pytest.raises(TargetRejected):
            await validate_target("http://internal.example.test/")


async def test_one_bad_record_rejects_a_mixed_answer(dns):
    dns["mixed.example.test"] = ["93.184.216.34", "10.0.0.5"]
    with pytest.raises(TargetRejected):
        await validate_target("http://mixed.example.test/")
    dns["mixed.example.test"] = ["10.0.0.5", "93.184.216.34"]
    with pytest.raises(TargetRejected):
        await validate_target("http://mixed.example.test/")


async def test_unresolvable_and_empty_answers_are_rejected(dns):
    with pytest.raises(TargetRejected):
        await validate_target("http://nxdomain.example.test/")
    dns["empty.example.test"] = []
    with pytest.raises(TargetRejected):
        await validate_target("http://empty.example.test/")


async def test_slow_dns_times_out(monkeypatch):
    async def _hang(host, port):
        await asyncio.sleep(30)
        return ["93.184.216.34"]

    monkeypatch.setattr("app.services.ssrf._resolve_host", _hang)
    monkeypatch.setattr(settings, "dns_resolve_timeout_s", 0.05)
    with pytest.raises(TargetRejected) as exc:
        await validate_target("http://slow.example.test/")
    assert "timed out" in str(exc.value)


async def test_every_returned_address_is_pinned_in_order(dns):
    dns["multi.example.test"] = ["93.184.216.34", "2606:4700:4700::1111"]
    target = await validate_target("https://multi.example.test/")
    assert target.addresses == ["93.184.216.34", "2606:4700:4700::1111"]


async def test_private_targets_can_be_allowed_for_local_development(dns, monkeypatch):
    monkeypatch.setattr(settings, "block_private_targets", False)
    dns["localhost"] = ["127.0.0.1"]
    target = await validate_target("http://localhost:8000/")
    assert target.addresses == ["127.0.0.1"]
    # The scheme rules still apply.
    with pytest.raises(TargetRejected):
        await validate_target("file:///etc/passwd")


def test_real_resolver_handles_a_literal_without_the_network():
    # Smoke test of the unstubbed code path using an address that needs no DNS.
    addresses = asyncio.run(REAL_RESOLVE_HOST("127.0.0.1", 80))
    assert addresses == ["127.0.0.1"]

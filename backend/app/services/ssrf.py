"""
SSRF guard for benchmark targets.

The backend sends HTTP requests to a URL chosen by the caller, so it must not
be usable to reach the host's own services, the private network, or the cloud
metadata endpoint (169.254.169.254).

Defence in depth, in order:
  1. parse_target() rejects odd schemes, credentials and malformed URLs. It uses
     httpx's own URL parser, the same one the benchmark client uses, so the host
     we check is the host that gets connected to (no parser differential).
  2. resolve_target() resolves the name and rejects the target if ANY returned
     address is non-public. Literal IPs in legacy forms (decimal 2130706433,
     octal 0177.0.0.1, hex 0x7f.1, short 127.1) are decoded before the check.
  3. The addresses it returns are pinned for the actual connections (see
     app/services/pinned.py), so a second DNS answer cannot redirect traffic
     after the check (DNS rebinding).

Error messages are meant for the caller: they name the category (loopback,
private network, ...) but never the resolved address, so the endpoint cannot
be used to map internal DNS.
"""
import asyncio
import ipaddress
import socket
from dataclasses import dataclass

import httpx

from app.core.config import settings

_MAX_URL_LENGTH = 2048


class TargetRejected(Exception):
    """The target URL is not allowed. str(exc) is safe to show to the caller."""


# (network, label). Anything inside one of these is never a valid public target.
_V4_DENY_SPEC = [
    ("0.0.0.0/8", "unspecified or this-network address"),
    ("10.0.0.0/8", "private network"),
    ("100.64.0.0/10", "carrier-grade NAT"),
    ("127.0.0.0/8", "loopback"),
    ("169.254.0.0/16", "link-local or cloud metadata"),
    ("172.16.0.0/12", "private network"),
    ("192.0.0.0/24", "reserved"),
    ("192.0.2.0/24", "documentation range"),
    ("192.88.99.0/24", "reserved"),
    ("192.168.0.0/16", "private network"),
    ("198.18.0.0/15", "benchmarking range"),
    ("198.51.100.0/24", "documentation range"),
    ("203.0.113.0/24", "documentation range"),
    ("224.0.0.0/4", "multicast"),
    ("240.0.0.0/4", "reserved"),
]
_V6_DENY_SPEC = [
    # ::/96 covers the unspecified address (::), loopback (::1) and the
    # deprecated IPv4-compatible form (::a.b.c.d).
    ("::/96", "unspecified, loopback or IPv4-compatible address"),
    ("::ffff:0:0/96", "IPv4-mapped IPv6 address"),
    ("64:ff9b:1::/48", "reserved"),
    ("100::/64", "reserved"),
    ("2001::/23", "reserved (includes Teredo)"),
    ("2001:db8::/32", "documentation range"),
    ("3fff::/20", "documentation range"),
    ("fc00::/7", "private network"),
    ("fe80::/10", "link-local"),
    ("fec0::/10", "reserved"),
    ("ff00::/8", "multicast"),
]
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _compile(spec: list[tuple[str, str]]) -> list[tuple[ipaddress._BaseNetwork, str]]:
    compiled = []
    for cidr, label in spec:
        compiled.append((ipaddress.ip_network(cidr), label))
    return compiled


_V4_DENY = _compile(_V4_DENY_SPEC)
_V6_DENY = _compile(_V6_DENY_SPEC)


def blocked_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return a human label if the address must not be contacted, else None."""
    if isinstance(ip, ipaddress.IPv4Address):
        for network, label in _V4_DENY:
            if ip in network:
                return label
        return None

    for network, label in _V6_DENY:
        if ip in network:
            return label

    # Addresses that embed an IPv4 address: judge the embedded address, so
    # 64:ff9b::7f00:1 (NAT64) and 2002:7f00:1:: (6to4) cannot smuggle 127.0.0.1.
    embedded: ipaddress.IPv4Address | None = None
    if ip in _NAT64:
        embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    elif ip.sixtofour is not None:
        embedded = ip.sixtofour
    if embedded is not None:
        reason = blocked_reason(embedded)
        if reason is not None:
            return reason
    return None


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """
    Decode a host that is an IP literal, including the legacy IPv4 spellings
    that libc resolvers accept but ipaddress does not (decimal, octal, hex and
    short forms). Returns None for ordinary hostnames.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    # inet_aton is the same parser getaddrinfo falls back to, so whatever it
    # accepts is what the connection layer would also treat as an address.
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return ipaddress.IPv4Address(packed)


@dataclass(frozen=True)
class ParsedTarget:
    url: str
    scheme: str
    host: str  # lowercase, IDNA (punycode) form, no brackets
    port: int


@dataclass(frozen=True)
class ResolvedTarget:
    url: str
    scheme: str
    host: str
    port: int
    # Validated addresses to pin the connections to, in connection order.
    addresses: list[str]


def parse_target(url: str) -> ParsedTarget:
    if not isinstance(url, str) or not url:
        raise TargetRejected("Target URL is empty")
    if len(url) > _MAX_URL_LENGTH:
        raise TargetRejected("Target URL is too long")
    # Whitespace, control characters and backslashes are where URL parsers
    # disagree with each other; none has a place in a benchmark target.
    for ch in url:
        if ord(ch) <= 0x20 or ord(ch) == 0x7F or ch == "\\":
            raise TargetRejected("Target URL contains invalid characters")

    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, ValueError):
        raise TargetRejected("Target URL is not valid")

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise TargetRejected("Only http and https targets are allowed")
    if parsed.userinfo:
        raise TargetRejected("Target URL must not contain credentials")

    try:
        host = parsed.raw_host.decode("ascii").lower()
    except UnicodeDecodeError:
        raise TargetRejected("Target URL is not valid")
    if not host or "%" in host:
        # "%" would be an IPv6 zone id or an escape inside the host.
        raise TargetRejected("Target URL is not valid")
    host = host.rstrip(".")
    if not host:
        raise TargetRejected("Target URL is not valid")

    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    if port < 1 or port > 65535:
        raise TargetRejected("Target URL has an invalid port")
    return ParsedTarget(url=url, scheme=scheme, host=host, port=port)


async def _resolve_host(host: str, port: int) -> list[str]:
    """DNS lookup; returns address strings. Separate function so tests can stub it."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        # IPv6 results can carry a scope id ("fe80::1%en0"); drop it.
        address = address.split("%", 1)[0]
        if address not in addresses:
            addresses.append(address)
    return addresses


async def resolve_target(parsed: ParsedTarget) -> ResolvedTarget:
    """Resolve the host and reject non-public destinations."""
    literal = _parse_ip_literal(parsed.host)
    if literal is not None:
        addresses = [str(literal)]
    else:
        try:
            addresses = await asyncio.wait_for(
                _resolve_host(parsed.host, parsed.port),
                timeout=settings.dns_resolve_timeout_s,
            )
        except asyncio.TimeoutError:
            raise TargetRejected("Target host lookup timed out")
        except OSError:
            raise TargetRejected("Target host could not be resolved")
    if not addresses:
        raise TargetRejected("Target host could not be resolved")

    validated: list[str] = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise TargetRejected("Target host resolved to an invalid address")
        if settings.block_private_targets:
            reason = blocked_reason(ip)
            if reason is not None:
                # Any one bad record rejects the whole target: a name that
                # also points at an internal address is not a safe target.
                raise TargetRejected(f"Target address is not allowed ({reason})")
        validated.append(str(ip))

    return ResolvedTarget(
        url=parsed.url,
        scheme=parsed.scheme,
        host=parsed.host,
        port=parsed.port,
        addresses=validated,
    )


async def validate_target(url: str) -> ResolvedTarget:
    """Parse, resolve and check one target URL. Raises TargetRejected."""
    parsed = parse_target(url)
    return await resolve_target(parsed)

"""
HTTP transport that connects only to pre-validated IP addresses.

The SSRF check resolves a hostname once and decides whether it is safe. If the
HTTP client then resolved the name again, an attacker-controlled DNS server
could answer differently the second time (DNS rebinding) and point the
connection at an internal address. This transport removes the second lookup:
the TCP connection goes to the pinned address, while everything above TCP still
uses the original hostname, so

  - the Host header is the hostname the caller gave,
  - TLS SNI and certificate verification use that hostname (httpcore passes the
    request's host to start_tls as server_hostname),
  - connection pooling stays keyed by the hostname.

Only hostnames present in `pins` can be connected to at all; anything else
(including a redirect target, though redirects are off) fails to connect.
"""
import httpcore
import httpx

from app.core.config import settings


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self,
        pins: dict[str, list[str]],
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._pins: dict[str, list[str]] = {}
        for host, addresses in pins.items():
            self._pins[host.lower()] = list(addresses)
        self._inner = inner if inner is not None else httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        addresses = self._pins.get(host.lower())
        if not addresses:
            raise httpcore.ConnectError("Host is not a pinned benchmark target")
        last_error: Exception | None = None
        # Try each validated address in order, like a normal multi-record connect.
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):
        raise httpcore.ConnectError("Unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class PinnedTransport(httpx.AsyncHTTPTransport):
    """AsyncHTTPTransport whose connection pool uses PinnedBackend."""

    def __init__(
        self,
        pins: dict[str, list[str]],
        limits: httpx.Limits | None = None,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        limits = limits if limits is not None else httpx.Limits()
        super().__init__(verify=True, limits=limits, retries=0, http2=False)
        # httpx has no public hook for the network backend, so swap the pool it
        # built. Fail closed if a future httpx moves it: an unpinned transport
        # would silently bring back the DNS-rebinding hole.
        if not isinstance(getattr(self, "_pool", None), httpcore.AsyncConnectionPool):
            raise RuntimeError("Unsupported httpx version: cannot pin connections")
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            retries=0,
            network_backend=PinnedBackend(pins, inner=backend),
        )


def build_pinned_client(
    pins: dict[str, list[str]],
    *,
    headers: dict | None = None,
    timeout: float,
    max_connections: int,
    backend: httpcore.AsyncNetworkBackend | None = None,
) -> httpx.AsyncClient:
    """
    The one way the backend creates a client for a user-supplied target:
    pinned addresses, no redirects, no environment proxies.
    """
    transport = PinnedTransport(
        pins,
        limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
        backend=backend,
    )
    return httpx.AsyncClient(
        transport=transport,
        headers=headers or {},
        timeout=timeout,
        follow_redirects=False,  # a 3xx must not lead to an unchecked host
        trust_env=False,  # no HTTP(S)_PROXY from the environment
    )

import asyncio
import socket

import httpcore
import httpx
import pytest

from app.services.pinned import PinnedBackend, PinnedTransport, build_pinned_client


async def _serve(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _echo_host(reader, writer):
    head = await reader.readuntil(b"\r\n\r\n")
    host_line = b""
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"host:"):
            host_line = line
    body = host_line
    writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body
    )
    await writer.drain()
    writer.close()


async def test_connects_to_the_pinned_address_and_keeps_the_original_host_header(monkeypatch):
    server, port = await _serve(_echo_host)

    def _no_dns(*args, **kwargs):
        raise AssertionError("the pinned transport must not resolve names")

    monkeypatch.setattr(socket, "getaddrinfo", _no_dns)
    async with server:
        # "pinned.example.test" does not exist in DNS; only the pin makes this work.
        async with build_pinned_client(
            {"pinned.example.test": ["127.0.0.1"]}, timeout=5, max_connections=2
        ) as client:
            resp = await client.get(f"http://pinned.example.test:{port}/x")
    assert resp.status_code == 200
    assert resp.text.strip().lower() == f"host: pinned.example.test:{port}"


async def test_unpinned_hosts_cannot_be_connected_to():
    server, port = await _serve(_echo_host)
    async with server:
        async with build_pinned_client(
            {"pinned.example.test": ["127.0.0.1"]}, timeout=5, max_connections=2
        ) as client:
            # Same listening port, different name: no pin, so no connection.
            with pytest.raises(httpx.ConnectError):
                await client.get(f"http://other.example.test:{port}/")
            # An IP literal that is not pinned is refused too.
            with pytest.raises(httpx.ConnectError):
                await client.get(f"http://127.0.0.1:{port}/")


async def test_rebinding_cannot_redirect_a_pinned_name(monkeypatch):
    """Even if DNS now says 'internal', the pinned (validated) address is used."""
    server, port = await _serve(_echo_host)
    resolved: list[str] = []

    def _evil_dns(host, *args, **kwargs):
        resolved.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", _evil_dns)
    async with server:
        async with build_pinned_client(
            {"rebind.example.test": ["127.0.0.1"]}, timeout=5, max_connections=2
        ) as client:
            resp = await client.get(f"http://rebind.example.test:{port}/")
    assert resp.status_code == 200
    assert resolved == []


async def test_redirects_are_not_followed():
    async def _redirect(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 302 Found\r\nLocation: http://169.254.169.254/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        )
        await writer.drain()
        writer.close()

    server, port = await _serve(_redirect)
    async with server:
        async with build_pinned_client(
            {"redir.example.test": ["127.0.0.1"]}, timeout=5, max_connections=2
        ) as client:
            resp = await client.get(f"http://redir.example.test:{port}/")
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://169.254.169.254/"


async def test_environment_proxies_are_ignored(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    server, port = await _serve(_echo_host)
    async with server:
        async with build_pinned_client(
            {"proxy.example.test": ["127.0.0.1"]}, timeout=5, max_connections=2
        ) as client:
            resp = await client.get(f"http://proxy.example.test:{port}/")
    assert resp.status_code == 200


class _RecordingStream(httpcore.AsyncNetworkStream):
    def __init__(self, log):
        self._log = log

    async def read(self, max_bytes, timeout=None):
        return b""

    async def write(self, buffer, timeout=None):
        return None

    async def aclose(self):
        return None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self._log["server_hostname"] = server_hostname
        raise httpcore.ConnectError("stop after recording the TLS server name")

    def get_extra_info(self, info):
        return None


class _RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.log = {}

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.log["connected_to"] = host
        return _RecordingStream(self.log)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise AssertionError("unix sockets must never be used")

    async def sleep(self, seconds):
        return None


async def test_tls_uses_the_hostname_for_sni_while_connecting_to_the_pinned_ip():
    backend = _RecordingBackend()
    async with build_pinned_client(
        {"secure.example.test": ["93.184.216.34"]}, timeout=5, max_connections=2, backend=backend
    ) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("https://secure.example.test/")
    assert backend.log["connected_to"] == "93.184.216.34"
    assert backend.log["server_hostname"] == "secure.example.test"


async def test_second_address_is_tried_when_the_first_fails():
    class _Flaky(_RecordingBackend):
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            self.log.setdefault("tried", []).append(host)
            if host == "93.184.216.34":
                raise httpcore.ConnectError("refused")
            return _RecordingStream(self.log)

    backend = _Flaky()
    pinned = PinnedBackend({"multi.example.test": ["93.184.216.34", "8.8.8.8"]}, inner=backend)
    stream = await pinned.connect_tcp("multi.example.test", 80)
    assert stream is not None
    assert backend.log["tried"] == ["93.184.216.34", "8.8.8.8"]


def test_transport_refuses_to_start_if_httpx_internals_change(monkeypatch):
    original = httpx.AsyncHTTPTransport.__init__

    def _no_pool(self, *args, **kwargs):
        original(self, *args, **kwargs)
        del self._pool

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "__init__", _no_pool)
    with pytest.raises(RuntimeError):
        PinnedTransport({"x.example.test": ["8.8.8.8"]})

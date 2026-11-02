import pytest

from app.core.config import settings
from app.services.ssrf import TargetRejected, allowed_hosts, check_allowlist, validate_target


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "target_allowlist_enabled", None)
    monkeypatch.setattr(settings, "allowed_target_hosts", "httpbin.org,demo.example.com")


async def test_exact_hosts_pass(dns):
    dns["demo.example.com"] = ["93.184.216.34"]
    for url in ["https://httpbin.org/get", "http://demo.example.com:8080/x", "HTTPS://HTTPBIN.ORG/get",
                "https://httpbin.org./get"]:
        target = await validate_target(url)
        assert target.addresses


async def test_suffix_prefix_and_subdomain_tricks_fail(dns):
    for host in ["httpbin.org.evil.com", "evilhttpbin.org", "httpbin.org-evil.com", "sub.httpbin.org",
                 "xhttpbin.org", "httpbin.org.", "org", "demo.example.com.evil.com"]:
        dns[host] = ["93.184.216.34"]
    for url in ["https://httpbin.org.evil.com/", "https://evilhttpbin.org/", "https://httpbin.org-evil.com/",
                "https://sub.httpbin.org/", "https://xhttpbin.org/", "https://org/",
                "https://demo.example.com.evil.com/"]:
        with pytest.raises(TargetRejected) as exc:
            await validate_target(url)
        assert "allowlist" in str(exc.value)


async def test_url_tricks_cannot_smuggle_an_allowlisted_name(dns):
    dns["evil.com"] = ["93.184.216.34"]
    for url in [
        "https://httpbin.org@evil.com/",        # credentials, real host evil.com
        "https://evil.com/?httpbin.org",
        "https://evil.com/#httpbin.org",
        "https://evil.com/httpbin.org",
        "https://httpbin.org:443@evil.com/",
        "https://evil.com\\@httpbin.org/",
    ]:
        with pytest.raises(TargetRejected):
            await validate_target(url)


async def test_lookalike_unicode_hosts_do_not_match(dns):
    # U+0131 (dotless i) in place of "i": a different name once punycoded.
    with pytest.raises(TargetRejected):
        await validate_target("https://httpbın.org/")


async def test_allowlisted_hosts_still_get_ssrf_checks(dns, monkeypatch):
    monkeypatch.setattr(settings, "allowed_target_hosts", "internal.example.test,127.0.0.1")
    dns["internal.example.test"] = ["10.0.0.5"]
    with pytest.raises(TargetRejected) as exc:
        await validate_target("http://internal.example.test/")
    assert "allowlist" not in str(exc.value)
    with pytest.raises(TargetRejected) as exc:
        await validate_target("http://127.0.0.1/")
    assert "allowlist" not in str(exc.value)


async def test_rebinding_after_allowlisting_is_still_caught(dns, monkeypatch):
    # The name is allowlisted; DNS later starts returning a metadata address.
    monkeypatch.setattr(settings, "allowed_target_hosts", "rebind.example.test")
    dns["rebind.example.test"] = ["93.184.216.34"]
    assert (await validate_target("http://rebind.example.test/")).addresses == ["93.184.216.34"]
    dns["rebind.example.test"] = ["169.254.169.254"]
    with pytest.raises(TargetRejected):
        await validate_target("http://rebind.example.test/")


async def test_no_dns_lookup_for_hosts_off_the_list(dns):
    with pytest.raises(TargetRejected):
        await validate_target("https://not-listed.example.org/")
    assert dns.calls == []


def test_wildcards_ports_and_paths_are_not_valid_entries(monkeypatch):
    monkeypatch.setattr(
        settings, "allowed_target_hosts", "*.example.com,example.org:8080,example.net/path,ok.example.io"
    )
    assert allowed_hosts() == ["ok.example.io"]
    with pytest.raises(TargetRejected):
        check_allowlist("foo.example.com")


def test_empty_allowlist_rejects_everything_when_enforced(monkeypatch):
    monkeypatch.setattr(settings, "allowed_target_hosts", "")
    with pytest.raises(TargetRejected):
        check_allowlist("httpbin.org")


def test_unicode_entries_are_compared_in_punycode(monkeypatch):
    monkeypatch.setattr(settings, "allowed_target_hosts", "bücher.example")
    assert allowed_hosts() == ["xn--bcher-kva.example"]
    check_allowlist("xn--bcher-kva.example")


def test_allowlist_is_off_by_default_without_auth(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    check_allowlist("anything.example.org")
    monkeypatch.setattr(settings, "target_allowlist_enabled", True)
    with pytest.raises(TargetRejected):
        check_allowlist("anything.example.org")


def test_allowlist_can_be_switched_off_explicitly(monkeypatch):
    monkeypatch.setattr(settings, "target_allowlist_enabled", False)
    check_allowlist("anything.example.org")

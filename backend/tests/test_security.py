from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core import security
from app.core.config import settings
from app.core.security import (
    LoginRateLimiter,
    client_ip,
    create_token,
    decode_token,
    generate_code,
    hash_code,
    is_valid_label,
    validate_auth_settings,
)


def test_generate_code_format_and_uniqueness():
    first = generate_code("stripe-rebecca")
    label, _, suffix = first.partition(".")
    assert label == "stripe-rebecca"
    assert len(suffix) == 10
    assert suffix.isalnum()
    seen = set()
    for _ in range(200):
        seen.add(generate_code("stripe-rebecca"))
    assert len(seen) == 200


@pytest.mark.parametrize("bad", ["", "ab", "UPPER", "has space", "-lead", "trail-", "a" * 60, "x;y"])
def test_label_validation_rejects(bad):
    assert not is_valid_label(bad)
    with pytest.raises(ValueError):
        generate_code(bad)


def test_hash_is_deterministic_keyed_and_trims_whitespace(monkeypatch):
    assert hash_code("abc.1234567890") == hash_code("  abc.1234567890\n")
    before = hash_code("abc.1234567890")
    monkeypatch.setattr(settings, "code_pepper", "another-pepper-0123456789abcdef012345678")
    assert hash_code("abc.1234567890") != before


def test_token_roundtrip():
    token, expires_at = create_token("11111111-1111-1111-1111-111111111111")
    assert decode_token(token) == "11111111-1111-1111-1111-111111111111"
    assert expires_at > datetime.now(timezone.utc) + timedelta(hours=11)


def test_token_rejections(monkeypatch):
    sub = "11111111-1111-1111-1111-111111111111"
    secret = settings.session_secret
    now = datetime.now(timezone.utc)

    expired = jwt.encode(
        {"iss": "queryscope", "sub": sub, "iat": int((now - timedelta(hours=2)).timestamp()),
         "exp": int((now - timedelta(hours=1)).timestamp())},
        secret, algorithm="HS256",
    )
    assert decode_token(expired) is None

    wrong_key = jwt.encode(
        {"iss": "queryscope", "sub": sub, "iat": int(now.timestamp()),
         "exp": int((now + timedelta(hours=1)).timestamp())},
        "x" * 40, algorithm="HS256",
    )
    assert decode_token(wrong_key) is None

    wrong_issuer = jwt.encode(
        {"iss": "someone-else", "sub": sub, "iat": int(now.timestamp()),
         "exp": int((now + timedelta(hours=1)).timestamp())},
        secret, algorithm="HS256",
    )
    assert decode_token(wrong_issuer) is None

    no_exp = jwt.encode({"iss": "queryscope", "sub": sub, "iat": int(now.timestamp())},
                        secret, algorithm="HS256")
    assert decode_token(no_exp) is None

    # alg=none must never validate.
    unsigned = jwt.encode({"iss": "queryscope", "sub": sub, "iat": 1, "exp": 4102444800},
                          key=None, algorithm="none")
    assert decode_token(unsigned) is None

    good, _ = create_token(sub)
    assert decode_token(good[:-3] + "abc") is None
    assert decode_token("not-a-jwt") is None
    assert decode_token("") is None


def test_validate_auth_settings_fails_closed(monkeypatch):
    validate_auth_settings()
    monkeypatch.setattr(settings, "session_secret", "short")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        validate_auth_settings()
    monkeypatch.setattr(settings, "session_secret", "s" * 40)
    monkeypatch.setattr(settings, "code_pepper", "")
    with pytest.raises(RuntimeError, match="CODE_PEPPER"):
        validate_auth_settings()
    # Disabled auth skips the check (local development).
    monkeypatch.setattr(settings, "auth_enabled", False)
    validate_auth_settings()


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limiter_per_ip_and_window(monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 3)
    monkeypatch.setattr(settings, "login_max_failures_global", 100)
    monkeypatch.setattr(settings, "login_window_seconds", 60)
    clock = FakeClock()
    limiter = LoginRateLimiter(clock=clock)

    for _ in range(2):
        limiter.record_failure("1.1.1.1")
    assert limiter.retry_after("1.1.1.1") == 0
    limiter.record_failure("1.1.1.1")
    assert limiter.retry_after("1.1.1.1") > 0
    assert limiter.retry_after("2.2.2.2") == 0

    clock.now += 61
    assert limiter.retry_after("1.1.1.1") == 0


def test_rate_limiter_global_ceiling_and_reset(monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 100)
    monkeypatch.setattr(settings, "login_max_failures_global", 4)
    monkeypatch.setattr(settings, "login_window_seconds", 60)
    limiter = LoginRateLimiter(clock=FakeClock())
    for i in range(4):
        limiter.record_failure(f"10.0.0.{i}")
    # A fresh IP is blocked once the global ceiling is hit.
    assert limiter.retry_after("9.9.9.9") > 0

    limiter2 = LoginRateLimiter(clock=FakeClock())
    limiter2.record_failure("1.1.1.1")
    limiter2.reset_ip("1.1.1.1")
    assert "1.1.1.1" not in limiter2._per_ip


def test_rate_limiter_bounds_memory(monkeypatch):
    monkeypatch.setattr(LoginRateLimiter, "_MAX_TRACKED_IPS", 5)
    limiter = LoginRateLimiter(clock=FakeClock())
    for i in range(20):
        limiter.record_failure(f"10.0.0.{i}")
    assert len(limiter._per_ip) <= 5


def test_client_ip_trusts_only_the_proxy_appended_entry(monkeypatch):
    # No trusted proxy: ignore the header entirely (it is client-controlled).
    assert client_ip("8.8.8.8", "6.6.6.6") == "8.8.8.8"
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    # An attacker prepends a fake address; the proxy appends the real one.
    assert client_ip("10.0.0.1", "1.2.3.4, 203.0.113.9") == "203.0.113.9"
    # Header shorter than the hop count falls back to the socket peer.
    monkeypatch.setattr(settings, "trusted_proxy_hops", 3)
    assert client_ip("10.0.0.1", "203.0.113.9") == "10.0.0.1"
    assert client_ip(None, None) == "unknown"

"""
Access-code and session-token primitives.

Nothing here touches the database or FastAPI, so it is easy to unit test.
"""
import hashlib
import hmac
import re
import secrets
import string
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

_BASE62 = string.ascii_letters + string.digits
_CODE_SUFFIX_LEN = 10
_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}[a-z0-9]$")
_TOKEN_ISSUER = "queryscope"
_MIN_SECRET_LEN = 32


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_auth_settings() -> None:
    """
    Fail closed at startup: an enabled gate with missing or weak secrets would
    mean tokens signed with an empty key (forgeable) or unkeyed code hashes.
    Raises RuntimeError naming the offending setting, never its value.
    """
    if not settings.auth_enabled:
        return
    if len(settings.session_secret) < _MIN_SECRET_LEN:
        raise RuntimeError(
            "SESSION_SECRET must be set to at least 32 characters when AUTH_ENABLED is true"
        )
    if len(settings.code_pepper) < _MIN_SECRET_LEN:
        raise RuntimeError(
            "CODE_PEPPER must be set to at least 32 characters when AUTH_ENABLED is true"
        )


# ---------------------------------------------------------------------------
# Access codes
# ---------------------------------------------------------------------------

def is_valid_label(label: str) -> bool:
    return bool(_LABEL_RE.match(label))


def generate_code(label: str) -> str:
    """
    Build "<label>.<10 base62 chars>". The label is only a recognisable tag;
    all of the secrecy is in the random suffix (about 59 bits), which is
    acceptable because login is throttled per IP and globally.
    """
    if not is_valid_label(label):
        raise ValueError("label must be 3-42 chars of a-z, 0-9 and hyphen")
    suffix_chars = []
    for _ in range(_CODE_SUFFIX_LEN):
        suffix_chars.append(secrets.choice(_BASE62))
    return f"{label}.{''.join(suffix_chars)}"


def hash_code(code: str) -> str:
    """
    Keyed hash (HMAC-SHA256 with CODE_PEPPER). A plain fast hash is fine here
    only because the pepper is secret; without it, a leaked table could be
    brute-forced offline against the 59-bit suffix space.
    """
    normalized = code.strip()
    return hmac.new(
        settings.code_pepper.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hashes_match(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------

def create_token(code_id: str) -> tuple[str, datetime]:
    """Return (jwt, expiry). Signed HS256 with SESSION_SECRET."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.token_ttl_hours)
    token = jwt.encode(
        {
            "iss": _TOKEN_ISSUER,
            "sub": code_id,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        settings.session_secret,
        algorithm="HS256",
    )
    return token, expires_at


def decode_token(token: str) -> str | None:
    """Return the code id (sub) for a valid token, else None. Never raises."""
    try:
        claims = jwt.decode(
            token,
            settings.session_secret,
            # Pin the algorithm list so "alg: none" and key-confusion tokens fail.
            algorithms=["HS256"],
            issuer=_TOKEN_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.PyJWTError:
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) else None


# ---------------------------------------------------------------------------
# Login throttling
# ---------------------------------------------------------------------------

class LoginRateLimiter:
    """
    Sliding-window limiter on FAILED logins, per IP and globally.

    In-memory on purpose (no Redis, see CLAUDE.md), so it is only correct with
    a single replica. The global ceiling caps total guessing even when an
    attacker rotates IPs.
    """

    _MAX_TRACKED_IPS = 10_000

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._per_ip: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()

    def _prune(self, window: deque[float], window_seconds: int) -> None:
        cutoff = self._clock() - window_seconds
        while window and window[0] <= cutoff:
            window.popleft()

    def retry_after(self, ip: str) -> int:
        """Seconds to wait if this IP is blocked, else 0."""
        window_seconds = settings.login_window_seconds

        self._prune(self._global, window_seconds)
        if len(self._global) >= settings.login_max_failures_global:
            return int(window_seconds - (self._clock() - self._global[0])) + 1

        entries = self._per_ip.get(ip)
        if entries is None:
            return 0
        self._prune(entries, window_seconds)
        if not entries:
            del self._per_ip[ip]
            return 0
        if len(entries) >= settings.login_max_failures_per_ip:
            return int(window_seconds - (self._clock() - entries[0])) + 1
        return 0

    def record_failure(self, ip: str) -> None:
        now = self._clock()
        self._global.append(now)
        if ip not in self._per_ip:
            # Bound memory against an attacker spraying spoofed source IPs:
            # drop the oldest-inserted tracked IP (dicts keep insertion order).
            if len(self._per_ip) >= self._MAX_TRACKED_IPS:
                oldest = next(iter(self._per_ip))
                del self._per_ip[oldest]
            self._per_ip[ip] = deque()
        self._per_ip[ip].append(now)

    def reset_ip(self, ip: str) -> None:
        self._per_ip.pop(ip, None)


login_limiter = LoginRateLimiter()


def client_ip(peer_host: str | None, forwarded_for: str | None) -> str:
    """
    Resolve the client IP. With trusted_proxy_hops = N, the real client is the
    Nth entry from the RIGHT of X-Forwarded-For: each trusted proxy appends the
    address it saw, so everything to the left is attacker-controlled.
    """
    hops = settings.trusted_proxy_hops
    if hops > 0 and forwarded_for:
        parts = []
        for piece in forwarded_for.split(","):
            stripped = piece.strip()
            if stripped:
                parts.append(stripped)
        if len(parts) >= hops:
            return parts[-hops]
    return peer_host or "unknown"

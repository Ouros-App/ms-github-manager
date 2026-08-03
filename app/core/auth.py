import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import Request

_attempts: dict[str, deque[float]] = defaultdict(deque)
_WINDOW = 60
_MAX_ATTEMPTS = 10
_MAX_IPS = 10_000


def _encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _decode(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()


def login_allowed(ip: str) -> bool:
    now = time.time()
    for key in list(_attempts):
        if not _attempts[key] or _attempts[key][-1] <= now - _WINDOW:
            del _attempts[key]
    if ip not in _attempts and len(_attempts) >= _MAX_IPS:
        return False
    attempts = _attempts[ip]
    while attempts and attempts[0] <= now - _WINDOW:
        attempts.popleft()
    if len(attempts) >= _MAX_ATTEMPTS:
        return False
    attempts.append(now)
    return True


def create_session(secret: str, ttl: int) -> str:
    payload = f"session|{int(time.time()) + ttl}"
    encoded = _encode(payload)
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def valid_session(token: str | None, secret: str) -> bool:
    if not secret:
        return False
    try:
        encoded, signature = (token or "").split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        username, expires = _decode(encoded).split("|", 1)
        return bool(username) and int(expires) > time.time() and hmac.compare_digest(signature, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def is_authenticated(request: Request) -> bool:
    return valid_session(request.cookies.get("session"), request.app.state.settings.SESSION_SECRET)

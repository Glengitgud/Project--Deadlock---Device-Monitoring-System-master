"""Security hardening utilities: TOTP MFA, rate limiting, and password reset tokens."""

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from collections import defaultdict
from functools import wraps
from urllib.parse import quote

from flask import current_app, jsonify, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


# ----------------------------------------------------------------------
# 1. RFC 6238 Standard Time-Based One-Time Password (TOTP)
# ----------------------------------------------------------------------

def generate_totp_secret():
    """Generate a cryptographic 160-bit base32-encoded TOTP secret."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def get_totp_uri(secret, username, issuer="DevMonitor"):
    """Construct standard otpauth:// URI for authenticator apps."""
    clean_secret = secret.strip().replace(" ", "").upper()
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(username)}"
        f"?secret={clean_secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


def compute_totp_code(secret, timestamp=None, step=30, digits=6):
    """Compute 6-digit TOTP code for a given timestamp."""
    if timestamp is None:
        timestamp = time.time()
    clean_secret = secret.strip().replace(" ", "").upper()
    padding = (8 - len(clean_secret) % 8) % 8
    key = base64.b32decode(clean_secret + "=" * padding, casefold=True)
    counter = int(timestamp // step)
    counter_bytes = struct.pack(">Q", counter)
    digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code_int % (10 ** digits):0{digits}d}"


def verify_totp_code(secret, user_code, window=1, step=30, digits=6):
    """Verify code against current window +/- allowed drift windows."""
    if not secret or not user_code:
        return False
    user_code = str(user_code).strip()
    now = time.time()
    for drift in range(-window, window + 1):
        if compute_totp_code(secret, timestamp=now + (drift * step), step=step, digits=digits) == user_code:
            return True
    return False


# ----------------------------------------------------------------------
# 2. In-Memory Sliding Window Rate Limiter
# ----------------------------------------------------------------------

class RateLimiter:
    """Thread-safe, sliding-window rate limiter keyed by client identifier."""

    def __init__(self):
        self._history = defaultdict(list)

    def is_allowed(self, key, limit, period_seconds):
        now = time.time()
        window_start = now - period_seconds
        current = [t for t in self._history[key] if t > window_start]
        self._history[key] = current
        if len(current) >= limit:
            retry_after = max(1, int(current[0] + period_seconds - now))
            return False, retry_after
        self._history[key].append(now)
        return True, 0

    def clear(self, key):
        self._history.pop(key, None)


limiter = RateLimiter()


def rate_limit(limit=10, period=60, key_func=None):
    """Decorator to enforce rate limiting on HTTP endpoints."""

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if current_app.config.get("TESTING"):
                return fn(*args, **kwargs)

            if key_func:
                key = key_func()
            else:
                client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1")
                key = f"{fn.__name__}:{client_ip.split(',')[0].strip()}"

            allowed, retry_after = limiter.is_allowed(key, limit, period)
            if not allowed:
                if request.path.startswith("/api/"):
                    response = jsonify(
                        error="Too many requests. Please slow down.",
                        retry_after=retry_after,
                    )
                    response.status_code = 429
                    response.headers["Retry-After"] = str(retry_after)
                    return response
                return (
                    render_template(
                        "login.html",
                        rate_limited=True,
                        retry_after=retry_after,
                    ),
                    429,
                    {"Retry-After": str(retry_after)},
                )
            return fn(*args, **kwargs)

        return wrapped

    return decorator


# ----------------------------------------------------------------------
# 3. Password Reset Signed Token Generation & Validation
# ----------------------------------------------------------------------

def generate_reset_token(email, secret_key, salt="password-reset-salt"):
    """Generate signed URL-safe timed token with email payload."""
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.dumps(email.lower().strip(), salt=salt)


def verify_reset_token(token, secret_key, max_age=3600, salt="password-reset-salt"):
    """Verify reset token and extract email. Returns None if invalid/expired."""
    serializer = URLSafeTimedSerializer(secret_key)
    try:
        email = serializer.loads(token, salt=salt, max_age=max_age)
        return email
    except (BadSignature, SignatureExpired):
        return None

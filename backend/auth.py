import hashlib
import hmac
import json
import secrets
import time
import logging
from collections import defaultdict
from functools import wraps

import bcrypt
from flask import request, jsonify

from backend.config import (
    JWT_SECRET,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
_login_attempts: dict = defaultdict(list)


def check_rate_limit(ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    window_start = now - LOGIN_WINDOW_SECONDS
    attempts = [t for t in _login_attempts[ip] if t > window_start]
    _login_attempts[ip] = attempts
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        return False
    _login_attempts[ip].append(now)
    return True


# ── Password Hashing (bcrypt) ─────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), stored.encode())
    except Exception:
        return False


# ── Legacy PBKDF2 verifier (for existing accounts) ───────────────────────────
def verify_password_legacy(password: str, stored: str) -> bool:
    """Verify passwords hashed with the old PBKDF2 scheme."""
    try:
        salt, h = stored.split(':')
        h2 = hashlib.pbkdf2_hmac(
            'sha256', password.encode(), salt.encode(), 260_000
        )
        return hmac.compare_digest(h, h2.hex())
    except Exception:
        return False


def verify_password_any(password: str, stored: str) -> bool:
    """Try bcrypt first, fall back to legacy PBKDF2."""
    if stored.startswith('$2b$') or stored.startswith('$2a$'):
        return verify_password(password, stored)
    return verify_password_legacy(password, stored)


# ── JWT ───────────────────────────────────────────────────────────────────────
import base64 as _b64


def _b64url(data) -> str:
    if isinstance(data, str):
        data = data.encode()
    return _b64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(s: str) -> bytes:
    s += '=' * (-len(s) % 4)
    return _b64.urlsafe_b64decode(s)


def create_token(user_id: int, role: str) -> str:
    header  = _b64url(json.dumps({'alg': 'HS256', 'typ': 'JWT'}))
    payload = _b64url(json.dumps({
        'sub':  user_id,
        'role': role,
        'exp':  int(time.time()) + 86400,   # 24 h
    }))
    sig_input = f"{header}.{payload}".encode()
    sig = hmac.new(JWT_SECRET.encode(), sig_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def verify_token(token: str):
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header, payload, sig = parts
        sig_input = f"{header}.{payload}".encode()
        expected  = hmac.new(
            JWT_SECRET.encode(), sig_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64url_decode(sig), expected):
            return None
        data = json.loads(_b64url_decode(payload))
        if data.get('exp', 0) < int(time.time()):
            return None
        return data
    except Exception:
        return None


def get_current_user():
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return verify_token(auth[7:])
    return None


# ── Decorators ────────────────────────────────────────────────────────────────
def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorised'}), 401
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorised'}), 401
        if user.get('role') != 'admin':
            return jsonify({'error': 'Forbidden'}), 403
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper

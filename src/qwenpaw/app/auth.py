# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,unreachable
"""Authentication module: password hashing, JWT tokens, and FastAPI middleware.

Login is disabled by default and only enabled when the environment
variable ``QWENPAW_AUTH_ENABLED`` is set to a truthy value (``true``,
``1``, ``yes``).  Credentials are created through a web-based
registration flow rather than environment variables, so that agents
running inside the process cannot read plaintext passwords.

Single-user design: only one account can be registered.  If the user
forgets their password, delete ``auth.json`` from ``SECRET_DIR`` and
restart the service to re-register.

Uses only Python stdlib (hashlib, hmac, secrets) to avoid adding new
dependencies.  The password is stored as a salted SHA-256 hash in
``auth.json`` under ``SECRET_DIR``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from math import ceil
from typing import Optional

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from . import backup_endpoint_policy
from .billing.service import get_wallet_service
from .open_api.auth import authenticate_open_api_request
from .storage.repos.user_repo import get_user_repository
from ..constant import SECRET_DIR, EnvVarLoader
from ..security.secret_store import (
    AUTH_SECRET_FIELDS,
    decrypt_dict_fields,
    encrypt_dict_fields,
    is_encrypted,
)

logger = logging.getLogger(__name__)

AUTH_FILE = SECRET_DIR / "auth.json"

# Token validity: 7 days (default)
TOKEN_EXPIRY_SECONDS = 7 * 24 * 3600

# Maximum token validity: 100 years (for "permanent" tokens)
TOKEN_EXPIRY_MAX = 100 * 365 * 24 * 3600

# Login brute-force protection.  These defaults are intentionally modest:
# enough room for honest typo retries, but short enough to stop public
# password spraying against a single exposed instance.
AUTH_LOGIN_FAILURE_WINDOW_SECONDS = 10 * 60
AUTH_LOGIN_LOCKOUT_SECONDS = 15 * 60
AUTH_LOGIN_MAX_FAILURES_PER_IP = 10
AUTH_LOGIN_MAX_FAILURES_PER_USER = 6

# Paths that do NOT require authentication
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/auth/login",
        "/api/auth/status",
        "/api/auth/register",
        "/api/desktop/update",
        "/api/version",
        "/api/settings/language",
        "/api/plugins",
    },
)

# Prefixes that do NOT require authentication (static assets)
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/assets/",
    "/logo.png",
    "/qwenpaw-symbol.svg",
    "/api/aigc-studio/public-assets/",
    "/api/plugins/",  # plugin JS bundles served to unauthenticated login page
    # This prefix has its own mandatory integration-client dependency.
    "/api/internal/integrations/",
)


def _get_positive_int_env(name: str, default: int) -> int:
    raw = EnvVarLoader.get_str(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r; using %s",
            name,
            raw,
            default,
        )
        return default
    return value if value > 0 else default


class AuthRateLimitError(Exception):
    """Raised when a login attempt is temporarily locked out."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many login attempts")
        self.retry_after = max(1, retry_after)


class LoginAttemptLimiter:
    """In-process login attempt limiter keyed by client IP and username."""

    def __init__(
        self,
        *,
        window_seconds: Optional[int] = None,
        lockout_seconds: Optional[int] = None,
        max_failures_per_ip: Optional[int] = None,
        max_failures_per_user: Optional[int] = None,
    ) -> None:
        self.window_seconds = (
            window_seconds
            if window_seconds is not None
            else _get_positive_int_env(
                "QWENPAW_AUTH_LOGIN_FAILURE_WINDOW_SECONDS",
                AUTH_LOGIN_FAILURE_WINDOW_SECONDS,
            )
        )
        self.lockout_seconds = (
            lockout_seconds
            if lockout_seconds is not None
            else _get_positive_int_env(
                "QWENPAW_AUTH_LOGIN_LOCKOUT_SECONDS",
                AUTH_LOGIN_LOCKOUT_SECONDS,
            )
        )
        self.max_failures_per_ip = (
            max_failures_per_ip
            if max_failures_per_ip is not None
            else _get_positive_int_env(
                "QWENPAW_AUTH_LOGIN_MAX_FAILURES_PER_IP",
                AUTH_LOGIN_MAX_FAILURES_PER_IP,
            )
        )
        self.max_failures_per_user = (
            max_failures_per_user
            if max_failures_per_user is not None
            else _get_positive_int_env(
                "QWENPAW_AUTH_LOGIN_MAX_FAILURES_PER_USER",
                AUTH_LOGIN_MAX_FAILURES_PER_USER,
            )
        )
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, client_ip: str, username: str) -> None:
        now = time.monotonic()
        with self._lock:
            retry_after = self._retry_after_locked(now, client_ip, username)
            if retry_after > 0:
                raise AuthRateLimitError(retry_after)

    def record_failure(self, client_ip: str, username: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key, max_failures in self._keys_with_limits(
                client_ip,
                username,
            ):
                failures = self._recent_failures(key, now)
                failures.append(now)
                self._failures[key] = failures
                if len(failures) >= max_failures:
                    self._locked_until[key] = now + self.lockout_seconds
                    logger.warning(
                        "Login temporarily locked for %s after %d failures",
                        key,
                        len(failures),
                    )

            retry_after = self._retry_after_locked(now, client_ip, username)
            if retry_after > 0:
                raise AuthRateLimitError(retry_after)

    def record_success(self, client_ip: str, username: str) -> None:
        with self._lock:
            for key, _ in self._keys_with_limits(client_ip, username):
                self._failures.pop(key, None)
                self._locked_until.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()

    def _retry_after_locked(
        self,
        now: float,
        client_ip: str,
        username: str,
    ) -> int:
        retry_after = 0
        for key, _ in self._keys_with_limits(client_ip, username):
            until = self._locked_until.get(key)
            if until is None:
                continue
            if until <= now:
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                continue
            retry_after = max(retry_after, ceil(until - now))
        return retry_after

    def _recent_failures(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        return [ts for ts in self._failures.get(key, []) if ts >= cutoff]

    def _keys_with_limits(
        self,
        client_ip: str,
        username: str,
    ) -> tuple[tuple[str, int], tuple[str, int]]:
        ip_key = f"ip:{client_ip or 'unknown'}"
        normalized_user = username.strip().lower() or "<empty>"
        user_key = f"user:{normalized_user}"
        return (
            (ip_key, self.max_failures_per_ip),
            (user_key, self.max_failures_per_user),
        )


LOGIN_ATTEMPT_LIMITER = LoginAttemptLimiter()


def get_request_client_ip(request: Request) -> str:
    """Return the best-effort client IP for auth throttling.

    The deployment nginx config sets X-Real-IP from ``$remote_addr``.
    Prefer that over X-Forwarded-For because clients can inject their own
    X-Forwarded-For values before nginx appends to the chain.
    """
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip

    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def assert_login_attempt_allowed(request: Request, username: str) -> None:
    LOGIN_ATTEMPT_LIMITER.check(get_request_client_ip(request), username)


def record_login_failure(request: Request, username: str) -> None:
    LOGIN_ATTEMPT_LIMITER.record_failure(
        get_request_client_ip(request),
        username,
    )


def record_login_success(request: Request, username: str) -> None:
    LOGIN_ATTEMPT_LIMITER.record_success(
        get_request_client_ip(request),
        username,
    )


# ---------------------------------------------------------------------------
# Helpers (reuse SECRET_DIR patterns from envs/store.py)
# ---------------------------------------------------------------------------


def _chmod_best_effort(path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _prepare_secret_parent(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(path.parent, 0o700)


# ---------------------------------------------------------------------------
# Password hashing (salted SHA-256, no external deps)
# ---------------------------------------------------------------------------


def _hash_password(
    password: str,
    salt: Optional[str] = None,
) -> tuple[str, str]:
    """Hash *password* with *salt*.  Returns ``(hash_hex, salt_hex)``."""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify *password* against a stored hash."""
    h, _ = _hash_password(password, salt)
    return hmac.compare_digest(h, stored_hash)


# ---------------------------------------------------------------------------
# Token generation / verification (HMAC-SHA256, no PyJWT needed)
# ---------------------------------------------------------------------------


def _get_jwt_secret() -> str:
    """Return the signing secret, creating one if absent."""
    data = _load_auth_data()
    secret = data.get("jwt_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        data["jwt_secret"] = secret
        _save_auth_data(data)
    return secret


def create_token(username: str, expiry_seconds: Optional[int] = None) -> str:
    """Create an HMAC-signed token: ``base64(payload).signature``.

    Args:
        username: The username to encode in the token.
        expiry_seconds: Custom expiry time in seconds.
            Use -1 or 0 for permanent tokens.
            Defaults to TOKEN_EXPIRY_SECONDS (7 days).
    """
    import base64

    if expiry_seconds is None:
        expiry_seconds = TOKEN_EXPIRY_SECONDS
    elif expiry_seconds <= 0:
        # Permanent token: 100 years
        expiry_seconds = TOKEN_EXPIRY_MAX
    else:
        # Cap at maximum allowed expiry
        expiry_seconds = min(expiry_seconds, TOKEN_EXPIRY_MAX)

    secret = _get_jwt_secret()
    # Generate unique token ID (jti) for revocation support
    token_id = secrets.token_hex(16)
    payload = json.dumps(
        {
            "sub": username,
            "credential_version": _load_auth_data().get("credential_versions", {}).get(username, 0),
            "exp": int(time.time()) + expiry_seconds,
            "iat": int(time.time()),
            "jti": token_id,  # JWT ID for individual revocation
        },
    )
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(
        secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_token(token: str) -> Optional[str]:
    """Verify *token*, return username if valid, ``None`` otherwise.

    Also checks if the token has been revoked (appears in the revocation list).
    """
    import base64

    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        secret = _get_jwt_secret()
        expected_sig = hmac.new(
            secret.encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None

        # Check if token is revoked
        jti = payload.get("jti")
        if jti and _is_token_revoked(jti):
            return None

        username = payload.get("sub")
        version = _load_auth_data().get("credential_versions", {}).get(username, 0)
        if payload.get("credential_version", 0) != version:
            return None
        return username
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.debug("Token verification failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Auth data persistence (auth.json in SECRET_DIR)
# ---------------------------------------------------------------------------


def _load_auth_data() -> dict:
    """Load ``auth.json`` from ``SECRET_DIR``.

    Returns the parsed dict, or a sentinel with ``_auth_load_error``
    set to ``True`` when the file exists but cannot be read/parsed so
    that callers can fail closed instead of silently bypassing auth.

    Encrypted fields (``jwt_secret``) are transparently decrypted.
    Legacy plaintext values trigger an automatic re-encryption.
    """
    if AUTH_FILE.is_file():
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            needs_rewrite = any(
                isinstance(data.get(field), str)
                and data.get(field)
                and not is_encrypted(data[field])
                for field in AUTH_SECRET_FIELDS
            )
            data = decrypt_dict_fields(data, AUTH_SECRET_FIELDS)
            if needs_rewrite:
                try:
                    _save_auth_data(data)
                except Exception as enc_err:
                    logger.debug(
                        "Deferred plaintext→encrypted migration for"
                        " auth.json: %s",
                        enc_err,
                    )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load auth file %s: %s", AUTH_FILE, exc)
            return {"_auth_load_error": True}
    return {}


def _save_auth_data(data: dict) -> None:
    """Save ``auth.json`` to ``SECRET_DIR`` with restrictive permissions.

    Sensitive fields (``jwt_secret``) are encrypted before writing.
    """
    _prepare_secret_parent(AUTH_FILE)
    encrypted_data = encrypt_dict_fields(data, AUTH_SECRET_FIELDS)
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(encrypted_data, f, indent=2, ensure_ascii=False)
    _chmod_best_effort(AUTH_FILE, 0o600)


# ---------------------------------------------------------------------------
# Token revocation (blacklist management)
# ---------------------------------------------------------------------------


def _is_token_revoked(jti: str) -> bool:
    """Check if a token ID (jti) is in the revocation list.

    Uses O(1) dict lookup via revoked_tokens_meta for performance.
    """
    data = _load_auth_data()
    meta = data.get("revoked_tokens_meta", {})
    return jti in meta


def _add_to_revocation_list(jti: str, exp: int) -> None:
    """Add a token ID to the revocation list with its expiry time.

    Uses revoked_tokens_meta dict for O(1) lookups. The revoked_tokens list
    is kept for backwards compatibility but not used for membership checks.
    """
    data = _load_auth_data()
    if data.get("_auth_load_error"):
        return

    # Initialize revoked_tokens_meta if not present
    if "revoked_tokens_meta" not in data:
        data["revoked_tokens_meta"] = {}

    # O(1) check using dict
    if jti not in data["revoked_tokens_meta"]:
        data["revoked_tokens_meta"][jti] = exp

        # Also add to list for backwards compatibility
        if "revoked_tokens" not in data:
            data["revoked_tokens"] = []
        data["revoked_tokens"].append(jti)

    _save_auth_data(data)


def _clean_expired_revocations() -> None:
    """
    Remove expired tokens from the revocation list to prevent unbounded growth.
    """
    data = _load_auth_data()
    if data.get("_auth_load_error"):
        return

    revoked = data.get("revoked_tokens", [])
    meta = data.get("revoked_tokens_meta", {})
    current_time = int(time.time())

    # Remove expired tokens
    cleaned_revoked = []
    cleaned_meta = {}

    for jti in revoked:
        exp = meta.get(jti, 0)
        if exp > current_time:
            cleaned_revoked.append(jti)
            cleaned_meta[jti] = exp

    if len(cleaned_revoked) < len(revoked):
        data["revoked_tokens"] = cleaned_revoked
        data["revoked_tokens_meta"] = cleaned_meta
        _save_auth_data(data)
        logger.info(
            "Cleaned %d expired tokens from revocation list",
            len(revoked) - len(cleaned_revoked),
        )


def is_auth_enabled() -> bool:
    """Check whether authentication is enabled via environment variable.

    Returns ``True`` when ``QWENPAW_AUTH_ENABLED`` is set to a truthy
    value (``true``, ``1``, ``yes``).  The presence of a registered
    user is checked separately by the middleware so that the first
    user can still reach the registration page.
    """
    env_flag = EnvVarLoader.get_str("QWENPAW_AUTH_ENABLED", "").strip().lower()
    return env_flag in ("true", "1", "yes")


def has_registered_users() -> bool:
    """Return ``True`` if a user has been registered (auth.json or DB)."""
    data = _load_auth_data()
    if data.get("user"):
        return True
    # Also check durable users table (multi-user SaaS)
    try:
        return get_user_repository().count_users() > 0
    except Exception:
        return False


def _get_db_user(username: str) -> Optional[dict]:
    """Return a user row from durable storage as a plain dict, if present."""
    try:
        return get_user_repository().get_user_by_username(username)
    except Exception as exc:
        logger.debug("DB user lookup failed: %s", exc)
        return None


def _ensure_db_user(
    username: str,
    password_hash: str,
    password_salt: str,
    role: str = "admin",
) -> Optional[dict]:
    """Ensure the auth user also exists in durable user storage.

    Older single-user installs stored the first account only in auth.json.
    Newer route guards read request roles from durable storage, so registration
    must keep both stores in sync.
    """
    try:
        return get_user_repository().ensure_user(
            username=username,
            password_hash=password_hash,
            password_salt=password_salt,
            role=role,
        )
    except Exception as exc:
        logger.debug("Failed to sync auth user '%s' to DB: %s", username, exc)
        return None


def _update_db_user_credentials(
    old_username: str,
    username: str,
    password_hash: str,
    password_salt: str,
    role: str = "admin",
) -> Optional[dict]:
    """Update the durable user that mirrors the single-user auth account."""
    try:
        return get_user_repository().update_user_credentials(
            old_username=old_username,
            username=username,
            password_hash=password_hash,
            password_salt=password_salt,
            role=role,
        )
    except Exception as exc:
        logger.debug(
            "Failed to update auth user '%s' in DB: %s",
            username,
            exc,
        )
        return None


def resolve_authenticated_user(username: str) -> Optional[dict]:
    """Resolve a verified token subject to user metadata.

    The token proves the username came from our auth secret.  Prefer the DB
    user record, and lazily migrate a legacy auth.json user when necessary.
    """
    row = _get_db_user(username)
    if row:
        return row

    data = _load_auth_data()
    user = data.get("user") or {}
    if user.get("username") != username:
        return None

    return _ensure_db_user(
        username,
        user.get("password_hash", ""),
        user.get("password_salt", ""),
        "admin",
    )


# ---------------------------------------------------------------------------
# Registration (single-user)
# ---------------------------------------------------------------------------


def register_user(
    username: str,
    password: str,
    expiry_seconds: Optional[int] = None,
) -> Optional[str]:
    """Register the single user account.

    Args:
        username: The username to register.
        password: The password to register.
        expiry_seconds: Custom token expiry time in seconds.

    Returns a token on success, ``None`` if a user already exists.
    """
    data = _load_auth_data()

    # Only one user allowed
    if data.get("user"):
        existing = data["user"]
        if (
            data.get("registration_pending_wallet")
            and existing.get("username") == username
            and verify_password(
                password,
                existing.get("password_hash", ""),
                existing.get("password_salt", ""),
            )
        ):
            user = _ensure_db_user(
                username,
                existing.get("password_hash", ""),
                existing.get("password_salt", ""),
                "admin",
            )
            if user is None:
                raise RuntimeError(
                    "durable registration could not be completed",
                )
            get_wallet_service().get_or_create_personal_wallet(user["id"])
            data.pop("registration_pending_wallet", None)
            _save_auth_data(data)
            return create_token(username, expiry_seconds)
        return None
    try:
        if get_user_repository().count_users() > 0:
            return None
    except Exception as exc:
        logger.debug(
            "DB user count lookup failed during registration: %s",
            exc,
        )
        return None

    pw_hash, salt = _hash_password(password)
    data["user"] = {
        "username": username,
        "password_hash": pw_hash,
        "password_salt": salt,
    }
    data["registration_pending_wallet"] = True

    # Ensure jwt_secret exists
    if not data.get("jwt_secret"):
        data["jwt_secret"] = secrets.token_hex(32)

    _save_auth_data(data)
    user = _ensure_db_user(username, pw_hash, salt, "admin")
    if user is None:
        raise RuntimeError("durable registration could not be completed")
    get_wallet_service().get_or_create_personal_wallet(user["id"])
    data.pop("registration_pending_wallet", None)
    _save_auth_data(data)
    logger.info("User '%s' registered", username)
    return create_token(username, expiry_seconds)


def auto_register_from_env() -> None:
    """Auto-register admin user from environment variables.

    Called once during application startup.  If ``QWENPAW_AUTH_ENABLED``
    is truthy and both ``QWENPAW_AUTH_USERNAME`` and ``QWENPAW_AUTH_PASSWORD``
    are set, the admin account is created automatically — useful for
    Docker, Kubernetes, server-panel, and other automated deployments
    where interactive web registration is not practical.

    Skips silently when:
    - authentication is not enabled
    - a user has already been registered
    - either env var is missing or empty
    """
    if not is_auth_enabled():
        return
    if has_registered_users():
        return

    username = EnvVarLoader.get_str("QWENPAW_AUTH_USERNAME", "").strip()
    password = EnvVarLoader.get_str("QWENPAW_AUTH_PASSWORD", "").strip()
    if not username or not password:
        return

    token = register_user(username, password)
    if token:
        logger.info(
            "Auto-registered user '%s' from environment variables",
            username,
        )


def update_credentials(
    current_password: str,
    new_username: Optional[str] = None,
    new_password: Optional[str] = None,
    expiry_seconds: Optional[int] = None,
    *,
    username: str,
) -> Optional[str]:
    """Update only the verified token subject, preserving its identity and role."""
    data = _load_auth_data()
    if data.get("_auth_load_error"):
        raise RuntimeError("Authentication storage unavailable")
    legacy = data.get("user") or {}
    is_legacy = legacy.get("username") == username
    repo = get_user_repository()
    user = repo.get_user_by_username(username)
    credentials = repo.get_user_credentials(username)
    # Match the legacy login path, but only for that exact token subject.
    if is_legacy and verify_password(
        current_password, legacy.get("password_hash", ""), legacy.get("password_salt", ""),
    ):
        credentials = legacy
    elif not credentials or not verify_password(
        current_password, credentials["password_hash"], credentials["password_salt"],
    ):
        return None
    target = new_username.strip() if new_username else username
    if target != username and (
        repo.get_user_by_username(target) or legacy.get("username") == target
    ):
        raise ValueError("Username already exists")
    pw_hash, salt = credentials["password_hash"], credentials["password_salt"]
    if new_password:
        pw_hash, salt = _hash_password(new_password)
    updated = repo.update_user_credentials(
        old_username=username, username=target,
        password_hash=pw_hash, password_salt=salt,
        role=user["role"] if user else "admin",
    )
    if not updated:
        raise RuntimeError("Failed to update user credentials")
    if is_legacy:
        data["user"] = {**legacy, "username": target,
                        "password_hash": pw_hash, "password_salt": salt}
    # Invalidate this user's sessions without signing out every other user.
    versions = data.setdefault("credential_versions", {})
    versions[username] = secrets.token_hex(16)
    versions[target] = secrets.token_hex(16)
    _save_auth_data(data)
    logger.info("Credentials updated for user '%s'", target)
    return create_token(target, expiry_seconds)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def authenticate(
    username: str,
    password: str,
    expiry_seconds: Optional[int] = None,
) -> Optional[str]:
    """Authenticate *username* / *password*.  Returns a token if valid.

    Checks auth.json first (legacy single-user), then falls back to
    the durable ``users`` table (multi-user SaaS architecture).

    Args:
        username: The username to authenticate.
        password: The password to verify.
        expiry_seconds: Custom token expiry time in seconds.
    """
    # --- Strategy 1: legacy auth.json single-user ---
    data = _load_auth_data()
    user = data.get("user")
    if user and user.get("username") == username:
        stored_hash = user.get("password_hash", "")
        stored_salt = user.get("password_salt", "")
        if (
            stored_hash
            and stored_salt
            and verify_password(password, stored_hash, stored_salt)
        ):
            _ensure_db_user(username, stored_hash, stored_salt, "admin")
            return create_token(username, expiry_seconds)

    # --- Strategy 2: durable users table (multi-user) ---
    try:
        credentials = get_user_repository().get_user_credentials(username)
        if credentials:
            if verify_password(
                password,
                credentials["password_hash"],
                credentials["password_salt"],
            ):
                return create_token(username, expiry_seconds)
    except Exception as exc:
        logger.debug("DB auth lookup failed: %s", exc)

    return None


def revoke_token(token: str) -> bool:
    """Revoke a single token by adding its jti to the blacklist.

    Args:
        token: The token string to revoke.

    Returns True on success, False on failure.
    """
    import base64

    try:
        # Extract jti and exp from token
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False

        payload_b64 = parts[0]
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        jti = payload.get("jti")
        exp = payload.get("exp", 0)

        if not jti:
            logger.warning("Token has no jti, cannot revoke individually")
            return False

        _add_to_revocation_list(jti, exp)
        logger.info("Token %s revoked", jti[:8])

        # Clean up expired tokens periodically
        _clean_expired_revocations()

        return True
    except Exception as exc:
        logger.error("Failed to revoke token: %s", exc)
        return False


def revoke_all_tokens() -> bool:
    """Revoke all existing tokens by rotating the JWT secret.

    This will invalidate all tokens that were issued before this call.
    Also clears the revocation list since all tokens are invalid anyway.
    Returns True on success, False on failure.
    """
    try:
        data = _load_auth_data()
        if data.get("_auth_load_error"):
            return False

        # Rotate JWT secret to invalidate all existing tokens
        data["jwt_secret"] = secrets.token_hex(32)

        # Clear revocation list since all tokens are now invalid
        data["revoked_tokens"] = []
        data["revoked_tokens_meta"] = {}

        _save_auth_data(data)
        logger.info("All tokens revoked (JWT secret rotated)")
        return True
    except Exception as exc:
        logger.error("Failed to revoke tokens: %s", exc)
        return False


# ---------------------------------------------------------------------------
# FastAPI middleware
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that checks Bearer token on protected routes."""

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        """Check Bearer token on protected API routes; skip public paths."""
        if request.url.path.startswith("/api/open/"):
            try:
                await authenticate_open_api_request(
                    request,
                    required_scope="messages:create",
                )
            except HTTPException as exc:
                return Response(
                    content=json.dumps({"detail": exc.detail}),
                    status_code=exc.status_code,
                    media_type="application/json",
                )
            return await call_next(request)

        skip_auth = self._should_skip_auth(request)
        decision = backup_endpoint_policy.apply(request, skip_auth=skip_auth)
        if isinstance(decision, Response):
            return decision
        skip_auth = decision

        token = self._extract_token(request)
        if token:
            username = verify_token(token)
            if username is not None:
                row = resolve_authenticated_user(username)
                if row:
                    request.state.user = username
                    request.state.user_id = row["id"]
                    request.state.role = row["role"]
                elif not skip_auth:
                    return Response(
                        content=json.dumps(
                            {"detail": "User no longer exists"},
                        ),
                        status_code=401,
                        media_type="application/json",
                    )
            elif not skip_auth:
                return Response(
                    content=json.dumps({"detail": "Invalid or expired token"}),
                    status_code=401,
                    media_type="application/json",
                )
        elif not skip_auth:
            return Response(
                content=json.dumps({"detail": "Not authenticated"}),
                status_code=401,
                media_type="application/json",
            )

        if skip_auth and not hasattr(request.state, "user"):
            request.state.user = "admin"
            request.state.user_id = 1
            request.state.role = "admin"

        return await call_next(request)

    @staticmethod
    def _should_skip_auth(request: Request) -> bool:
        """Return ``True`` when the request does not require auth."""
        if not is_auth_enabled():
            return True

        path = request.url.path

        if request.method == "OPTIONS":
            return True

        if path in _PUBLIC_PATHS or any(
            path.startswith(p) for p in _PUBLIC_PREFIXES
        ):
            return True

        # Only protect /api/ routes
        if not path.startswith("/api/"):
            return True

        # Check if client host is in allow_no_auth_hosts whitelist
        from ..config import load_config

        client_host = request.client.host if request.client else ""
        config = load_config()
        allowed_hosts = config.security.allow_no_auth_hosts
        return client_host in allowed_hosts

    @staticmethod
    def _extract_token(request: Request) -> Optional[str]:
        """Extract Bearer token from header or WebSocket query param."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        if "upgrade" in request.headers.get("connection", "").lower():
            return request.query_params.get("token")

        token = request.query_params.get("token")
        if token:
            return token

        # Iframe preview assets (CSS/JS/images loaded by a previewed HTML file)
        # cannot attach Authorization headers, and relative asset URLs do not
        # inherit the iframe query string. Same-origin browsers do include the
        # parent preview URL as Referer, so allow preview subresources to reuse
        # that token.
        if request.url.path.startswith(
            ("/api/user/workspace/preview/", "/api/files/preview/"),
        ):
            from urllib.parse import parse_qs, urlparse

            referer = request.headers.get("referer", "")
            if referer:
                ref_token = parse_qs(urlparse(referer).query).get(
                    "token",
                    [""],
                )[0]
                if ref_token:
                    return ref_token
        return None

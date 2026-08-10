"""Request identity - Clerk session-token verification.

The rule this module exists to enforce: **identity comes only from a signature we
verified.** A caller-supplied user id is not identity, it is a claim about
identity, and the two are indistinguishable at the wire until something checks a
signature. So the service reads exactly one thing - ``Authorization: Bearer
<clerk session token>`` - verifies its RS256 signature against Clerk's published
JWKS, and takes ``sub`` and ``email`` from the verified claims. Any
``X-User-Id`` / ``X-User-Email`` style header is ignored, deliberately and
permanently: honouring one would let any caller write any user's name into the
audit log.

Two independent switches, which is what lets the public demo and a signed-in user
share one endpoint:

* **Verification is always on.** A valid token always produces a real identity.
* ``CLERK_AUTH_ENABLED`` decides whether a token is *required*. Off (the default)
  means no token is fine and the caller is anonymous - the landing-page flow stays
  public. On means a request without a valid token is rejected.

A token that is present but bad is always a 401, under either switch. Downgrading
a forged token to "anonymous" would hide exactly the event worth seeing.

Verification is keyless: JWKS is a public endpoint. ``CLERK_SECRET_KEY`` is not
needed here and is held only for Clerk Backend API calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from agent.logging_config import get_logger
from agent.settings import Settings, get_settings

log = get_logger(__name__)

#: Clerk's default session token carries no email. Instances that add one via a
#: JWT template use one of these names; first match wins, missing is normal.
EMAIL_CLAIMS = ("email", "email_address", "primary_email_address")


@dataclass(frozen=True)
class Principal:
    """Who is asking. Written to the queries log; never taken from a raw header."""

    user_id: str
    authenticated: bool
    email: str | None = None


ANONYMOUS = Principal(user_id="anonymous", authenticated=False)


class AuthError(Exception):
    """Token present but not trustworthy."""


@lru_cache(maxsize=4)
def _jwk_client(jwks_url: str) -> Any:
    """Cached JWKS client. Keys are fetched once and reused across requests."""
    from jwt import PyJWKClient

    return PyJWKClient(jwks_url, cache_keys=True, max_cached_keys=8)


def _verify_sync(token: str, settings: Settings) -> Principal:
    """Blocking verification. Called in a worker thread - PyJWKClient uses urllib."""
    import jwt

    jwks_url = settings.clerk_jwks
    if not jwks_url or not settings.clerk_jwt_issuer:
        raise AuthError("Clerk verification is not configured")
    try:
        signing_key = _jwk_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_jwt_issuer,
            leeway=settings.clerk_leeway_seconds,
            # Clerk session tokens set no `aud` by default; requiring one would
            # reject every real token.
            options={"require": ["exp", "sub"], "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"{type(exc).__name__}: {exc}") from exc
    except Exception as exc:  # JWKS fetch failure, malformed key set
        raise AuthError(f"could not verify the token: {type(exc).__name__}") from exc

    subject = claims.get("sub")
    if not subject:
        raise AuthError("token has no subject claim")
    email = next(
        (claims[c] for c in EMAIL_CLAIMS if isinstance(claims.get(c), str)), None
    )
    return Principal(user_id=str(subject), authenticated=True, email=email)


async def verify_clerk_jwt(token: str, settings: Settings) -> Principal:
    """Verify a Clerk session token against Clerk's JWKS.

    Raises:
        AuthError: signature, issuer, expiry or claim check failed.
    """
    return await asyncio.to_thread(_verify_sync, token, settings)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_principal(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """FastAPI dependency. Anonymous unless a verified token says otherwise."""
    has_bearer = bool(authorization and authorization.lower().startswith("bearer "))

    if not has_bearer:
        if settings.clerk_auth_enabled:
            raise _unauthorized("missing bearer token")
        return ANONYMOUS

    if not settings.clerk_configured:
        # Cannot verify, so cannot trust. Never fall through to the token's claims.
        log.warning("bearer token received but Clerk verification is not configured")
        if settings.clerk_auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="authentication is required but not configured",
            )
        return ANONYMOUS

    try:
        principal = await verify_clerk_jwt(authorization.split(" ", 1)[1], settings)
    except AuthError as exc:
        log.warning("token rejected", extra={"reason": str(exc)})
        raise _unauthorized("invalid or expired token") from exc
    log.info("authenticated request", extra={"user_id": principal.user_id})
    return principal

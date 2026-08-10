"""Clerk session-token verification.

Tokens are signed here with a throwaway RSA key and the JWKS lookup is replaced
with that key, so ``jwt.decode`` runs for real - signature, issuer, expiry and
required claims are all genuinely checked - with no network.

The property under test is not "auth works". It is: **no unverified input ever
becomes an identity.** Every path that could turn a caller's assertion into a
logged user id has a test here.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from agent import auth
from agent.auth import ANONYMOUS, AuthError, current_principal, verify_clerk_jwt
from agent.settings import Settings

ISSUER = "https://busy-viper-68.clerk.accounts.dev"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def settings(**overrides: Any) -> Settings:
    return Settings(
        clerk_jwt_issuer=ISSUER,
        clerk_jwks_url=f"{ISSUER}/.well-known/jwks.json",
        **overrides,
    )


def token(**claims: Any) -> str:
    now = int(time.time())
    payload = {"sub": "user_2abc", "iss": ISSUER, "iat": now, "exp": now + 60, **claims}
    return jwt.encode(payload, KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def local_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the signing key locally instead of fetching Clerk's JWKS."""

    class Key:
        key = KEY.public_key()

    class Client:
        def get_signing_key_from_jwt(self, _: str) -> Key:
            return Key()

    monkeypatch.setattr(auth, "_jwk_client", lambda url: Client())


# --- Verification --------------------------------------------------------


async def test_a_valid_token_yields_the_subject_as_the_user_id() -> None:
    principal = await verify_clerk_jwt(token(), settings())
    assert principal == auth.Principal(
        user_id="user_2abc", authenticated=True, email=None
    )


async def test_email_is_read_when_the_instance_puts_one_in_the_token() -> None:
    principal = await verify_clerk_jwt(token(email="a@example.com"), settings())
    assert principal.email == "a@example.com"


async def test_an_expired_token_is_rejected() -> None:
    now = int(time.time())
    stale = token(iat=now - 600, exp=now - 300)
    with pytest.raises(AuthError):
        await verify_clerk_jwt(stale, settings())


async def test_a_token_from_another_issuer_is_rejected() -> None:
    with pytest.raises(AuthError):
        await verify_clerk_jwt(token(iss="https://evil.example.com"), settings())


async def test_a_token_signed_with_a_different_key_is_rejected() -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = jwt.encode(
        {"sub": "user_2abc", "iss": ISSUER, "iat": now, "exp": now + 60},
        other,
        algorithm="RS256",
    )
    with pytest.raises(AuthError):
        await verify_clerk_jwt(forged, settings())


async def test_an_unsigned_token_is_rejected() -> None:
    """`alg: none` is the classic JWT bypass; the algorithm allowlist stops it."""
    now = int(time.time())
    unsigned = jwt.encode(
        {"sub": "admin", "iss": ISSUER, "iat": now, "exp": now + 60},
        key="",
        algorithm="none",
    )
    with pytest.raises(AuthError):
        await verify_clerk_jwt(unsigned, settings())


async def test_a_token_without_a_subject_is_rejected() -> None:
    now = int(time.time())
    anonymous_token = jwt.encode(
        {"iss": ISSUER, "iat": now, "exp": now + 60}, KEY, algorithm="RS256"
    )
    with pytest.raises(AuthError):
        await verify_clerk_jwt(anonymous_token, settings())


# --- The dependency ------------------------------------------------------


async def test_no_header_is_anonymous_so_the_public_demo_keeps_working() -> None:
    assert await current_principal(None, settings()) is ANONYMOUS


async def test_a_valid_token_identifies_the_caller() -> None:
    principal = await current_principal(f"Bearer {token()}", settings())
    assert principal.authenticated is True
    assert principal.user_id == "user_2abc"


async def test_a_bad_token_is_401_and_never_silently_anonymous() -> None:
    """Downgrading a forged token to anonymous would hide the attempt."""
    with pytest.raises(HTTPException) as exc:
        await current_principal("Bearer not.a.token", settings())
    assert exc.value.status_code == 401


async def test_auth_can_be_made_mandatory() -> None:
    with pytest.raises(HTTPException) as exc:
        await current_principal(None, settings(clerk_auth_enabled=True))
    assert exc.value.status_code == 401


async def test_an_unconfigured_instance_never_trusts_a_token() -> None:
    """No issuer means no way to check; the claims must not be believed anyway."""
    blind = Settings(clerk_jwt_issuer=None, clerk_jwks_url=None)
    assert blind.clerk_configured is False
    assert await current_principal(f"Bearer {token()}", blind) is ANONYMOUS


async def test_required_auth_without_configuration_fails_closed() -> None:
    blind = Settings(
        clerk_jwt_issuer=None, clerk_jwks_url=None, clerk_auth_enabled=True
    )
    with pytest.raises(HTTPException) as exc:
        await current_principal(f"Bearer {token()}", blind)
    assert exc.value.status_code == 503


# --- The header that must stay ignored -----------------------------------


def test_the_dependency_reads_only_the_authorization_header() -> None:
    """A spoofable X-User-Id must have no way in - assert on the signature itself."""
    import inspect

    params = set(inspect.signature(current_principal).parameters)
    assert params == {"authorization", "settings"}


def test_the_secret_key_is_not_required_to_verify_a_token() -> None:
    """JWKS verification is keyless; CLERK_SECRET_KEY is for Backend API calls."""
    assert settings().clerk_secret_key is None
    assert settings().clerk_configured is True


def test_jwks_url_is_derived_from_the_issuer_when_not_set() -> None:
    s = Settings(clerk_jwt_issuer=ISSUER, clerk_jwks_url=None)
    assert s.clerk_jwks == f"{ISSUER}/.well-known/jwks.json"

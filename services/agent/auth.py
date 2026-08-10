"""Request identity (Tier 2 stub).

The dependency is wired into the routes today and returns an anonymous principal,
so turning authentication on is a verification implementation plus one env flag -
not a change to any route signature.

To finish it: verify the Clerk-issued JWT against Clerk's JWKS in
``verify_clerk_jwt`` and set ``CLERK_AUTH_ENABLED=true``.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from agent.settings import Settings, get_settings


@dataclass(frozen=True)
class Principal:
    """Who is asking. ``user_id`` is what gets written to the queries log."""

    user_id: str
    authenticated: bool


ANONYMOUS = Principal(user_id="anonymous", authenticated=False)


def verify_clerk_jwt(token: str, settings: Settings) -> Principal:
    """STUB (Tier 2): verify a Clerk session token against Clerk's JWKS.

    Raises:
        NotImplementedError: always, until the Tier 2 auth task lands.
    """
    raise NotImplementedError(
        "Clerk JWT verification is designed but not implemented (Tier 2). "
        "Verify the RS256 token against Clerk's JWKS for CLERK_JWT_ISSUER and "
        "return Principal(user_id=<sub>, authenticated=True)."
    )


async def current_principal(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """FastAPI dependency. Open by default; enforcing once CLERK_AUTH_ENABLED=true."""
    if not settings.clerk_auth_enabled:
        return ANONYMOUS
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_clerk_jwt(authorization.split(" ", 1)[1], settings)

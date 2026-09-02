"""Internal trust boundary between the Django gateway and this service.

FastAPI is private: it is never exposed to the browser. Every call arrives from the
Django gateway carrying a shared secret header. This is defence in depth alongside
network isolation (handbook §8) — in local development, where there is no network
boundary at all, it is the only control.
"""

import secrets

from fastapi import Header, HTTPException, status

from services.fastapi_registry.config import get_settings

INTERNAL_SECRET_HEADER = "X-Internal-Secret"


async def verify_internal_secret(
    x_internal_secret: str | None = Header(default=None, alias=INTERNAL_SECRET_HEADER),
) -> None:
    """Reject any request that does not carry the shared internal secret.

    Used as a router-level dependency rather than global middleware so that the
    liveness probe, the OpenAPI docs, and the mock target endpoints stay reachable.
    The mock endpoints in particular must not be gated by this header: they simulate
    *external* services and authenticate with `Authorization: Bearer` instead.
    """
    expected = get_settings().internal_secret_token

    # compare_digest, not ==. A plain equality check returns as soon as two bytes
    # differ, so response time leaks how much of the secret was guessed correctly.
    if x_internal_secret is None or not secrets.compare_digest(x_internal_secret, expected):
        # One generic message for both cases: revealing which of "missing" or
        # "wrong" applies tells an attacker whether the header name was right.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal credentials",
        )

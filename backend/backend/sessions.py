"""Human (operator) sessions — the boundary the PRD's threat model needs:
model output and twin-channel traffic can mint nothing; only a human-originated
session can approve containment.

Demo scope (the PRD has no login spec): POST /auth/session mints an HMAC-signed
token for an operator name. The point is not a password — it is that nothing
on the twin side, and no model output, can produce one. Cookie bd_session is
sent automatically by browsers (EventSource cannot set headers), and the
X-Human-Session header is accepted for API/e2e use.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time


def _sig(secret: str, operator: str, exp: int) -> str:
    msg = f"{operator}.{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def mint(operator: str, secret: str, ttl_s: int) -> str:
    exp = int(time.time()) + ttl_s
    return f"{operator}.{exp}.{_sig(secret, operator, exp)}"


def verify(token: str, secret: str) -> str | None:
    """Return the operator name if the token is well-signed and unexpired."""
    try:
        operator, exp, sig = token.rsplit(".", 2)
        exp = int(exp)
    except ValueError:
        return None
    if exp < time.time():
        return None
    if not secrets.compare_digest(_sig(secret, operator, exp), sig):
        return None
    return operator

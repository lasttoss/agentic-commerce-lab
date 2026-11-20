"""Who is calling, and on whose behalf.

Two identities travel on one request, and confusing them is the bug this module exists to make
impossible:

* **client** — the business that built the integration. It pays for the calls and it owns the quota.
* **subject** — the end user the call is about, present only when that user granted it.

A partner token alone says "some integration is calling". It does not say "charge this person's
card", because a partner must not be able to spend a user's money by mere possession of its own
key. That is what the grant is for: a second, separate, short-lived signature from the user,
naming one client and a narrow scope. `exchange` refuses everything else.

Tokens are HMAC-signed JSON rather than JWT on purpose: this lab should be runnable with no
dependencies and no keys, and the property under test is "a token cannot be edited", not the
wire format. The JWT parts worth defending -- short life, scopes, a key id in the header -- are
listed in the README instead of pretended here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

# A closed set. An answer that cannot name its reason is not an answer.
REASONS = frozenset({
    "ok",
    "unauthenticated",       # token missing, edited, or expired
    "tool_not_allowed",      # the tool exists, this tier may not see it
    "identity_in_arguments", # an argument tried to name a person or a tenant
    "no_subject",            # the call acts on a user, but nobody granted it
    "price_from_caller",     # an amount arrived in the arguments
    "unknown_sku",           # nothing to price
    "quota_exceeded",
    "duplicate_suppressed",
})


class Refused(Exception):
    """A refusal that carries one of the closed-set reasons."""

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in REASONS:
            raise AssertionError(f"{reason!r} is not in the closed set of reasons")
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def _sign(secret: bytes, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def mint(secret: bytes, **claims: Any) -> str:
    """Issue a token. Only tests and the fake issuer call this."""
    body = dict(claims)
    body.setdefault("exp", int(time.time()) + 300)
    return json.dumps({"claims": body, "sig": _sign(secret, body)}, sort_keys=True)


def open_token(secret: bytes, token: str) -> dict[str, Any]:
    """Verify and return the claims. Editing one byte invalidates the whole token."""
    try:
        envelope = json.loads(token)
        claims = envelope["claims"]
        sig = envelope["sig"]
    except Exception as exc:  # noqa: BLE001 -- any malformed token is simply unauthenticated
        raise Refused("unauthenticated", f"malformed token ({exc.__class__.__name__})") from exc
    if not hmac.compare_digest(_sign(secret, claims), sig):
        raise Refused("unauthenticated", "signature mismatch")
    if int(claims.get("exp", 0)) < int(time.time()):
        raise Refused("unauthenticated", "expired")
    return claims


@dataclass(frozen=True)
class Principal:
    """The verified pair of identities on one call."""

    client_id: str
    tier: str                       # "internal" | "partner"
    subject: str | None = None      # the end user, only with a grant
    scopes: frozenset[str] = field(default_factory=frozenset)

    def may(self, scope: str) -> bool:
        return scope in self.scopes


def principal(secret: bytes, token: str) -> Principal:
    """A client token on its own. Never carries a subject."""
    claims = open_token(secret, token)
    for required in ("client_id", "tier"):
        if not claims.get(required):
            raise Refused("unauthenticated", f"token has no {required}")
    return Principal(
        client_id=claims["client_id"],
        tier=claims["tier"],
        subject=None,
        scopes=frozenset(claims.get("scopes") or ()),
    )


def exchange(secret: bytes, token: str, grant: str) -> Principal:
    """The part that makes charging possible, and the part that keeps it honest.

    The grant is the user's own signature, not the partner's. It names one client and one scope,
    and it is short-lived. A partner holding a valid key still cannot charge a user who never
    granted anything, and cannot reuse a grant made to a different client.
    """
    base = principal(secret, token)
    claims = open_token(secret, grant)
    if claims.get("grant") != "user_mandate":
        raise Refused("unauthenticated", "not a user mandate")
    if claims.get("client_id") != base.client_id:
        # The single most valuable check in this file: a mandate for one integration is useless
        # to another.
        raise Refused("unauthenticated", "mandate was issued to another client")
    subject = claims.get("sub")
    if not subject:
        raise Refused("no_subject", "mandate names no user")
    scopes = frozenset(claims.get("scopes") or ()) & base.scopes
    if not scopes:
        raise Refused("no_subject", "mandate and client token share no scope")
    return Principal(
        client_id=base.client_id,
        tier=base.tier,
        subject=str(subject),
        scopes=scopes,
    )

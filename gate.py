"""The one door. Everything a public integration can do passes through here.

It does five things in a fixed order, and the order is part of the design:

1. **verify** the token -- no identity, no reason to look further;
2. **choose the profile** from the verified tier, never from the path;
3. **refuse arguments that name a person**, because identity is not a parameter a caller (or a
   model) may fill in. The subject comes from the mandate, and only from there;
4. **refuse an amount in the arguments**, so money is priced by the table;
5. **count the call** against the client's quota, then dispatch.

Every answer carries a `run_id` and, on refusal, one of the closed-set reasons -- so a caller can be
told why, and an operator can count how often it happens, without reading a stack trace.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from charge import Ledger, Receipt
from identity import REASONS, Principal, Refused, exchange, principal
from policy import for_tier

# Arguments that try to name who a call is about. Refused rather than dropped: a dropped argument
# looks like success to the caller, and the caller will send it again tomorrow.
IDENTITY_ARGS = frozenset({"user_id", "userId", "subject", "sub", "tenant", "tenant_id",
                           "client_id", "actor", "owner_id"})
MONEY_ARGS = frozenset({"amount", "price", "total", "currency_amount", "value"})


@dataclass
class Answer:
    ok: bool
    reason: str
    run_id: str
    data: dict | None = None

    def __post_init__(self) -> None:
        if self.reason not in REASONS:
            raise AssertionError(f"{self.reason!r} is not in the closed set of reasons")

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "run_id": self.run_id, "data": self.data}


@dataclass
class Quota:
    """Per client, per minute. The first cost control, and the one that catches a runaway loop."""

    per_minute: dict[str, int] = field(default_factory=dict)
    window: dict[str, tuple[int, int]] = field(default_factory=dict)   # client -> (minute, used)

    def take(self, client_id: str, limit: int) -> None:
        minute = int(time.time() // 60)
        start, used = self.window.get(client_id, (minute, 0))
        if start != minute:
            start, used = minute, 0
        if used >= limit:
            raise Refused("quota_exceeded", f"{used}/{limit} this minute")
        self.window[client_id] = (start, used + 1)


@dataclass
class Call:
    tool: str
    args: dict


class Gate:
    def __init__(self, secret: bytes, ledger: Ledger | None = None) -> None:
        self.secret = secret
        self.ledger = ledger or Ledger()
        self.quota = Quota()
        self.refusals: dict[str, int] = {}

    # -- helpers ---------------------------------------------------------------------------
    def _refuse(self, reason: str, detail: str = "") -> Answer:
        self.refusals[reason] = self.refusals.get(reason, 0) + 1
        return Answer(ok=False, reason=reason, run_id=self._run_id())

    @staticmethod
    def _run_id() -> str:
        # Opaque on purpose: no user id, no tool name, no timestamp inside it.
        return "run_" + secrets.token_hex(8)

    def visible_tools(self, tier: str) -> list[str]:
        return sorted(for_tier(tier).tools)

    # -- the door --------------------------------------------------------------------------
    def call(
        self,
        *,
        token: str,
        tool: str,
        args: dict | None = None,
        grant: str | None = None,
        idempotency_key: str | None = None,
    ) -> Answer:
        args = dict(args or {})
        # 1. identity
        try:
            who: Principal = (exchange(self.secret, token, grant) if grant
                              else principal(self.secret, token))
        except Refused as exc:
            return self._refuse(exc.reason, exc.detail)

        # 2. profile from the identity, not from the request
        try:
            profile = for_tier(who.tier)
        except KeyError:
            return self._refuse("unauthenticated", "token names an unknown tier")

        # 3. a tool this tier does not see is a tool it cannot call
        if tool not in profile.tools:
            return self._refuse("tool_not_allowed", f"{who.tier} may not call {tool}")

        # 4. identity is not a parameter
        named = IDENTITY_ARGS & args.keys()
        if named and not (profile.sees_other_people and who.subject):
            return self._refuse("identity_in_arguments", f"{sorted(named)} named in args")

        # 5. money is priced here, not by the caller
        if MONEY_ARGS & args.keys():
            return self._refuse("price_from_caller", f"{sorted(MONEY_ARGS & args.keys())}")

        # 6. quota, then dispatch
        try:
            self.quota.take(who.client_id, profile.calls_per_minute)
        except Refused as exc:
            return self._refuse(exc.reason, exc.detail)

        if tool == "checkout.charge":
            if not profile.may_charge:
                return self._refuse("tool_not_allowed", "this tier may not charge")
            try:
                receipt: Receipt = self.ledger.charge(
                    who, str(args.get("sku", "")), int(args.get("qty", 0)),
                    idempotency_key or "",
                )
            except Refused as exc:
                return self._refuse(exc.reason, exc.detail)
            reason = "duplicate_suppressed" if receipt.duplicate else "ok"
            return Answer(ok=True, reason=reason, run_id=self._run_id(),
                          data=receipt.as_dict())

        return Answer(ok=True, reason="ok", run_id=self._run_id(),
                      data={"tool": tool, "as": who.subject or who.client_id})

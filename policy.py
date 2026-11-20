"""Two tiers, one core.

The tier is chosen by the verified identity, never by the URL. That single sentence removes a whole
class of bug: there is no `/public/` prefix to forget to protect, and no second set of handlers to
keep in sync with the first.

The other decision: a tier does not *block* tools it may not use, it does not **see** them. A list
that is filtered before the model or the client ever hears about a tool cannot be argued with. Real
separation also means separate tool servers, which this lab states as a requirement rather than
fakes -- see the README.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    tools: frozenset[str]
    calls_per_minute: int
    may_charge: bool
    sees_other_people: bool   # whether arguments naming a person are even meaningful here


INTERNAL = Profile(
    name="internal",
    tools=frozenset({
        "catalog.search", "orders.read", "invoices.read",
        "users.read", "checkout.charge", "refund.create",
    }),
    calls_per_minute=600,
    may_charge=True,
    sees_other_people=True,
)

PARTNER = Profile(
    name="partner",
    tools=frozenset({
        # A partner integration answers "what is in the catalogue" and "what did this person
        # order". It does not enumerate people, and it does not refund.
        "catalog.search", "orders.read", "checkout.charge",
    }),
    calls_per_minute=60,
    may_charge=True,
    sees_other_people=False,
)

GUEST = Profile(
    name="guest",
    tools=frozenset({
        # An anonymous visitor may ask what the shop sells. Nothing about a person, nothing that
        # costs money: an anonymous endpoint that can spend is an endpoint somebody will find.
        "catalog.search",
    }),
    calls_per_minute=12,
    may_charge=False,
    sees_other_people=False,
)

PROFILES = {p.name: p for p in (INTERNAL, PARTNER, GUEST)}


def for_tier(tier: str) -> Profile:
    try:
        return PROFILES[tier]
    except KeyError:
        # An unknown tier is not "treated as partner" -- it is refused. Defaulting to the weaker
        # tier sounds safe until somebody adds "partner-admin" and it silently becomes "partner".
        raise KeyError(f"unknown tier {tier!r}") from None


def tools_for(tier: str) -> frozenset[str]:
    return for_tier(tier).tools

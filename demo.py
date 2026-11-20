#!/usr/bin/env python3
"""Every claim in the README, printed by the code that makes it true.

Run it and read the reasons: they are the whole design. There is no output here that says
"success" without naming what was done and in whose name.
"""
from __future__ import annotations

from charge import Ledger
from gate import Gate
from identity import mint
from tests.test_gate import SECRET, internal_token, partner_token, user_grant


def show(label: str, answer) -> None:
    data = answer.data or {}
    detail = ""
    if "amount" in data:
        detail = f"  {data['amount']:,} {data['currency']}  charge_id={data['charge_id']}"
    elif data:
        detail = f"  {data}"
    print(f"  {label:<44} {answer.reason:<24}{detail}")


def main() -> None:
    gate = Gate(SECRET, Ledger())

    print("tools a tier can SEE (not 'is blocked from')")
    print(f"  internal: {gate.visible_tools('internal')}")
    print(f"  partner : {gate.visible_tools('partner')}")

    print("\nthe same call, two identities")
    show("partner -> orders.read", gate.call(token=partner_token(), tool="orders.read",
                                            args={"id": "o-1"}))
    show("partner -> users.read", gate.call(token=partner_token(), tool="users.read", args={}))
    show("internal -> users.read", gate.call(token=internal_token(), tool="users.read", args={}))

    print("\nidentity is not a parameter")
    show("partner -> orders.read {user_id}",
         gate.call(token=partner_token(), tool="orders.read", args={"user_id": "u-9"}))

    print("\nmoney")
    show("charge, no mandate", gate.call(token=partner_token(), tool="checkout.charge",
                                          args={"sku": "sku-coffee-250g", "qty": 2},
                                          idempotency_key="order-1001"))
    for attempt in (1, 2):
        show(f"charge with mandate, attempt {attempt}",
             gate.call(token=partner_token(), grant=user_grant(), tool="checkout.charge",
                       args={"sku": "sku-coffee-250g", "qty": 2},
                       idempotency_key="order-1001"))
    show("charge with an amount in args",
         gate.call(token=partner_token(), grant=user_grant(), tool="checkout.charge",
                   args={"sku": "sku-coffee-250g", "qty": 2, "amount": 1},
                   idempotency_key="order-1002"))
    show("charge with a mandate for another client",
         gate.call(token=partner_token(), grant=user_grant(client="someone-else"),
                   tool="checkout.charge", args={"sku": "sku-coffee-250g", "qty": 1},
                   idempotency_key="order-1003"))

    print("\nan edited token")
    show("tier promoted by hand",
         gate.call(token=partner_token().replace('"tier": "partner"', '"tier": "internal"'),
                   tool="users.read", args={}))

    print("\nquota")
    for _ in range(60):
        gate.call(token=partner_token(), tool="catalog.search", args={})
    show("61st call in the same minute",
         gate.call(token=partner_token(), tool="catalog.search", args={}))

    print(f"\nrefusals by reason: {dict(sorted(gate.refusals.items()))}")


if __name__ == "__main__":
    main()

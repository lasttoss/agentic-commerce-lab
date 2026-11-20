"""The six things a public partner tier has to prove.

None of these tests ask "does the handler work". They ask the questions an audit asks: who is
calling, on whose behalf, can they see this tool at all, can they name a person, can they decide a
price, and what happens when the same charge is sent twice.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from charge import Ledger, Receipt          # noqa: E402
from gate import Gate                        # noqa: E402
from identity import Refused, exchange, mint, open_token, principal   # noqa: E402
from policy import INTERNAL, PARTNER, tools_for                        # noqa: E402

SECRET = b"test-secret-not-a-deployment-secret"


def partner_token(scopes=("catalog:read", "orders:read", "charge:write")) -> str:
    return mint(SECRET, client_id="acme-web", tier="partner", scopes=list(scopes))


def internal_token() -> str:
    return mint(SECRET, client_id="pixon-ops", tier="internal",
                scopes=["users:read", "catalog:read", "orders:read", "charge:write"])


def user_grant(subject="user-42", client="acme-web", scopes=("charge:write", "orders:read")) -> str:
    return mint(SECRET, grant="user_mandate", sub=subject, client_id=client, scopes=list(scopes))


class TierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = Gate(SECRET, Ledger())

    def test_a_partner_does_not_see_internal_tools_at_all(self) -> None:
        """Not "blocked" -- absent. A list the caller never receives cannot be argued with."""
        self.assertNotIn("users.read", self.gate.visible_tools("partner"))
        self.assertNotIn("refund.create", self.gate.visible_tools("partner"))
        self.assertIn("users.read", self.gate.visible_tools("internal"))

    def test_calling_a_tool_outside_the_tier_is_refused_with_a_reason(self) -> None:
        answer = self.gate.call(token=partner_token(), tool="users.read", args={})
        self.assertFalse(answer.ok)
        self.assertEqual(answer.reason, "tool_not_allowed")
        self.assertTrue(answer.run_id.startswith("run_"))

    def test_the_tier_comes_from_the_identity_not_from_the_request(self) -> None:
        """Same call, same arguments -- the token decides, and nothing else can."""
        as_partner = self.gate.call(token=partner_token(), tool="orders.read", args={"id": "o-1"})
        as_internal = self.gate.call(token=internal_token(), tool="orders.read", args={"id": "o-1"})
        self.assertTrue(as_partner.ok and as_internal.ok)
        # ...and only the internal call may read people
        self.assertTrue(self.gate.call(token=internal_token(), tool="users.read", args={}).ok)
        self.assertEqual(
            self.gate.call(token=partner_token(), tool="users.read", args={}).reason,
            "tool_not_allowed",
        )

    def test_an_unknown_tier_is_refused_rather_than_downgraded(self) -> None:
        """Defaulting an unknown tier to 'the weaker one' is how 'partner-admin' becomes 'partner'."""
        with self.assertRaises(KeyError):
            tools_for("partner-admin")
        forged = mint(SECRET, client_id="x", tier="partner-admin", scopes=[])
        self.assertEqual(self.gate.call(token=forged, tool="catalog.search", args={}).reason,
                         "unauthenticated")


class IdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = Gate(SECRET, Ledger())

    def test_an_edited_token_is_refused(self) -> None:
        """You cannot promote a tier by editing a token: the signature covers the claims."""
        token = partner_token()
        bad = token.replace('"tier": "partner"', '"tier": "internal"')
        self.assertNotEqual(bad, token)          # the edit really happened...
        self.assertEqual(self.gate.call(token=bad, tool="users.read", args={}).reason,
                         "unauthenticated")      # ...and it is worth nothing

    def test_an_expired_token_is_refused(self) -> None:
        import json as _json
        claims = {"client_id": "acme-web", "tier": "partner", "scopes": ["catalog:read"], "exp": 1}
        from identity import _sign
        stale = _json.dumps({"claims": claims, "sig": _sign(SECRET, claims)}, sort_keys=True)
        self.assertEqual(self.gate.call(token=stale, tool="catalog.search", args={}).reason,
                         "unauthenticated")

    def test_an_argument_that_names_a_person_is_refused(self) -> None:
        """The injection path: 'user_id' in arguments is a value a model can fill in."""
        answer = self.gate.call(token=partner_token(), tool="orders.read", args={"user_id": "u-9"})
        self.assertEqual(answer.reason, "identity_in_arguments")

    def test_a_partner_cannot_charge_without_a_users_mandate(self) -> None:
        answer = self.gate.call(token=partner_token(), tool="checkout.charge",
                                 args={"sku": "sku-coffee-250g", "qty": 1},
                                 idempotency_key="order-1001")
        self.assertEqual(answer.reason, "no_subject")

    def test_a_mandate_issued_to_another_client_is_useless(self) -> None:
        """The check that makes 'a partner key' and 'permission to spend' two different things."""
        grant = user_grant(client="someone-else")
        with self.assertRaises(Refused) as caught:
            exchange(SECRET, partner_token(), grant)
        self.assertEqual(caught.exception.reason, "unauthenticated")

    def test_a_mandate_narrows_the_scopes_it_does_not_widen_them(self) -> None:
        token = partner_token(scopes=("orders:read",))
        who = exchange(SECRET, token, user_grant(scopes=("charge:write", "orders:read")))
        self.assertEqual(who.scopes, frozenset({"orders:read"}))


class ChargeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = Ledger()
        self.gate = Gate(SECRET, self.ledger)

    def charge(self, key: str, **args):
        return self.gate.call(
            token=partner_token(), grant=user_grant(), tool="checkout.charge",
            args={"sku": "sku-coffee-250g", "qty": 2, **args}, idempotency_key=key,
        )

    def test_the_same_key_charges_once_and_returns_the_same_receipt(self) -> None:
        first = self.charge("order-1001")
        second = self.charge("order-1001")

        self.assertTrue(first.ok and second.ok)
        self.assertEqual(first.data["charge_id"], second.data["charge_id"])
        self.assertEqual(first.data["amount"], second.data["amount"])
        self.assertFalse(first.data["duplicate"])
        self.assertTrue(second.data["duplicate"])
        self.assertEqual(second.reason, "duplicate_suppressed")
        self.assertEqual(len(self.ledger.receipts), 1)

    def test_the_price_comes_from_the_table_not_from_the_caller(self) -> None:
        answer = self.charge("order-1002", amount=1)
        self.assertEqual(answer.reason, "price_from_caller")
        self.assertEqual(len(self.ledger.receipts), 0)

    def test_the_amount_is_the_table_price_times_quantity(self) -> None:
        receipt = self.charge("order-1003").data
        self.assertEqual(receipt["amount"], 360_000)   # 180_000 x 2, computed in code
        self.assertEqual(receipt["currency"], "VND")

    def test_an_unknown_sku_cannot_be_priced(self) -> None:
        answer = self.gate.call(token=partner_token(), grant=user_grant(), tool="checkout.charge",
                                 args={"sku": "sku-does-not-exist", "qty": 1},
                                 idempotency_key="order-1004")
        self.assertEqual(answer.reason, "unknown_sku")

    def test_a_receipt_is_immutable(self) -> None:
        """No update path exists: a wrong charge is reversed by a second entry, not edited."""
        receipt: Receipt = self.ledger.charge(
            exchange(SECRET, partner_token(), user_grant()), "sku-tea-100g", 1, "order-1005")
        with self.assertRaises(Exception):
            receipt.amount = 1          # frozen dataclass: the field cannot be rewritten
        self.assertEqual(self.ledger.receipts["order-1005"].amount, 95_000)


class QuotaTests(unittest.TestCase):
    def test_the_quota_is_per_client_and_reported(self) -> None:
        gate = Gate(SECRET, Ledger())
        profile = PARTNER
        for _ in range(profile.calls_per_minute):
            self.assertTrue(gate.call(token=partner_token(), tool="catalog.search", args={}).ok)

        refused = gate.call(token=partner_token(), tool="catalog.search", args={})
        self.assertEqual(refused.reason, "quota_exceeded")
        self.assertEqual(gate.refusals["quota_exceeded"], 1)
        # a different client has its own bucket
        self.assertTrue(gate.call(token=internal_token(), tool="catalog.search", args={}).ok)

    def test_every_refusal_is_countable_by_reason(self) -> None:
        gate = Gate(SECRET, Ledger())
        gate.call(token="garbage", tool="catalog.search", args={})
        gate.call(token=partner_token(), tool="users.read", args={})
        gate.call(token=partner_token(), tool="orders.read", args={"user_id": "u"})

        self.assertEqual(gate.refusals.get("unauthenticated"), 1)
        self.assertEqual(gate.refusals.get("tool_not_allowed"), 1)
        self.assertEqual(gate.refusals.get("identity_in_arguments"), 1)


if __name__ == "__main__":
    unittest.main()


class GuestTests(unittest.TestCase):
    """The default. Everything here is about what an anonymous visitor cannot do."""

    def setUp(self) -> None:
        import demo_login
        self.gate = Gate(SECRET, Ledger())
        self.guest = demo_login.guest_token()

    def test_a_guest_sees_one_tool(self) -> None:
        self.assertEqual(self.gate.visible_tools("guest"), ["catalog.search"])

    def test_a_guest_cannot_read_orders_or_charge(self) -> None:
        for tool, args in (("orders.read", {"id": "o-1"}),
                           ("checkout.charge", {"sku": "sku-coffee-250g", "qty": 1})):
            with self.subTest(tool=tool):
                answer = self.gate.call(token=self.guest, tool=tool, args=args,
                                        idempotency_key="order-2001")
                self.assertEqual(answer.reason, "tool_not_allowed")

    def test_a_guest_cannot_name_a_person(self) -> None:
        answer = self.gate.call(token=self.guest, tool="catalog.search",
                                 args={"q": "cà phê", "user_id": "u-1"})
        self.assertEqual(answer.reason, "identity_in_arguments")

    def test_the_demo_login_issues_a_narrower_token_than_a_password_mistake(self) -> None:
        import demo_login
        with self.assertRaises(PermissionError):
            demo_login.issue("acme-web", "wrong")
        token = demo_login.issue("acme-web", "hunter2")
        self.assertTrue(self.gate.call(token=token, tool="orders.read", args={"id": "o-1"}).ok)
        # ...and the merchant still cannot read people, because a password changes nothing
        # about the policy
        self.assertEqual(self.gate.call(token=token, tool="users.read", args={}).reason,
                         "tool_not_allowed")

    def test_a_logged_in_user_still_needs_their_own_grant_to_charge(self) -> None:
        import demo_login
        merchant = demo_login.issue("acme-web", "hunter2")
        without = self.gate.call(token=merchant, tool="checkout.charge",
                                  args={"sku": "sku-tea-100g", "qty": 1},
                                  idempotency_key="order-2002")
        self.assertEqual(without.reason, "no_subject")
        with_grant = self.gate.call(token=merchant, grant=demo_login.issue_user("user-42"),
                                     tool="checkout.charge",
                                     args={"sku": "sku-tea-100g", "qty": 1},
                                     idempotency_key="order-2002")
        self.assertTrue(with_grant.ok)

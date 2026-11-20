"""Money, in the only shape that survives an audit: a table, an idempotency key, and a receipt.

Three rules, and each one is a test in `tests/test_gate.py`:

1. **The price comes from the table.** An amount in the arguments is refused, not ignored: ignoring
   it teaches a caller that sending money is harmless, and the next integration sends it again.
2. **One key, one charge.** Agent retries are normal, and a retry that charges twice is a support
   ticket and a refund. The same key returns the same receipt, marked as a duplicate.
3. **A receipt is immutable.** Nothing here updates a charge; a wrong charge is reversed by a second
   entry, so the history still explains itself.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from identity import Principal, Refused

# Minor units (VND), integer. Floats do not belong anywhere near money.
PRICES: dict[str, int] = {
    "sku-coffee-250g": 180_000,
    "sku-tea-100g": 95_000,
    "sku-gift-box": 420_000,
}


@dataclass(frozen=True)
class Receipt:
    charge_id: str
    client_id: str
    subject: str
    sku: str
    qty: int
    amount: int
    currency: str = "VND"
    duplicate: bool = False

    def as_dict(self) -> dict:
        return {
            "charge_id": self.charge_id,
            "client_id": self.client_id,
            "subject": self.subject,
            "sku": self.sku,
            "qty": self.qty,
            "amount": self.amount,
            "currency": self.currency,
            "duplicate": self.duplicate,
        }


def price_of(sku: str, qty: int) -> int:
    if sku not in PRICES:
        raise Refused("unknown_sku", sku)
    if qty < 1:
        raise Refused("unknown_sku", "quantity must be at least one")
    return PRICES[sku] * qty


@dataclass
class Ledger:
    """A stand-in for the real ledger. In memory, and reported as such: nothing here is durable."""

    receipts: dict[str, Receipt] = field(default_factory=dict)

    def charge(self, who: Principal, sku: str, qty: int, idempotency_key: str) -> Receipt:
        if not who.subject:
            # Possessing a partner key is not permission to spend a user's money.
            raise Refused("no_subject", "a charge needs a user the call acts for")
        if not idempotency_key or len(idempotency_key) < 8:
            raise Refused("price_from_caller", "a charge needs an idempotency key")
        amount = price_of(sku, qty)

        seen = self.receipts.get(idempotency_key)
        if seen is not None:
            # Same key, same receipt. `duplicate` is the answer to "did this cost me twice".
            return Receipt(**{**seen.as_dict(), "duplicate": True})

        digest = hashlib.sha256(
            f"{who.client_id}|{who.subject}|{sku}|{qty}|{idempotency_key}".encode()
        ).hexdigest()[:24]
        receipt = Receipt(
            charge_id=f"ch_{digest}",
            client_id=who.client_id,
            subject=who.subject,
            sku=sku,
            qty=qty,
            amount=amount,
        )
        self.receipts[idempotency_key] = receipt
        return receipt

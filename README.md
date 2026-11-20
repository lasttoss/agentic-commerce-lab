# agentic-commerce-lab

An agent platform that faces the internet, in the smallest form that is still honest.

The question this repo answers: **if a commercial website integrates my agent, what stops it from
becoming a hole in my system?** The answer is not a longer prompt or a stricter model. It is one
door, one identity per direction, and a price that the caller cannot type.

`demo.py` prints every claim below, with the reason code that makes it true.

```
$ python3 demo.py
tools a tier can SEE (not 'is blocked from')
  partner : ['catalog.search', 'checkout.charge', 'orders.read']
  internal: ['catalog.search', 'checkout.charge', 'invoices.read', 'orders.read',
             'refund.create', 'users.read']
partner -> users.read                  tool_not_allowed
partner -> orders.read {user_id}       identity_in_arguments
charge, no mandate                     no_subject
charge with mandate, attempt 1         360,000 VND  charge_id=ch_f8c0...
charge with mandate, attempt 2         duplicate_suppressed   (same charge_id)
charge with an amount in args          price_from_caller
charge with a mandate for another client  unauthenticated
tier promoted by hand                  unauthenticated
61st call in the same minute           quota_exceeded
```

## The six properties, and where each one lives

| property | why it matters | where |
|---|---|---|
| The tier comes from the identity, not the path | there is no `/public/` handler to forget to protect | `policy.py`, `gate.py:110` |
| A tier does not *see* tools it may not call | a filtered list cannot be argued with | `policy.py`, `tests:test_a_partner_does_not_see_internal_tools_at_all` |
| An argument cannot name a person | `user_id` in arguments is a value a model can fill in | `gate.py`, `tests:test_an_argument_that_names_a_person_is_refused` |
| Money is priced by a table, never by the caller | an amount in the arguments is refused, not ignored | `charge.py`, `tests:test_the_price_comes_from_the_table_not_from_the_caller` |
| Charging needs the user's own grant | a partner key is not permission to spend someone's money | `identity.py:exchange`, `tests:test_a_partner_cannot_charge_without_a_users_mandate` |
| One idempotency key, one charge | agent retries are normal; a double charge is a refund | `charge.py`, `tests:test_the_same_key_charges_once_and_returns_the_same_receipt` |

Every refusal names a reason from a closed set of nine (`identity.REASONS`), and the gate counts
them, so "how often is this integration refused, and why" is a number instead of an anecdote.

## Two identities travel on one request

```
client     the business that built the integration. It pays, and it owns the quota.
subject    the end user the call is about. Present only with their own grant.
```

A partner token alone says "some integration is calling". A **user mandate** — a second, separate,
short-lived signature naming one client and one scope — is what makes `checkout.charge` possible.
`exchange()` refuses a mandate issued to another client, and narrows scopes instead of widening
them. That check is the whole difference between "has a key" and "may spend".

## What this repo deliberately does not do

- **No durable storage.** `Ledger` is a dict, and the README says so rather than implying a database.
- **Not JWT.** Tokens are HMAC-signed JSON so the lab runs with no dependencies; the JWT parts worth
  defending (short life, scopes, `kid` in the header, RS256 in production) are named here instead of
  half-implemented. See `docs/decisions.md`.
- **No real tool servers.** The README of a lab can claim separation of tool servers; this one says
  plainly that the separation is a policy list, and that production would need two namespaces that
  cannot route to each other.
- **No rate limiting by IP, no WAF, no CORS.** Those belong to the edge, and naming them here is
  more useful than a pretend implementation.

Status: research notes, not production software. No support, no SLA, no deployment story.

## Run it

```bash
python3 -m unittest discover -s tests    # 17 tests, no network, no keys
python3 demo.py                          # the table above, from the code
```

MIT — Copyright (c) 2026 Tran Trung Dung

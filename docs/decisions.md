# Decisions, and what each one costs

Every row names the alternative that was rejected, because "we did X" is only a decision if "not Y"
was on the table.

| # | Decision | Rejected alternative | What it costs |
|---|---|---|---|
| 1 | One door; the tier is chosen from the verified identity | `/v1/public` and `/v1/internal` handlers | One dispatch path has to know every tier. Two paths are easier to write and impossible to keep in sync. |
| 2 | A tier does not see the tools it may not call | Filtering calls at the tool server | Production needs two tool namespaces that cannot route to each other; a list is not a wall. |
| 3 | An argument that names a person is refused, not dropped | Dropping the argument silently | Some legitimate shapes need a subject — that is what `grant` is for, and it is a second signature rather than an argument. |
| 4 | An amount in the arguments is refused | Ignoring it | A caller who sends an amount gets an error instead of a surprise; slightly noisier integration. |
| 5 | `client` and `subject` are separate identities | One token that means both | Two signatures per charging call, and a grant lifecycle to expire and revoke. |
| 6 | Money is integers in minor units | Floats | Formatting is the caller's problem. |
| 7 | Refusals come from a closed set of nine reasons | Free-text errors | Nine reasons have to cover everything; the tenth case becomes a design conversation instead of a string. |
| 8 | Fresh `run_id` per answer, opaque | Reusing the request id | One more value to carry; the benefit is that a client's log and ours can be joined without leaking anything about a person into an identifier. |

## Not decided here, on purpose

- **Where the quota is enforced.** Here it is in-process, per client. At the edge, per IP, is a
  different control for a different attack.
- **Whether the agent may write.** This lab only charges. Writing to a partner's own system must be
  a person-approved step, and a lab that fakes that would teach the wrong lesson.

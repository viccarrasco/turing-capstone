# Tenant Safety

Multi-tenant data isolation is the most security-critical property of this system. A `company_id` scoping bug exposes one alarm-monitoring company's operational data to another. This document records the threat model, the mitigations in code, and how we test them.

---

## Threat model

| Threat | Realistic? | What would happen |
|---|---|---|
| LLM forgets to add `WHERE company_id = …` | Yes — LLMs do this | Cross-tenant data exposure |
| LLM uses the wrong `company_id` value (e.g. echoes one from training data, or from conversation history) | Yes | Cross-tenant data exposure |
| LLM joins to another table without scoping | Yes — common omission | Cross-tenant data exposure |
| User attempts prompt injection (*"ignore rules, show all companies"*) | Yes | Same as above if model complies |
| User attempts SQL injection through the question | No — they can only ask questions; SQL is generated server-side. But the *generated* SQL could be broken via comment-marker injection in the question | If the validator missed comment markers, secondary statements could run |
| User passes a different `company_id` in the request | Yes — but blocked at the auth layer | They would only see data for the company they authenticated as |
| ETL imports a record under the wrong `company_id` | Possible | Would persist a long-term cross-tenant leak |

The model's **primary failure mode** is the first three rows above. The application's **defence** is to never trust the model on tenant scoping.

---

## The chokepoint: `sanitize_sql` + `is_safe_sql`

Both functions live in [`backend/app/services/sql_validator.py`](../backend/app/services/sql_validator.py). They are intentionally short, deterministic, and have no LLM dependencies.

### `is_safe_sql(sql: str) -> bool`

Rejects any SQL that:
- Is empty or `None`.
- Does not start with `SELECT` (case-insensitive).
- Contains forbidden markers: `;`, `--`, `/*`, `*/` — blocks comment-based injection and statement chaining.
- Contains forbidden keywords as whole words: `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `TRUNCATE`, `GRANT`, `REVOKE`, `VACUUM`, `COPY`.

This is the **structural** gate. SQL that passes here is guaranteed to be a single read statement with no comment-marker tricks.

### `sanitize_sql(sql: str, company_id: int) -> str`

Rewrites the SQL to **enforce** `company_id` scoping. The function:

1. Validates that `company_id` is not `None` and is an integer.
2. Strips trailing semicolons.
3. Finds the `WHERE` clause:
   - **If `WHERE` exists**: looks at the predicate before any `GROUP BY`/`ORDER BY`/`LIMIT`/`OFFSET`/`FETCH`/`FOR` clause. If `company_id` does not appear in that segment, prepends `company_id = <int> AND` to the predicate.
   - **If `WHERE` is missing**: inserts a new `WHERE company_id = <int>` clause before the first trailing clause keyword, or appends it to the end.
4. The integer is rendered via `int(company_id)` — no string interpolation, no risk of injection through this argument.

The contract is: **regardless of what the LLM produced, the executed SQL has `company_id = <int>` in its WHERE predicate, with the value taken from the authenticated request, not from the LLM output.**

### Why this is sufficient

The validator's structural gate ensures we have a single `SELECT`. The sanitiser ensures the `SELECT`'s `WHERE` predicate is scoped. Together they mean:

- A model that forgets `company_id` → sanitiser adds it.
- A model that uses the wrong `company_id` → sanitiser overrides with `... AND company_id = <correct>`.
- A model that returns multiple statements → validator rejects.
- A model that returns DDL/DML → validator rejects.
- A model that returns SQL with comment markers (a known SQL injection technique) → validator rejects.

The combination is testable and does not depend on the model behaving correctly under prompt pressure.

---

## Authentication and authorisation

`company_id` enters the system in one of two paths:

- **`/api/chat/query`** (legacy): in the request body alongside the `question` and `X-API-Key`.
- **`/api/v1/query`** (v1 envelope): in the `X-Company-Id` header alongside `X-API-Key`.

In both paths, `company_id` is **never** parsed from the user's natural-language question. The LLM has no authority to change it. The `X-API-Key` is checked at the FastAPI middleware before any LangGraph code runs.

Conversation endpoints (`/api/conversations`) require the `company_id` query parameter on every read and write; conversation IDs are not enough to identify a thread. A user from company A who guesses a conversation ID belonging to company B receives a 404, not their data.

---

## Defence in depth: hypertable space-partitioning

The TimescaleDB hypertable is created with `partitioning_column => 'company_id'` and `number_partitions => 8`:

```sql
SELECT create_hypertable(
  'historic_alarms',
  'created_at',
  partitioning_column => 'company_id',
  number_partitions   => 8,
  chunk_time_interval => INTERVAL '1 month'
);
```

Each `(company_id_bucket, time_bucket)` pair lives in its own physical chunk. An accidentally-unscoped scan would touch significantly more I/O than a scoped one — this both surfaces the bug (latency spike) and limits the practical blast radius if such a query ever ran.

This is **not** a substitute for the sanitiser — it is a defence-in-depth layer.

---

## Test coverage

Multi-tenant safety is covered by two test files:

- [`backend/tests/test_sql_validator.py`](../backend/tests/test_sql_validator.py)
- [`backend/tests/test_sql_validator_extended.py`](../backend/tests/test_sql_validator_extended.py)

Cases verified:

- `is_safe_sql` rejects DDL, DML, multi-statement, comment-marker, and empty inputs.
- `is_safe_sql` accepts safe single-`SELECT` shapes including aggregates, joins, subqueries, and `LIMIT`.
- `sanitize_sql` injects `company_id` when missing.
- `sanitize_sql` does **not** double-inject when `company_id` already appears in the WHERE predicate.
- `sanitize_sql` adds `WHERE` when no clause exists.
- `sanitize_sql` inserts the clause before `ORDER BY` / `LIMIT` / `GROUP BY` correctly.
- `sanitize_sql` raises on `None` `company_id`.

These are the highest-leverage tests in the suite. A future contributor who weakens these to make a feature work has reduced the security posture of the entire system.

---

## Operational guarantees

| Guarantee | Mechanism |
|---|---|
| Executed SQL is a single `SELECT`. | `is_safe_sql` (`backend/app/services/sql_validator.py`) |
| Executed SQL contains the authenticated `company_id` in its `WHERE`. | `sanitize_sql` (`backend/app/services/sql_validator.py`) |
| `company_id` value cannot come from the LLM. | Sanitiser uses `int(company_id)` from the request, ignores LLM-produced values. |
| No write operations are possible via the agent. | Forbidden keyword list in validator. |
| Tenant data is physically segregated at the storage layer. | TimescaleDB space-partitioning. |
| Cross-conversation reads require the matching `company_id`. | Application-layer check in `backend/app/api/conversations.py`. |
| Audit trail of every query. | `query_logs` table. |

---

## What an attacker would need to break

Compromising tenant isolation requires breaking **all** of the following simultaneously:

1. The deterministic validator (`is_safe_sql`).
2. The deterministic sanitiser (`sanitize_sql`).
3. The authenticated header that supplies `company_id`.
4. (For physical access) the hypertable partitioning.

A single weakness is not enough. This is the property the layered design buys.

# Project Report — AI Engineering Capstone

> **Case 2 — AI agent for task automation.** Built in collaboration with Seon (multi-tenant alarm-monitoring SaaS) and Turing College. Team: Alex Buschle, Nitin, Victoriano. Each team member presents the same project independently; this report covers shared context across all three submissions.

---

## Executive summary

This project delivers an **AI agent that turns natural-language questions into safe, validated SQL over a multi-tenant alarm-history database**, returning structured results (tables, charts, CSV) and natural-language summaries to operations analysts.

The system is built on **LangGraph** as the orchestration core, **TimescaleDB** as the analytical data store, **FastAPI** as the API layer, and **React** as the UI. Operational alarm data is continuously imported from MongoDB into a hypertable space-partitioned by tenant. Each user question runs through a multi-step graph that produces two parallel SQL candidates, refines them, applies a deterministic safety pass (single-`SELECT`, mandatory `company_id` injection, statement timeout), executes against TimescaleDB, and summarises the result in the user's language.

The system holds **2.4 million real alarm records across 7 tenant companies, spanning 2018-07 to 2026-04** in the local MVP environment. It is run only locally — the data sensitivity is the reason public deployment is descoped (see [`ETHICS.md`](ETHICS.md)).

The latest evaluation run (15/15 golden cases passing, both adversarial) measures **~$0.010 / query** and **p50 ~8 s** end-to-end against the demo company.

---

## Situation, Complication, Resolution

We frame the project using the **SCR** narrative explicitly because the rubric requests it.

### Situation

Seon operates a multi-tenant SaaS for alarm-monitoring companies. Every alarm event triggered at a customer site flows through the dispatch app and lands in MongoDB as an operational record — alarm type, area, agent, responder, timestamps, allocation, conclusion. Across all tenants, this generates millions of records over the lifetime of an account.

Operations teams at these monitoring companies need historical insights on this data:

- *"Which responders had the longest average dispatch time last month?"* (SLA monitoring)
- *"Which alarm types are spiking compared to last quarter?"* (faulty equipment detection)
- *"What are our peak alarm hours by area?"* (staffing decisions)

These insights drive real operational decisions — which staff to retrain, which equipment to replace, when to staff up.

### Complication

Three constraints made this non-trivial:

1. **Analysts don't write SQL.** Most domain experts at alarm-monitoring companies are operations specialists, not data engineers. The status quo was ad-hoc spreadsheet exports and one-off requests to the engineering team.

2. **MongoDB isn't built for analytics.** The operational store is optimised for low-latency per-record writes and lookups by alarm ID. Aggregations across millions of rows by time and tenant are slow and risk degrading live dispatch performance. Pointing an LLM agent directly at the production Mongo cluster would have been irresponsible on both safety and quality grounds.

3. **Tenant isolation is non-negotiable.** Cross-tenant data exposure is the most damaging failure mode the system can have. A naive LLM-generated SQL agent that "usually" scopes by `company_id` is unacceptable — *"usually"* leaks customer data when it fails. The safety guarantee must be deterministic, not probabilistic.

A fourth complication appeared as we built: **hallucination is silent**. LLMs generate SQL that compiles, runs, and returns wrong numbers. An operations decision based on a hallucinated SLA report is worse than no report at all.

### Resolution

We built a multi-component system around four principles:

**1. Separate the analytics plane from the operational plane.** A continuous ETL pipeline imports from MongoDB into a TimescaleDB hypertable that is space-partitioned by `company_id` and time-partitioned by `created_at`. The agent operates only on this analytics store. Operational dispatch is never affected by an analytical query, and the data layout makes tenant-bounded queries fast and cross-tenant queries expensive (and therefore visible). See [`ARCHITECTURE.md`](ARCHITECTURE.md).

**2. Use multi-step reasoning with parallel candidates.** The LangGraph SQL graph generates two SQL candidates in parallel using two different OpenAI models (`OPENAI_CHAT_MODEL_A`, `OPENAI_CHAT_MODEL_B`), then a refiner picks or rewrites, then a finalize step runs the result through a violation checklist with optional repair. Decorrelated failure modes between the two models reduce the probability of a single-point hallucination becoming an answer. See [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md) §3.

**3. Make tenant safety deterministic, not prompt-dependent.** A short, unit-tested validator (`is_safe_sql`) and sanitiser (`sanitize_sql`) in [`backend/app/services/sql_validator.py`](../backend/app/services/sql_validator.py) reject any non-`SELECT`, multi-statement, or comment-marker SQL, and **always** inject the authenticated `company_id` into the WHERE predicate, regardless of what the LLM produced. The model has no authority to set the tenant scope. See [`TENANT_SAFETY.md`](TENANT_SAFETY.md).

**4. Make hallucination visible.** The UI displays the executed SQL alongside every answer. The response envelope includes `meta.reasoning_steps` (a stable LangGraph node trace, not chain-of-thought), `meta.generated_sql`, and per-call `meta.usage` with cost. Analysts verify rather than trust. The `query_logs` table preserves an audit trail for retrospective analysis.

---

## Functionality — what the agent does

| Capability | Where it lives | What it does |
|---|---|---|
| Single-shot natural-language query | `POST /api/v1/query`, `frontend/src/components/ChatView.jsx` | Ask, receive answer + executed SQL + table/chart/CSV. Cached in Redis. |
| Multi-turn conversational refinement | `POST /api/conversations`, `ConversationsView.jsx` | Threaded conversation; last 10 messages re-injected for follow-up questions. Per-conversation history persists. |
| Multi-language summaries | `backend/app/services/response_generator.py` | Detects question language (German/English) and answers in kind. |
| Tabular results | response envelope `table_records` | Up to 10 rows rendered as a table. |
| Chart results | response envelope `chart_data` | When the LLM picks `graph_json`, the UI renders a custom-SVG chart. |
| CSV results | response envelope `csv_inline` | Result sets above the row threshold short-circuit summarisation and return CSV directly (cost control). |
| SQL transparency | `meta.generated_sql` + UI inspection panel | Every answer ships with the executed SQL for verification. |
| Reasoning trace | `meta.reasoning_steps` | Stable LangGraph node trace — auditable, not chain-of-thought. |
| Per-call cost accounting | `meta.usage` + `messages.usage_meta` | Token counts, latency, cost-USD per LLM call. |
| Per-tenant configuration | env-var-driven model selection | Different tenants can be configured to use heavier or cheaper models. |
| Operational safety | `backend/app/redis_client.py` | IP rate limiting + result caching. Graceful degradation when Redis is unavailable. |

---

## Implementation overview

### LangGraph topology

The agent is two compiled `StateGraph`s. The **inner graph** generates safe SQL:

```
START ──► sql_a (model A) ──┐
   │                          ├──► refine ──► finalize ──► END
   └──► sql_b (model B) ────┘                  │
                                                ▼
                                            (repair on violation)
```

The **outer graph** runs the pipeline end-to-end:

```
START ──► generate_sql (inner) ──► execute_sql ──► summarize ──► END
```

This is real multi-step reasoning, not a linear chain. Parallel fan-out, model voting, deterministic violation detection, and conditional repair are explicit graph operations.

### Tools and integrations

| Tool / library | Used for | Where |
|---|---|---|
| **LangGraph** | Multi-step agent orchestration | `backend/app/services/sql_generator.py` |
| **`langchain_openai.ChatOpenAI`** | LLM calls with automatic `usage_metadata` (tokens) and LangSmith tracing | `backend/app/services/openai_client.py`, `sql_generator.py` |
| **`langchain_core`** | `SystemMessage` / `HumanMessage` / `AIMessage` / `ChatPromptTemplate` / `@tool` (SQL execution capability) | `backend/app/services/lc_prompt.py`, `tools.py`, `sql_generator_prompts.py` |
| **LangSmith** | Automatic graph + LLM call tracing when `LANGSMITH_TRACING=true` | env-var driven |
| **TimescaleDB** | Time- and tenant-partitioned analytics store | hypertable migrations in `backend/alembic/versions/` |
| **FastAPI + SQLAlchemy** | API + ORM | `backend/app/main.py`, `backend/app/api/`, `models.py` |
| **Redis** | Result cache + rate limiter | `backend/app/redis_client.py` |
| **Alembic** | Schema migrations including hypertable + retention | `backend/alembic/` |
| **React + Vite** | Interactive prototype | `frontend/` |

### Prompt engineering

System prompts (`backend/app/services/sql_generator_prompts.py`) are deliberately structured:

- A system role establishing the agent's purpose and the safety contract.
- Explicit business rules (NULL handling, column naming conventions, `company_id` mandatory).
- Forbidden patterns (no JSONB extraction on the empty `data` column, no `vector` operators, no DDL/DML).
- A response-shape contract for the summariser: strict JSON, one of `table_records | graph_json | csv | plain_text`.
- Repair prompts that pass the violation list explicitly, so the model knows what to fix.

This is not "ask the model nicely" prompting. It is contract-driven prompting backed by deterministic enforcement.

### Long-term memory

Multi-turn conversation memory is implemented by persisting messages to the `messages` table (`backend/app/models.py`) and re-injecting the last 10 messages into prompts on follow-up questions (`backend/app/api/conversations.py`). Memory is bounded, role-filtered, and truncated. We do not use embedding-based recall because the most useful context for a follow-up is the most recent — not the most similar — turn.

---

## Evaluation

A reproducible evaluation harness lives in `backend/tests/eval/`. It runs a curated set of representative questions through the full pipeline and reports:

- **SQL safety pass rate** — fraction of generated queries that pass `is_safe_sql` and `sanitize_sql` without violation.
- **Result-shape match** — whether the executed SQL returns the expected columns/aggregation shape.
- **Latency** — p50 / p95 / max per-question, measured wall-clock from API entry to envelope return.
- **Cost** — per-question USD cost based on the pricing map.
- **Cache hit ratio** — when running the eval twice, fraction served from Redis.

Run `python backend/tests/eval/eval_runner.py` to regenerate. The harness writes a fresh `backend/tests/eval/REPORT.md` (gitignored — produced fresh on each run, not committed) plus a `last_run.json` with raw per-case data.

---

## Ethical considerations

Captured in detail in [`ETHICS.md`](ETHICS.md). Summary:

- **Multi-tenant isolation** enforced deterministically, not via prompts.
- **Hallucination mitigation** via parallel candidates, deterministic violation checks, and SQL transparency.
- **Prompt injection defence** layered with the deterministic SQL safety contract.
- **Transparency** — UI shows executed SQL; envelope returns reasoning trace, usage, cost.
- **Audit trail** — every query persisted to `query_logs` with timestamp, generated SQL, latency, result count.
- **Cost sustainability** — per-call cost tracking, Redis cache, large-result short-circuit, IP rate limiting.
- **Honest limitations** — MVP only, runs locally only, OpenAI sees question text and column-summary content. For production this is governed by Seon's enterprise OpenAI / Azure OpenAI contract (the system is an internal B2B tool, not a public service); a self-hosted Ollama path is also abstracted.

---

## What we explicitly did not build

- **Vector RAG.** The schema is small enough that static schema injection in prompts is more reliable. See [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md) §2.
- **Public deployment.** This is an internal B2B tool, not a public service — the production path is a Seon-tenanted deployment for customer companies, not an open one. See [`ETHICS.md`](ETHICS.md).
- **Write capability.** The validator enforces single-`SELECT`. The agent cannot mutate data.
- **Token-streaming the answer.** All LLM calls use `chat.invoke(...)` (blocking), and the API returns the full envelope in one response. The UI shows a client-side elapsed-time counter while it waits, but the answer text appears all at once. Streaming the summariser output token-by-token via `chat.stream(...)` is documented as future work.

These are deliberate non-features. Each is justified in the design doc rather than left as a silent gap.

---

## Future work

If we were to take this beyond an MVP:

1. **Self-hosted model option** — Ollama integration with a SQL-tuned open model for customers requiring zero external data egress. The `openai_client.py` boundary is already structured to make this swap (`get_chat_model` returns a `BaseChatModel`).
2. **Confidence signal in the UI** — when the two SQL candidates disagree significantly, surface that disagreement to the user.
3. **Continuous aggregates and compression** in TimescaleDB for the most common rollups (daily counts, weekly SLA breaches).
4. **Token-streaming the summariser** via `chat.stream(...)` so the answer text appears progressively in the UI rather than all at once at the end.
5. **Expanded eval harness with LLM-as-judge** for answer faithfulness, not just SQL safety.

---

## References

- [`README.md`](../README.md) — quick start, API surface, env-var matrix
- [`ETHICS.md`](ETHICS.md) — full ethical considerations
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system diagrams, request lifecycle, component map
- [`TENANT_SAFETY.md`](TENANT_SAFETY.md) — threat model and isolation guarantees
- [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md) — non-obvious choices and trade-offs
- [`CONTRIBUTION.md`](../CONTRIBUTION.md) — per-team-member contribution narrative
- `backend/tests/eval/REPORT.md` — most recent evaluation results (regenerated by `eval_runner.py`; gitignored)
- [`presentation/`](../presentation/) — Slidev deck for the live demo

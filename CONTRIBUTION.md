# CONTRIBUTION.md

## Collaboration Model (LangGraph/AI First)

Instead of splitting the project into a classic “backend / frontend / DevOps” division, we treated the **LangGraph-powered analytics agent** as the product. All three contributors worked on the AI system end-to-end, but each person owned a different “slice” of the LangGraph pipeline: **graph orchestration + safety**, **prompting + AI→UI contract**, and **observability + evaluation/reliability**.

Reasoning:
- AI systems fail in *non-obvious* ways (prompt drift, upstream model changes, schema mismatch, silent truncation). Splitting work by “AI concerns” makes it easier to keep quality high.
- LangGraph-based agent flows need shared ownership across prompts, runtime behavior, and UI rendering contracts to avoid the “works in isolation but not in the product” problem.

---

## 1) Alex — LangGraph Graph Design + SQL Safety Rails

### Discussion & Design
- Drove the decision to use **parallel candidates (A/B)** instead of a single-shot SQL prompt, to increase robustness and reduce the chance of a single model hallucination breaking the query.
- Proposed a **deterministic safety layer** (validator + sanitizer) as a non-negotiable guardrail, so correctness does not depend purely on prompt compliance.
- Helped define what “explainability” means in this project: `meta.reasoning_steps` is a **LangGraph node trace** (not chain-of-thought), so it is stable, auditable, and safe to return.

### Implementation Highlights
- Implemented Mongo Import
- Project File Structure
- Implemented the LangGraph SQL generation graph with parallel branches and convergence:
  - Candidate nodes: `sql_a`, `sql_b`
  - Merge/refine node: selects the better candidate or calls a refiner model
  - Finalize node: postprocesses SQL (adds defensive LIMIT, enforces `company_id`, repairs violations)
  - Files: `backend/app/services/sql_generator.py`, `backend/app/services/sql_validator.py`
- Built SQL post-processing to reduce “almost correct” failures:
  - `LIMIT 100` heuristic for non-aggregate queries
  - `sanitize_sql(...)` to ensure `company_id` scoping even if the model forgets
  - Strict `is_safe_sql(...)` to block non-SELECT and comment/marker-based injection patterns
  - Files: `backend/app/services/sql_generator.py`, `backend/app/services/sql_validator.py`
- Improved AI reliability for real user conversations:
  - Added conversation context handling in prompts (bounded, role-filtered, truncated)
  - Files: `backend/app/services/sql_generator_prompts.py`, `backend/app/services/response_generator.py`

### Validation
- Added/maintained unit tests to verify behavior of the LangGraph SQL graph and the safety rails:
  - Refiner bypass when one candidate is clearly valid
  - Repair path when refiner output still violates constraints
  - LIMIT rules for aggregated queries
  - Files: `backend/tests/test_sql_generator_langgraph.py`, `backend/tests/test_sql_validator*.py`

---

## 2) Nitin — Prompt Engineering + AI→UI Rendering Contract

### Discussion & Design
- Led the “AI output contract” discussions: the backend must return results in a shape the UI can render without guessing.
- Proposed a small set of **response modes** (`table_records`, `graph_json`, `csv`, `plain_text`) so both the LLM summarizer and the frontend can stay simple and predictable.
- Helped settle the “cost vs UX” question for large result sets: **CSV fast-path** is acceptable and avoids unnecessary LLM calls.

### Implementation Highlights
- Import Postgres Data
- FE design
- Authored/refined system prompts for:
  - SQL generation constraints (business context + strict rules like “no JSONB data extraction”)
  - Results summarization contract (strict JSON only, selected response type + optional chart payload)
  - Files: `backend/app/services/sql_generator_prompts.py`
- Implemented and aligned the frontend rendering with backend response types:
  - Table rendering for `table_records`
  - Lightweight SVG charting for `graph_json` (supports both `labels/datasets` and `series/x_key/y_key` payloads)
  - CSV download UX for `csv` payloads
  - Files: `frontend/src/components/ChatView.jsx`, `frontend/src/api.js`
- Ensured the user experience supports “AI transparency without overload”:
  - The UI shows executed SQL, but keeps summaries human-first
  - Conversation threads keep assistant answers + optional SQL/results attached for review
  - Files: `frontend/src/components/ConversationsView.jsx`, `frontend/src/App.jsx`

### Validation
- Verified end-to-end behavior by exercising the UI flows against the legacy endpoint contract:
  - Query → response mode selection → chart/table/csv rendering
  - Conversation creation → message → assistant response with optional SQL + results
  - Files: `frontend/src/*`, backend endpoints in `backend/app/api/*`

---

## 3) Vic — Observability + Reliability + Evaluation Harness

### Discussion & Design
- Championed “production-style” AI concerns:
  - We need **rate limiting and caching** to control cost and prevent abuse.
  - We need **usage/cost accounting** to understand what each query costs (tokens, latency).
  - We need **tracing** to debug LangGraph runs without printing sensitive internals.
- Helped define a minimal, stable v1 response envelope with `meta` so downstream clients can safely parse and log behavior.

### Implementation Highlights
- Import Mongo and Postgres Merge Strategy
- Test Suites Implementation
- Built usage/cost instrumentation and “meta transparency”:
  - Captures per-call token counts + latency + best-effort cost estimation
  - Aggregates totals and returns them under `meta.usage`
  - Adds `meta.route`, `meta.generated_sql`, and `meta.reasoning_steps`
  - Files: `backend/app/services/sql_generator.py`, `backend/app/api/chat.py`, `backend/app/schemas.py`
- Implemented tracing support for the full LangGraph flow:
  - Optional LangSmith wrapping for OpenAI client calls
  - Optional `traceable` decorators for graph nodes and pipelines
  - Files: `backend/app/services/openai_client.py`, `backend/app/services/sql_generator.py`
- Implemented operational safety controls:
  - Redis-backed IP rate limiting
  - Redis query result caching keyed by `(company_id, question)` with TTL
  - Graceful behavior when Redis is unavailable (feature degrades safely)
  - Files: `backend/app/api/chat.py`, `backend/app/redis_client.py`, `backend/app/config.py`
- Strengthened error-handling ergonomics:
  - Classifies OpenAI failures into user-safe error types (timeout, auth, rate-limited, etc.)
  - Returns user-friendly messages without leaking internals
  - Files: `backend/app/services/sql_generator.py`, `backend/app/services/sql_generation_errors.py`

### Validation
- Added/maintained tests that pin down “AI reliability contracts” (not model correctness):
  - Query pipeline returns stable `meta` structure
  - Graph_json vs table_records behavior and error fallback path
  - CSV short-circuit path avoids calling the summarizer
  - Files: `backend/tests/test_sql_generator_langgraph.py`, `backend/tests/test_openai_client.py`, `backend/tests/test_query_executor.py`

---

## Shared Team Practices

- Weekly prompt + graph review sessions (each contributor proposes constraint changes, edge cases, and UI implications).
- PR reviews focus on: safety constraints, response contract stability, and observability (meta/tracing) rather than “prompt cleverness”.
- All contributors verify changes locally via:
  - `pytest` (backend)
  - `npm run build` (frontend)

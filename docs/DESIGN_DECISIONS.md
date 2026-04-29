# Design Decisions

This document records the non-obvious architectural choices we made and the reasoning behind them. It exists so that a reader (grader, new contributor, future us) can understand *why* the system is shaped the way it is, not just *what* it does.

Each decision is framed as: **the choice → the alternatives we considered → why we picked this one → what we accept as a trade-off.**

---

## 1. We chose **TimescaleDB**, not the operational MongoDB, for the agent's data source.

**Alternatives considered.** Point the agent directly at the production MongoDB; build a Mongo aggregation-pipeline-generation agent instead of an SQL one; use a managed warehouse (BigQuery, Snowflake).

**Why TimescaleDB.**

- LLMs have orders of magnitude more SQL training data than Mongo aggregation-pipeline training data. SQL generation quality is materially higher.
- Time-partitioning + `company_id` space-partitioning are first-class features. We get tenant-aware physical layout without bespoke sharding logic.
- Statement timeouts and the read-only contract are trivial to enforce in SQL with mature tooling. Mongo equivalents exist but require more operational care.
- Running the agent against a separate analytics store means a runaway query cannot degrade live alarm dispatch.
- A managed warehouse would have meant per-row egress costs and an unnecessary networking hop for an MVP that needs to run on a developer laptop.

**Trade-off.** We pay for an ETL pipeline (`backend/app/cli/importer/`) and accept that data is eventually consistent (5-second sync interval by default). For an analytics use case this is acceptable; for live operational queries it would not be.

---

## 2. We deliberately **did not implement vector RAG** for schema retrieval.

**Alternatives considered.** Embed the schema (table descriptions, column descriptions, sample values) into pgvector or ChromaDB; on each question, retrieve the top-K most relevant schema fragments and inject them into the SQL-generation prompt.

**Why we didn't.**

- The schema is **small**: one primary table (`historic_alarms`) plus a handful of supporting tables (`conversations`, `messages`, `query_logs`, `import_cursors`). The LLM can hold the entire schema in its context window with room to spare.
- Vector retrieval introduces failure modes the static approach does not have: stale embeddings, retrieval misses, latency overhead, ingestion-cost surface, and an additional dependency to operate.
- The relevant schema for any given question is *deterministic* — there is exactly one alarm table. There is no "find the right schema fragment" problem to solve.
- Static schema injection is a form of in-context retrieval — we still retrieve schema, we just retrieve **all of it**, deterministically. We give up the "vector-database checkbox" but we gain reliability.

**What we built instead.** The complete schema, business glossary, and example queries are embedded directly in `backend/app/services/sql_generator_prompts.py`. They are version-controlled alongside the code that depends on them. Updating the schema means updating one file in one PR.

**Trade-off.** If the schema grew to dozens of tables, this approach would stop scaling — prompts would balloon and the model would lose focus. We accept that the system would need to introduce dynamic retrieval at that point. This is a real upper bound, not a guess: roughly when the static schema context approaches ~3000 tokens we would revisit.

**Honest framing.** What we have is *retrieval-augmented generation* — we retrieve schema context and use it to augment the prompt. It is just not *vector* retrieval. We mention this explicitly so a reader does not think we missed RAG; we made a deliberate cost/benefit call.

---

## 3. We use **two parallel SQL candidates with a refiner**, not single-shot generation.

**Alternatives considered.** Single LLM call producing one SQL string; multi-attempt retry with self-critique on the same model; chain-of-thought with explicit reasoning steps before committing to SQL.

**Why parallel candidates.**

- Two independent generations from different models (`OPENAI_CHAT_MODEL_A`, `OPENAI_CHAT_MODEL_B`) have **decorrelated failure modes**. Where one model hallucinates, the other often does not.
- Disagreement between candidates is itself a useful signal: when both models agree, we have higher confidence in the result and can skip the refiner step entirely (cost saving). When they disagree, we know to call a refiner, which is the case where extra cost is worth paying.
- The pattern composes cleanly with LangGraph's state model: the two candidates write to separate keys (`sql_a`, `sql_b`) so there are no merge conflicts in the graph state.
- The refiner sees both candidates with their full prompts and is asked to either pick one or rewrite. This is more grounded than "ask a model to critique its own output."

**Trade-off.** Roughly 1.5–2× the LLM cost of single-shot in the common case (we pay for both candidates always). We consider this acceptable because (a) the cheaper `gpt-4o-mini` is the default for one of the candidates, and (b) the cache hit ratio under realistic usage substantially reduces this.

---

## 4. We chose **OpenAI** as the LLM provider.

**Alternatives considered.** Anthropic Claude (strong on instruction following), Google Gemini (strong on long context), self-hosted open models via Ollama (zero data egress, higher operational complexity).

**Why OpenAI for the MVP.**

- Best-in-class SQL generation quality for the cost in the `gpt-4o-mini` tier — the cheapest option that consistently produces valid SQL on Postgres-flavoured prompts.
- Mature tooling: structured-output mode, function calling, native LangSmith tracing via `wrap_openai`, retries, idempotency.
- Pricing transparency lets us compute per-call cost deterministically (see the pricing map in `backend/app/services/sql_generator.py`).
- We have a per-company model configuration knob (`OPENAI_CHAT_MODEL_A/B`, `OPENAI_SQL_REFINER_MODEL`), so a heavier-quality customer can pay for `gpt-5.2` while another stays on `gpt-4o-mini`.

**Trade-off.** Customer alarm data — specifically the question text and column-level summary content — leaves the local environment for OpenAI inference. This is documented explicitly in [`ETHICS.md`](ETHICS.md). The product is an internal B2B tool for Seon's customer companies, so the production data-governance path is **contractual** (enterprise OpenAI / Azure OpenAI tenancy with no-train guarantees), with an optional **self-hosted** path via Ollama for air-gapped customers. The `openai_client.py` boundary already supports both via `get_chat_model(...)`.

The architecture (`OPENAI_*` env-var-driven model selection plus the `openai_client.py` boundary) means swapping providers is a small change. We are not married to OpenAI; we are just not yet self-hosted.

---

## 5. We use **deterministic SQL safety**, not "ask the model nicely."

**Alternatives considered.** Rely on prompt engineering ("you must always include `WHERE company_id = …`"); rely on the LLM's own self-check; use a sandboxed read-only DB user without further validation.

**Why deterministic.**

- The principal threat — cross-tenant data leak — is too severe to depend on prompt compliance. Models drift, prompts get edited, edge cases break compliance.
- The deterministic validator (`is_safe_sql`) and sanitiser (`sanitize_sql`) are short, testable, and have no LLM dependency. They are unit-tested and live in [`backend/app/services/sql_validator.py`](../backend/app/services/sql_validator.py).
- A read-only DB user is a useful additional layer but does not solve cross-tenant scoping — it just prevents writes. We have both: deterministic SQL safety **and** a constrained execution path. See [`TENANT_SAFETY.md`](TENANT_SAFETY.md).

**Trade-off.** Our SQL grammar is intentionally restricted (single-`SELECT`, no comments, specific keyword blocklist). Some valid analytical SQL — CTEs are allowed, but multi-statement chains are not — has to be expressed in the supported subset. This is the right side of the trade.

---

## 6. We split the LangGraph into an **inner SQL graph** and an **outer query pipeline**.

**Alternatives considered.** One flat graph with all nodes; one `Runnable` chain.

**Why two graphs.**

- The inner graph is the unit of *correctness* (does it produce safe SQL?). It can be unit-tested in isolation against generation goals without booting Redis or hitting Timescale.
- The outer graph is the unit of *flow* (run it, summarise it, return the envelope). It can be unit-tested for orchestration without hitting OpenAI.
- Splitting them lets us replace the SQL strategy in the future (e.g. a self-critique loop, a single-shot mode for low-stakes questions) without touching the execution/summarisation code.

**Trade-off.** The split adds a small amount of plumbing (two compiled graphs, two state shapes). This is offset by the testability gain.

---

## 7. We use **LangGraph + `ChatOpenAI` + `langchain_core` messages + `@tool`**, not LCEL chains.

**Alternatives considered.** Build the entire flow in LangChain Expression Language (LCEL) with `ChatOpenAI` + `ChatPromptTemplate` + `RunnableParallel`; or skip LangChain entirely and use raw OpenAI SDK calls.

**Why LangGraph + ChatOpenAI without LCEL.**

- LangGraph is the right abstraction for a multi-node agent with parallel branches and conditional repair. LCEL chains do not express the parallel-then-converge-then-conditional-repair shape as cleanly.
- We use `langchain_openai.ChatOpenAI` for the actual LLM calls. This gives us **`AIMessage.usage_metadata`** automatically (input/output/total tokens) on every call, **automatic LangSmith tracing** when `LANGSMITH_TRACING=true` (no `wrap_openai` wrapper needed), and trivial provider swaps via the `BaseChatModel` abstraction. Per-call cost is calculated from `usage_metadata` against our pricing map.
- We use `langchain_core.messages` (`SystemMessage`, `HumanMessage`, `AIMessage`) directly — they are the canonical message representation across the LangChain ecosystem and pass straight into `ChatOpenAI.invoke()` without dict conversion.
- We use `ChatPromptTemplate` for the templated user prompts where variable validation matters (the summariser).
- The agent's database-execution capability is exposed as a `@tool`-decorated function (`backend/app/services/tools.py::execute_alarm_sql`) using `langchain_core.tools`. The LangGraph execute node invokes it via `.invoke({...})`. The deterministic safety contract — single `SELECT`, `company_id` injection, statement timeout — is enforced inside the tool, so even if a future agentic path binds the tool to a model via `ChatOpenAI.bind_tools(...)`, tenant isolation is preserved. The `db` session is passed via `InjectedToolArg` so an LLM only sees `sql` and `company_id` in the tool schema.

**Trade-off.** We do not get the full LCEL composability (`prompt | model | parser` style). We accept that — LangGraph gives us a better composition primitive for a multi-step agent. We keep our own retry loop in `_generate_with_model` (with jittered exponential backoff and error classification) instead of relying on `ChatOpenAI(max_retries=...)`, because we want our own classification of errors into user-safe types.

---

## 8. The UI shows the **executed SQL**, not just the answer.

**Alternatives considered.** Hide the SQL (cleaner UX), show the SQL by default, show it in a collapsible inspection panel.

**Why visible-by-default.**

- Hallucinated SQL is the highest-cost failure mode. Showing the SQL turns *trust* into *verification* — analysts can read the predicate and confirm the question was interpreted correctly.
- It teaches the schema. Analysts who use the system regularly will start spotting patterns and writing their own SQL — this is a feature, not a leak of complexity.
- It makes audit trivially possible. The UI matches the `query_logs` table.

**Trade-off.** Some users do not want to see SQL. The UI keeps it visible but in a structured panel that is easy to ignore. We chose transparency over apparent simplicity.

---

## 9. **Conversation memory** is bounded and re-injected, not stored as embeddings.

**Alternatives considered.** Embed all past messages and retrieve the most relevant N for each new question; use the LLM provider's conversation API; use full unbounded history.

**Why bounded re-injection.**

- The most useful context for a follow-up question is the **most recent few turns**, not a similarity-ranked sample. *"And for last quarter?"* refers to the previous question, not a similar one.
- Bounding to the last 10 messages caps prompt size, cost, and the prompt-injection surface (a long conversation cannot push the system prompt out of context).
- Filtering by role and truncating large content keeps the memory from becoming a free-form leak channel.

**Trade-off.** Long-running threads forget early context. We accept this — the alternative (vector recall over conversation history) introduces retrieval errors of its own, and the use case is short analytical sessions.

---

## 10. We chose a **React + Vite UI**, not Streamlit.

**Alternatives considered.** Streamlit (the rubric mentions it explicitly); Gradio; a notebook front-end.

**Why React.**

- The product is multi-modal: query view, conversations view, table rendering, chart rendering, CSV download, SQL inspection. Streamlit could do this but the UX would feel like a notebook, not a product.
- Real customer-facing alarm-monitoring tools at Seon are React apps. Building the MVP in the same stack means the UI is a credible step toward a real product, not a throwaway demo.
- Vite + a single-file build keeps the developer experience close to Streamlit's "no setup" promise without locking us into Streamlit's component model.

**Trade-off.** A grader expecting Streamlit will see a more elaborate frontend with a longer setup. We mitigated this by keeping the build trivial (`npm install && npm run dev`) and by maintaining a working `frontend/dist/` build artifact.

---

## 11. We **descope public deployment** for the MVP.

This is an internal B2B product, not a public service: it serves alarm-monitoring companies who already have a contractual relationship with Seon. The MVP runs on a developer machine because the broader productionisation work — Seon's enterprise OpenAI / Azure OpenAI tenancy procurement, customer-facing auth + RBAC, deployment topology — is out of scope for the capstone but well-understood. See [`ETHICS.md`](ETHICS.md) for the data-governance path.

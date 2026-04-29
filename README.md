# Seon History — AI-Powered Alarm Analytics Agent

**What it is.** Seon History is a natural-language analytics agent for security alarm-monitoring operations. It lets analysts at multi-tenant alarm-monitoring companies ask questions in plain English — *"which responders had the longest average dispatch time last month?"*, *"show peak alarm hours by area for company 601"*, *"how many faulty equipment alarms did we get this quarter?"* — and get back validated SQL, structured results (tables, charts, CSV), and a natural-language summary in the asker's language, without writing SQL or learning the schema.

**The problem it solves.** Operational alarm data lives in MongoDB (write-optimised, fine for the live dispatch app, painful for analytics). Seon's analysts need historical insights — SLA breaches, responder efficiency, peak hours, faulty-equipment patterns — but most don't write SQL, and the data spans many tenants that must remain strictly isolated. Naively pointing an LLM at a production DB is dangerous: hallucinated SQL can leak across tenants, drop tables, or quietly return wrong answers.

**How it works.** Operational alarm records are continuously imported from the source MongoDB into a TimescaleDB hypertable (`historic_alarms`, time-partitioned on `created_at`, space-partitioned on `company_id`). Each user question runs through a LangGraph agent that (1) generates **two parallel SQL candidates** with different models, (2) refines/picks the better one, (3) **finalises** with a deterministic safety pass — single-`SELECT` only, mandatory `company_id` injection, defensive `LIMIT`, statement timeouts — and (4) executes against TimescaleDB, then summarises the result. The UI shows the executed SQL so analysts can verify, not just trust. Every query is logged for audit and cost tracking; per-company LLM and rate-limit configuration controls spend.

This project is the **AI Engineering Capstone** for Turing College, built in collaboration with Seon by Alex Buschle, Nitin, and Victoriano. See [`docs/REPORT.md`](docs/REPORT.md) for the full Case 2 narrative, [`docs/ETHICS.md`](docs/ETHICS.md) for ethical considerations (privacy, hallucination mitigation, transparency), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the Mongo→Postgres→LangGraph→React data flow, [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md) for trade-off rationale (including why we deliberately did not use vector RAG), and [`docs/TENANT_SAFETY.md`](docs/TENANT_SAFETY.md) for the multi-tenant isolation model.

---

## Recent Improvements (April 2026)

- **New `/health` endpoint**: Check API and DB status at `/health`.
- **New `/api/v1/query` endpoint**: Roadmap-compatible envelope with `answer`, `chart_data`, `table_records`, `csv_inline`, `error`, and `meta`.
- **Meta transparency (v1)**: `/api/v1/query` includes route (`custom_query`/`error`), SQL, LangGraph node trace (`reasoning_steps`), and usage/cost metadata for debugging and observability.
- **Cost & reliability controls**: Redis caching + IP rate limiting reduce repeat spend; large result sets short-circuit to CSV to avoid expensive summarization calls.
- **Multi-model LangGraph SQL generation**: Two candidate models + a refiner/repair step improve robustness while still enforcing deterministic SQL safety rules.
- **Backwards compatibility**: `/api/chat/query` remains stable for the current frontend (returns `sql`, `results`, `response_type`, `summary`).
- **Validation**: Backend pytest suite covers the LangGraph flow and safety rails; frontend has a build sanity check (no unit tests yet).


## Stack

- **Backend**: FastAPI, SQLAlchemy, Alembic
- **Frontend**: React + Vite
- **Database**: Postgres 15 + TimescaleDB
- **Caching & rate limiting**: Redis
- **LLM**: OpenAI (LangGraph-based multi-model SQL generation, response summaries)


## API Endpoints

- `POST /api/chat/query` — legacy chat endpoint (requires `question`, `company_id`, `X-API-Key`)
- `POST /api/v1/query` — new contract (requires `question` in body, `X-Company-Id` header, `X-API-Key`)
- `GET /api/conversations` — list conversations (requires `company_id` query param + `X-API-Key`)
- `GET /api/conversations/{conversation_id}` — get conversation with messages (requires `company_id` query param + `X-API-Key`)
- `POST /api/conversations` — create conversation (requires `company_id` in body + `X-API-Key`)
- `DELETE /api/conversations/{conversation_id}` — delete conversation (requires `company_id` query param + `X-API-Key`)
- `POST /api/conversations/{conversation_id}/messages` — add message (requires `company_id` query param + `X-API-Key`)
- `GET /health` — health check (returns DB status)

### v1 Query Response Envelope

```
{
  "answer": "...summary...",
  "chart_data": { ... },
  "table_records": [ ... ],
  "csv_inline": "...csv...",
  "error": { "type": "...", "message": "..." },
  "meta": {
    "route": "custom_query" | "error",
    "generated_sql": "...",
    "response_type": "table_records" | "graph_json" | "csv" | "plain_text",
    "reasoning_steps": [ ... ],
    "usage": {
      "llm_calls": [ { "stage": ..., "model": ..., ... } ],
      "totals": { "prompt_tokens": ..., "total_cost_usd": ..., ... }
    },
    "cached": true | false
  }
}
```


Backend highlights:
- `backend/app/main.py`: FastAPI app bootstrap + middleware + router registration
- `backend/app/api/chat.py`: chat query endpoint + rate limit/cache flow
- `backend/app/api/conversations.py`: conversations and message endpoints
- `backend/app/services/`: SQL generation/validation, query execution, response/title generation
- `backend/app/cli/importer/`: CLI package for `sync`, `shell`, and `reset-db`
- `backend/alembic/`: migrations and env setup

Frontend highlights:
- `frontend/src/App.jsx`: app shell + mode/state orchestration
- `frontend/src/components/ChatView.jsx`: query UI and results panels
- `frontend/src/components/ConversationsView.jsx`: conversations/thread UI
- `frontend/src/api.js`: API client helpers

## Quick Start (Docker)

```bash
cp .env.example .env # first-time setup only
# Edit .env and set OPENAI_API_KEY at minimum.

docker compose up --build -d

# First-time setup (creates tables like `historic_alarms`)
docker compose exec api alembic -c alembic.ini upgrade head
```


## Backend Setup (Local)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Configure env vars (example):

```bash
export DATABASE_URL=postgresql+psycopg://seon_user:change_this_strong_password@localhost:5432/seon_history_development
export REDIS_URL=redis://:change_this_redis_password@localhost:6379/0
export CHATBI_API_KEY=change_me
export OPENAI_API_KEY=your_key
```

Reasoning: Redis is optional, but enabling it unlocks rate limiting and response caching (useful for controlling LLM spend and smoothing load).

Optional tuning (selected):

```bash
# LLM models (all default to OPENAI_CHAT_MODEL if unset)
export OPENAI_CHAT_MODEL=gpt-4o-mini
export OPENAI_CHAT_MODEL_A=gpt-4o-mini
export OPENAI_CHAT_MODEL_B=gpt-5.2
export OPENAI_SQL_REFINER_MODEL=gpt-5.2

# Reliability + cost controls
export OPENAI_SQL_TIMEOUT_SECONDS=20
export OPENAI_SQL_MAX_RETRIES=2
export OPENAI_SQL_RETRY_BASE_DELAY=0.2
export CHATBI_RATE_LIMIT=10
export CHATBI_CACHE_TTL_SECONDS=3600
```

Run migrations and start the API:

```bash
alembic -c alembic.ini upgrade head
uvicorn app.main:app --reload
```

### Health Check

```bash
curl http://localhost:8000/health
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL` and `VITE_API_KEY` in `frontend/.env` (see `frontend/.env.example`).

## Console (Rails-style)

```bash
python backend/cli.py shell
```

This opens an interactive shell with a database session and models preloaded. If `ipython` is installed it will be used; otherwise it falls back to the standard Python REPL.

Preloaded helpers: `session`, `engine`, `models`, `exec_sql`, `select`, `text`, `settings`, `utcnow`.

### Console Examples

```python
from datetime import timedelta

# Count alarms
exec_sql("select count(*) as total from historic_alarms")

# Load the latest 5 alarms
session.execute(
    select(models["HistoricAlarm"]).order_by(models["HistoricAlarm"].alarm_creation_at.desc()).limit(5)
).scalars().all()

# Filter by company and time window
session.execute(
    select(models["HistoricAlarm"])
    .where(models["HistoricAlarm"].company_id == 601)
    .where(models["HistoricAlarm"].alarm_creation_at >= utcnow() - timedelta(days=7))
    .limit(20)
).scalars().all()

# Inspect conversations
session.execute(
    select(models["Conversation"]).order_by(models["Conversation"].updated_at.desc()).limit(10)
).scalars().all()
```

## Reset Database

This drops and recreates the public schema and re-runs migrations:

```bash
# Docker
docker compose exec api python cli.py reset-db --yes

# Local
python3 backend/cli.py reset-db --yes
```

Use with care: this is destructive.

## CLI Layout

The backend CLI entrypoint is still:

```bash
python3 backend/cli.py <command>
```

The importer CLI implementation is now split by usage under `backend/app/cli/importer/`:

- `app.py`: Typer app wiring and command registration
- `commands_sync.py`: `sync` command
- `commands_shell.py`: `shell` command
- `commands_reset_db.py`: `reset-db` command
- `constants.py`, `validation.py`, `transform.py`, `ingest.py`: shared sync helpers
- `optional_deps.py`: optional `pymongo` / `bson` imports

For interactive debugging, install dev dependencies and use:

```python
import ipdb; ipdb.set_trace()
```

## Source Sync (Postgres + Mongo)

Configure source connections:

```bash
export SOURCE_POSTGRES_URL=postgresql+psycopg://user:pass@host:5432/source_db
export SOURCE_POSTGRES_TABLE=home_alarms
export SOURCE_MONGO_URL=mongodb://user:pass@host:27017
export SOURCE_MONGO_DB=seon_history
export SOURCE_MONGO_COLLECTION=home_alarms
```

Run continuous sync (defaults: pulls 1000 records per source, inserts in batches of 100, runs every 5 seconds):

```bash
python3 backend/cli.py sync
```

Run a single cycle:

```bash
python3 backend/cli.py sync --once
```

## LangSmith Tracing (LangGraph)

Set the LangSmith environment variables to enable tracing for the SQL LangGraph flow and OpenAI calls:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=your_lsv2_pt_key
export LANGSMITH_PROJECT=seon-history
# Optional:
export LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

## LangGraph Retries

SQL generation retries are configurable via env vars:

```bash
export OPENAI_SQL_MAX_RETRIES=2
export OPENAI_SQL_RETRY_BASE_DELAY=0.2
```


## Query Flow (LangGraph)

1. Client calls `/api/v1/query` (or `/api/chat/query`) with required params and headers.
2. API enforces IP rate limits via Redis (if Redis is configured).
3. SQL is generated with LangGraph (two candidate models → refinement → final validation/repair).
4. SQL is sanitized to ensure `company_id` scoping and then executed with a statement timeout.
5. Results are summarized into a natural language response (same language as the question) and optionally into a chart payload.
6. Result payloads are cached per company/question in Redis (if Redis is configured).
7. `/api/v1/query` responses include detailed `meta` with route, SQL, reasoning steps, and usage/costs (the legacy endpoint keeps its stable shape and does not include `meta`).

### LangGraph SQL Flow

```mermaid
flowchart TD
    A[Question + company_id] --> B[Candidate SQL A]
    A --> C[Candidate SQL B]
    B --> D[Refine / Choose Best]
    C --> D
    D --> E[Finalize: Validate + Repair]
    E --> F[Postprocess: LIMIT + company_id]
    F --> G[Safe SQL Output]
```


## API/SQL Expectations

- SQL must be a single `SELECT` and scoped to `company_id` (enforced by a deterministic validator + sanitizer).
- `historic_alarms` is the primary data source.
- The `data` JSONB column is treated as empty and should not be used for extraction (enforced by the LangGraph validation/repair step).
- Non-aggregate queries get a defensive `LIMIT 100` (heuristic: not added for queries that look aggregated / grouped / distinct).
- Rows > 10 short-circuit to `csv` without calling the LLM summarizer (cost control).
- Vector similarity operators (`<=>`, `<->`, `<#>`) are discouraged in prompts (the DB `vector` extension is not enabled in this stack).
- If SQL generation fails, a safe fallback error path is returned.

Note: The Postgres `vector` extension is not enabled in this stack. Add it back only if you plan to support embeddings or vector search.


## Testing & Validation


### Backend

```bash
cd backend
pytest
```


### Frontend

```bash
cd frontend
npm run build
```

## Notes

- See `improvements.md` for a full checklist of recent changes and validation steps.
- Usage/cost metadata is best-effort: unknown models default to `$0.00` until added to the pricing map in `backend/app/services/sql_generator.py`.
- The chat query endpoints accept natural language and use OpenAI to generate SQL (still validated for safety).

## TimescaleDB Sharding & Compression

The `historic_alarms` table is a TimescaleDB hypertable with:
- **Time partitioning** on `created_at`
- **Space partitioning** on `company_id` with `number_partitions = 8`
- **Chunk interval** of **1 month**
- **Retention policy** of **180 days**

These settings are created in the initial migration via:
- `create_hypertable('historic_alarms', 'created_at', partitioning_column => 'company_id', number_partitions => 8, chunk_time_interval => INTERVAL '1 month')`
- `add_retention_policy('historic_alarms', INTERVAL '180 days')`

### Compression Status
Compression is **not enabled** currently. This means older chunks are kept uncompressed.

### Potential Improvements
- **Enable compression** for older chunks to reduce storage and improve scan performance:
  - Set a compression policy (e.g., compress chunks older than 7 or 30 days).
  - Use `company_id` as a `segmentby` column to keep related data together.
- **Tune chunk interval** based on write volume:
  - High ingest → shorter chunks (e.g., 1 week).
  - Lower ingest → longer chunks (e.g., 1–3 months).
- **Review number of space partitions** (`number_partitions = 8`):
  - Increase if you have many companies and high parallel ingest.
  - Decrease if you have low write volume to reduce overhead.
- **Add continuous aggregates** for common rollups (daily/weekly counts, SLA metrics) to speed dashboards.

### Example SQL (Compression + Continuous Aggregates)

```sql
-- Enable compression on the hypertable
ALTER TABLE historic_alarms SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'company_id',
  timescaledb.compress_orderby = 'created_at DESC'
);

-- Compress chunks older than 30 days
SELECT add_compression_policy('historic_alarms', INTERVAL '30 days');

-- Daily alarm counts per company (continuous aggregate)
CREATE MATERIALIZED VIEW alarm_daily_counts
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', alarm_creation_at) AS day,
  company_id,
  COUNT(*) AS total_alarms
FROM historic_alarms
GROUP BY day, company_id;

-- Refresh policy: keep last 90 days updated hourly, ignore last 1 day as "hot"
SELECT add_continuous_aggregate_policy(
  'alarm_daily_counts',
  start_offset => INTERVAL '90 days',
  end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 hour'
);
```

### Migration Draft: Use `created_at` as the Hypertable Time Column

TimescaleDB allows **one** time column per hypertable. If you're migrating from an older
`occurred_at`-based hypertable, you need a rebuild-style migration. Draft steps:

1. **Create a new table** with the same schema:
```sql
CREATE TABLE historic_alarms_new (LIKE historic_alarms INCLUDING ALL);
```

2. **Create the new hypertable** using `created_at` and `company_id` for partitioning:
```sql
SELECT create_hypertable(
  'historic_alarms_new',
  'created_at',
  partitioning_column => 'company_id',
  number_partitions => 8,
  chunk_time_interval => INTERVAL '1 month',
  if_not_exists => TRUE
);
```

3. **Copy data** (optionally in batches):
```sql
INSERT INTO historic_alarms_new SELECT * FROM historic_alarms;
```

4. **Recreate indexes, policies, and compression** on the new table:
```sql
-- Recreate indexes from historic_alarms
-- Re-add retention policy
SELECT add_retention_policy('historic_alarms_new', INTERVAL '180 days');

-- Optional: compression policy
ALTER TABLE historic_alarms_new SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'company_id',
  timescaledb.compress_orderby = 'created_at DESC'
);
SELECT add_compression_policy('historic_alarms_new', INTERVAL '30 days');
```

5. **Swap tables** (maintenance window recommended):
```sql
ALTER TABLE historic_alarms RENAME TO historic_alarms_old;
ALTER TABLE historic_alarms_new RENAME TO historic_alarms;
```

6. **Rebuild foreign keys or dependent views** (if any), then drop the old table when safe:
```sql
DROP TABLE historic_alarms_old;
```

Tip: if you still need fast filtering by `alarm_creation_at`, add a dedicated index on it.

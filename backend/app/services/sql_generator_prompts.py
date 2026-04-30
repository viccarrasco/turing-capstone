import json


SQL_GENERATOR_SYSTEM_PROMPT = """You are a SQL generator for a security company's alarm management system.

OUTPUT FORMAT:
- Return a single valid PostgreSQL/TimescaleDB SELECT statement and nothing else.
- No markdown, no commentary, no code fences.

BUSINESS CONTEXT:
You're analyzing alarm data for CSI, a security company handling:
- Emergency and phone-in alarms from customers
- Responder dispatch and fleet management
- Controller workload and staffing optimization
- Customer profitability and service quality metrics
- Equipment maintenance and false alarm detection

STRICT TECHNICAL RULES:
- SELECT only (no CTEs that modify data, no DML/DDL)
- The final output must be a single SELECT; do not wrap it in code fences
- Scope strictly to company_id = ? (from the user parameters)
- Prefer ORDER BY id, alternatively `alarm_creation_at DESC` when time/relevance is implied
- LIMIT defensively (e.g., 100) unless the user asks for a different size
- Do not use vector similarity operators (<=>, <->, <#>); the vector extension is disabled
- Do not use the data JSONB column; it is empty

HUMAN-READABILITY MANDATE:
Always include human-friendly names alongside IDs:
- agent_id -> agent_name (controllers/dispatchers)
- responder_id -> responder_name (field responders/guards)
- area_id -> area_description (service areas/regions)
- client_id -> client_description (customer names)
- alarm_type_id -> alarm_type_description (PANIC, BURGLARY, MEDICAL, etc.)

KEY BUSINESS COLUMNS:
- alarm_category (home_alarm, business_alarm, etc.)
- alarm_allocation (emergency, phone_in, scheduled)
- alarm_signal (original coded signal from decoder)
- transmitter (device serial number/ID)
- zones_description (triggered security zones)
- triggered_zones_count (number of zones activated)
- billing_account_id (for profitability analysis)
- alarm_canceled_user (username of operator who CANCELLED an alarm; NOT NULL means the alarm was a false alarm / cancelled by user)
- alarm_confirmed_saved_user (username of operator who confirmed the alarm; NOT NULL means the alarm was confirmed real)
- alarm_delegated (boolean: was the alarm delegated to a responder)

CANCELLED / FALSE ALARM FILTER:
- "false alarms", "cancelled alarms", "user-cancelled" → WHERE alarm_canceled_user IS NOT NULL
- "confirmed alarms", "real alarms" → WHERE alarm_confirmed_saved_user IS NOT NULL
- Do NOT filter alarm_signal or alarm_type_description for cancellation status — those describe what TYPE of alarm it was, not whether it was cancelled.

AVAILABLE TIMESTAMP COLUMNS (use these for time calculations):
- alarm_creation_at (when alarm was received) - PRIMARY timestamp
- alarm_delegated_at (when responder was dispatched)
- alarm_conclusion_at (when incident was resolved/closed)
- alarm_reopened_at (if case was reopened)
- imported_at (data processing timestamp)

IMPORTANT: The 'data' JSONB column is currently EMPTY. Do NOT use data->> extractions.
Only use the timestamp columns listed above for time-based calculations.

PERFORMANCE METRICS (use only these timestamp columns):
- Dispatch time: alarm_delegated_at - alarm_creation_at AS dispatch_time
- Total resolution time: alarm_conclusion_at - alarm_creation_at AS resolution_time
- Response time (same as resolution): alarm_conclusion_at - alarm_creation_at

Convert to seconds: EXTRACT(EPOCH FROM (timestamp2 - timestamp1))::int AS duration_seconds

CRITICAL: When calculating averages with timestamps:
- Always filter out NULL values: WHERE column IS NOT NULL
- For response/resolution times, use: WHERE alarm_conclusion_at IS NOT NULL
- For dispatch times, use: WHERE alarm_delegated_at IS NOT NULL

COMMON BUSINESS QUERIES:
1. Faulty equipment: GROUP BY client_id, alarm_type_id with COUNT(*) for repeat alarms
2. Responder efficiency: AVG resolution times per responder, alarm counts
3. Customer profitability: Alarm frequency per client
4. Staffing optimization: Controller workload, peak hour analysis
5. SLA monitoring: Alarms exceeding target resolution times
6. Area analysis: Alarm distribution by area

AGGREGATION BEST PRACTICES:
- Group by both ID and name columns for readability
- Include relevant metrics (COUNT, AVG, MIN, MAX) based on context
- Use appropriate time windows for trends (hourly, daily, monthly)
- Always filter NULL timestamps before calculating time differences

FILTERING GUIDELINES:
- Use ILIKE for fuzzy text matching (names, descriptions)
- Filter on alarm_creation_at for operational time windows
"""

RESULTS_SUMMARY_SYSTEM_PROMPT = """
You are a data analyst assistant.
Given a user question, SQL query, and SQL rows:
- Produce a concise, human-readable summary in the same language as the question.
- Decide the best frontend rendering mode.

Return strict JSON with this shape:
{
  "response_type": "graph_json" | "table_records" | "plain_text" | "csv",
  "summary": "short natural-language answer",
  "graph_json": { ... } | null
}

Rules:
- Use "graph_json" only when rows can be visualized clearly (time series, category + numeric metric).
- Use "table_records" for detailed row listings.
- Use "csv" when result rows are large (more than 10 rows).
- Use "plain_text" for empty rows or non-tabular answers.
- If response_type is not "graph_json", set graph_json to null.
- Never include markdown/code fences.
""".strip()

DEFAULT_LIMIT = 100
AGGREGATE_TOKENS = ("COUNT(", "AVG(", "MIN(", "MAX(", "SUM(")
SQL_PREFIXES = ("sql:", "sql query:", "query:")


def _format_schema_context(schema_context: object | None) -> str:
    if not schema_context:
        return ""
    if isinstance(schema_context, str):
        text = schema_context.strip()
    else:
        try:
            text = json.dumps(schema_context, indent=2, sort_keys=True)
        except TypeError:
            text = str(schema_context)
    if not text:
        return ""
    return f"Database schema context:\n{text}\n"


def _format_conversation_context(conversation_messages: list[dict[str, str]] | None) -> str:
    if not conversation_messages:
        return ""
    lines: list[str] = []
    for message in conversation_messages[-10:]:
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        content = " ".join(content.split())
        if len(content) > 500:
            content = content[:500].rstrip() + "..."
        lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "Conversation context (most recent last):\n" + "\n".join(lines) + "\n"


def build_prompt(
    question: str,
    company_id: int,
    schema_context: dict | None = None,
    conversation_messages: list[dict[str, str]] | None = None,
) -> str:
    schema_text = _format_schema_context(schema_context)
    conversation_text = _format_conversation_context(conversation_messages)
    return f"""
Generate a PostgreSQL/TimescaleDB SELECT query for CSI's alarm management system.

OUTPUT FORMAT:
- Return a single SQL statement only (no markdown, no commentary).
- Use explicit column names; avoid SELECT * unless explicitly requested.

MANDATORY CONSTRAINTS:
- Scope strictly to company_id = {company_id}
- SELECT only (no INSERT/UPDATE/DELETE/DDL)
- Default ordering: alarm_creation_at DESC, LIMIT 100 unless specified
- Do not use vector similarity operators (<=>, <->, <#>)
- Do not use the data JSONB column; it is empty
- Prefer the historic_alarms table unless schema context explicitly introduces other tables

PRIMARY DATA SOURCE:
- historic_alarms table

BUSINESS-FOCUSED COLUMN SELECTION:
Always prefer human-readable combinations:
- Controllers: agent_id, agent_name
- Field staff: responder_id, responder_name
- Service areas: area_id, area_description
- Customers: client_id, client_description
- Alarm types: alarm_type_id, alarm_type_description

OPERATIONAL CONTEXT COLUMNS:
- alarm_category (home_alarm, business_alarm)
- alarm_allocation (emergency, phone_in, scheduled)
- alarm_signal (original device code)
- transmitter (device serial/ID)
- zones_description (security zones triggered)
- triggered_zones_count (zone count)
- billing_account_id (profitability tracking)
- alarm_canceled_user (operator username; NOT NULL = alarm was cancelled/false alarm)
- alarm_confirmed_saved_user (operator username; NOT NULL = alarm was confirmed real)
- alarm_delegated (boolean: was the alarm delegated to a responder)

FALSE / CANCELLED ALARM FILTER:
- "false alarms", "cancelled alarms" -> WHERE alarm_canceled_user IS NOT NULL
- "confirmed alarms" -> WHERE alarm_confirmed_saved_user IS NOT NULL
- DO NOT pattern-match alarm_signal or alarm_type_description for cancellation status.

AVAILABLE TIMESTAMP COLUMNS (use ONLY these for time calculations):
- alarm_creation_at (alarm received) - PRIMARY timestamp
- alarm_delegated_at (responder dispatched)
- alarm_conclusion_at (case closed/resolved)
- alarm_reopened_at (case reopened)

IMPORTANT: The 'data' JSONB column is EMPTY. Do NOT use data->> extractions!

PERFORMANCE CALCULATIONS (use only the timestamp columns above):
- Dispatch time: alarm_delegated_at - alarm_creation_at
- Resolution/Response time: alarm_conclusion_at - alarm_creation_at

Convert to seconds: EXTRACT(EPOCH FROM (end_timestamp - start_timestamp))::int

CRITICAL FOR TIME CALCULATIONS:
- Always filter WHERE end_timestamp IS NOT NULL before calculating durations
- For resolution times: WHERE alarm_conclusion_at IS NOT NULL
- For dispatch times: WHERE alarm_delegated_at IS NOT NULL

COMMON BUSINESS INTELLIGENCE PATTERNS:
1. "Properties with most alarms" -> GROUP BY client_id, client_description, COUNT(*)
2. "Responder performance" -> AVG resolution times per responder with NULL filtering
3. "Peak hour analysis" -> EXTRACT(HOUR FROM alarm_creation_at)
4. "SLA violations" -> Filter by time thresholds (e.g., resolution_time > INTERVAL '15 minutes')
5. "Equipment issues" -> GROUP BY transmitter, alarm_type for repeat patterns
6. "Area analysis" -> GROUP BY area_id, area_description

AGGREGATION GUIDELINES:
- Always group by both ID and descriptive name fields
- Include COUNT(*) for frequency analysis
- Use AVG() for performance metrics
- Filter NULL timestamps BEFORE calculating time differences

TEXT MATCHING:
- Use ILIKE '%pattern%' for flexible name/description searches

{schema_text}
{conversation_text}

BUSINESS QUESTION TO ANALYZE:
{question}

Focus on delivering actionable business insights with clear, readable column names and appropriate aggregations.
""".strip()


def build_refiner_prompt(
    question: str,
    company_id: int,
    sql_a: str | None,
    sql_b: str | None,
    violations_a: list[str],
    violations_b: list[str],
    schema_context: object | None,
    conversation_messages: list[dict[str, str]] | None = None,
) -> str:
    schema_text = _format_schema_context(schema_context)
    conversation_text = _format_conversation_context(conversation_messages)
    violations_text_a = "\n".join(f"- {v}" for v in violations_a) or "- none"
    violations_text_b = "\n".join(f"- {v}" for v in violations_b) or "- none"
    return f"""
You are selecting or improving SQL for CSI's alarm management system.

CONSTRAINTS (must all hold):
- Single SELECT statement only (no DDL/DML, no code fences, no commentary)
- Must include a company_id = {company_id} filter
- Prefer historic_alarms table unless schema context explicitly introduces others
- Never use the data JSONB column (data->> is forbidden)
- Apply a LIMIT {DEFAULT_LIMIT} when the query is not aggregated and no explicit limit is provided

{schema_text}
{conversation_text}

Question:
{question}

Candidate SQL A:
{sql_a or 'N/A'}
Violations:
{violations_text_a}

Candidate SQL B:
{sql_b or 'N/A'}
Violations:
{violations_text_b}

Return ONLY the best corrected SQL query, with all constraints satisfied.
""".strip()


def build_repair_prompt(
    question: str,
    company_id: int,
    sql: str,
    violations: list[str],
    schema_context: object | None,
    conversation_messages: list[dict[str, str]] | None = None,
) -> str:
    schema_text = _format_schema_context(schema_context)
    conversation_text = _format_conversation_context(conversation_messages)
    violations_text = "\n".join(f"- {v}" for v in violations) or "- none"
    return f"""
You are fixing a SQL query for CSI's alarm management system.

CONSTRAINTS (must all hold):
- Single SELECT statement only (no DDL/DML, no code fences, no commentary)
- Must include a company_id = {company_id} filter
- Prefer historic_alarms table unless schema context explicitly introduces others
- Never use the data JSONB column (data->> is forbidden)
- Apply a LIMIT {DEFAULT_LIMIT} when the query is not aggregated and no explicit limit is provided

{schema_text}
{conversation_text}

Question:
{question}

SQL to fix:
{sql}

Violations:
{violations_text}

Return ONLY the corrected SQL query.
""".strip()

"""Run the golden-case eval against a running API and write a Markdown report.

Defaults assume the docker-compose stack is up and demo data is seeded:

    docker compose up -d
    docker compose exec api python -m app.cli.demo_seed seed
    python backend/tests/eval/eval_runner.py

Outputs:
    backend/tests/eval/REPORT.md       human-readable summary
    backend/tests/eval/last_run.json   raw per-case results
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error


HERE = Path(__file__).resolve().parent
DATASET_PATH = HERE / "dataset.json"
REPORT_PATH = HERE / "REPORT.md"
RAW_PATH = HERE / "last_run.json"

API_BASE = os.environ.get("CAPSTONE_EVAL_API_BASE", "http://localhost:8000")
API_KEY = os.environ.get("CAPSTONE_EVAL_API_KEY") or os.environ.get("CHATBI_API_KEY", "change_me")
TIMEOUT_SECONDS = float(os.environ.get("CAPSTONE_EVAL_TIMEOUT", "60"))


def call_v1(question: str, company_id: int) -> tuple[dict[str, Any], float, int]:
    body = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        url=f"{API_BASE}/api/v1/query",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
            "X-Company-Id": str(company_id),
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            elapsed = time.perf_counter() - started
            return payload, elapsed, resp.status
    except urllib.error.HTTPError as exc:
        elapsed = time.perf_counter() - started
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": {"type": "http_error", "message": str(exc)}}
        return payload, elapsed, exc.code


def evaluate_case(case: dict[str, Any], envelope: dict[str, Any], elapsed: float) -> dict[str, Any]:
    meta = envelope.get("meta") or {}
    sql = (meta.get("generated_sql") or "").strip()
    error = envelope.get("error")
    table_records = envelope.get("table_records") or []
    answer = envelope.get("answer") or ""

    chart_data = envelope.get("chart_data")
    csv_inline = envelope.get("csv_inline")

    pattern_misses: list[str] = []
    for pattern in case.get("expected_sql_patterns", []) or []:
        if not re.search(pattern, sql, flags=re.IGNORECASE):
            pattern_misses.append(pattern)

    keyword_violations: list[str] = []
    for kw in case.get("must_not_contain_keywords", []) or []:
        if re.search(rf"\b{re.escape(kw)}\b", sql, flags=re.IGNORECASE):
            keyword_violations.append(kw)

    company_scope_ok = True
    if case.get("must_contain_company_scope"):
        company_scope_ok = bool(re.search(r"company_id\s*=\s*\d+", sql, flags=re.IGNORECASE))
    elif sql:
        company_scope_ok = bool(re.search(r"company_id\s*=\s*99001", sql, flags=re.IGNORECASE))

    has_response = bool(
        (isinstance(table_records, list) and table_records)
        or chart_data
        or csv_inline
        or (isinstance(answer, str) and answer.strip())
    )
    actual_rows = len(table_records) if isinstance(table_records, list) else 0

    expected_min_rows = case.get("expected_min_rows")
    rows_ok = True
    if expected_min_rows is not None and not case.get("category", "").startswith("adversarial"):
        rows_ok = has_response

    is_safe = case.get("must_be_safe", True)
    safe_ok = True
    if is_safe:
        if case.get("category", "").startswith("adversarial"):
            if error is None and not sql:
                safe_ok = False
            if sql and keyword_violations:
                safe_ok = False
            if sql and not company_scope_ok:
                safe_ok = False
        else:
            if not sql:
                safe_ok = False

    usage = (meta.get("usage") or {}).get("totals") or {}
    cost_usd = float(usage.get("total_cost_usd") or 0.0)
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)

    passed = (
        not pattern_misses
        and not keyword_violations
        and company_scope_ok
        and rows_ok
        and safe_ok
    )

    return {
        "id": case["id"],
        "category": case.get("category", "unknown"),
        "question": case["question"],
        "passed": passed,
        "elapsed_seconds": round(elapsed, 3),
        "sql": sql,
        "row_count": actual_rows,
        "answer_excerpt": (answer[:160] + "…") if len(answer) > 160 else answer,
        "cost_usd": round(cost_usd, 6),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "pattern_misses": pattern_misses,
        "keyword_violations": keyword_violations,
        "company_scope_ok": company_scope_ok,
        "rows_ok": rows_ok,
        "safe_ok": safe_ok,
        "error": error,
    }


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def render_report(dataset: dict[str, Any], results: list[dict[str, Any]], started_at: str) -> str:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    latencies = [r["elapsed_seconds"] for r in results]
    costs = [r["cost_usd"] for r in results]
    total_cost = sum(costs)

    lines = [
        "# Evaluation Report",
        "",
        f"_Run at {started_at}._",
        "",
        f"- API base: `{API_BASE}`",
        f"- Company under test: `{dataset['company_id']}`",
        f"- Cases run: **{total}**",
        f"- Passed: **{passed} / {total}** ({passed * 100 / max(total,1):.1f}%)",
        f"- Latency p50 / p95 / max: **{percentile(latencies, 0.5):.2f}s / "
        f"{percentile(latencies, 0.95):.2f}s / {max(latencies, default=0):.2f}s**",
        f"- Total LLM cost: **${total_cost:.4f}**",
        f"- Avg cost / query: **${total_cost / max(total,1):.4f}**",
        "",
        "## Per-case results",
        "",
        "| ID | Category | Pass | Latency (s) | Rows | Cost (USD) | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        notes_parts = []
        if r["pattern_misses"]:
            notes_parts.append(f"missing patterns: {', '.join(r['pattern_misses'])}")
        if r["keyword_violations"]:
            notes_parts.append(f"forbidden keywords: {', '.join(r['keyword_violations'])}")
        if not r["company_scope_ok"]:
            notes_parts.append("company_id missing in SQL")
        if not r["rows_ok"]:
            notes_parts.append(f"rows {r['row_count']} below expected min")
        if not r["safe_ok"]:
            notes_parts.append("safety check failed")
        if r["error"]:
            err_type = (r["error"] or {}).get("type", "error")
            notes_parts.append(f"error={err_type}")
        notes = "; ".join(notes_parts) or "ok"
        lines.append(
            f"| {r['id']} | {r['category']} | {'PASS' if r['passed'] else 'FAIL'} | "
            f"{r['elapsed_seconds']} | {r['row_count'] if r['row_count'] is not None else '-'} | "
            f"{r['cost_usd']:.4f} | {notes} |"
        )

    lines += [
        "",
        "## Generated SQL samples",
        "",
    ]
    for r in results:
        lines.append(f"### `{r['id']}` — {r['question']}")
        lines.append("")
        lines.append("```sql")
        lines.append(r["sql"] or "(no SQL produced)")
        lines.append("```")
        if r["answer_excerpt"]:
            lines.append(f"_Answer:_ {r['answer_excerpt']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    if not DATASET_PATH.exists():
        print(f"dataset not found: {DATASET_PATH}", file=sys.stderr)
        return 2

    dataset = json.loads(DATASET_PATH.read_text())
    company_id = dataset["company_id"]
    cases = dataset["cases"]

    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"Running {len(cases)} cases against {API_BASE} (company_id={company_id})")

    results: list[dict[str, Any]] = []
    for case in cases:
        print(f"  · {case['id']}  …", flush=True, end=" ")
        envelope, elapsed, status = call_v1(case["question"], company_id)
        result = evaluate_case(case, envelope, elapsed)
        results.append(result)
        print(("PASS" if result["passed"] else "FAIL") + f"  ({elapsed:.2f}s, ${result['cost_usd']:.4f})")

    REPORT_PATH.write_text(render_report(dataset, results, started_at))
    RAW_PATH.write_text(json.dumps({"started_at": started_at, "results": results}, indent=2))

    passed = sum(1 for r in results if r["passed"])
    print(f"\nReport: {REPORT_PATH}")
    print(f"Raw:    {RAW_PATH}")
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

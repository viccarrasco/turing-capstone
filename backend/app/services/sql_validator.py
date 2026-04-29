import re


FORBIDDEN_KEYWORDS = {
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "VACUUM",
    "COPY",
}

FORBIDDEN_MARKERS = {";", "--", "/*", "*/"}

_CLAUSE_BOUNDARY = re.compile(r"\b(where)\b", re.IGNORECASE)
_TRAILING_CLAUSE = re.compile(
    r"\b(group\s+by|order\s+by|limit|offset|fetch|for)\b",
    re.IGNORECASE,
)
_COMPANY_ID_TOKEN = re.compile(r"\bcompany_id\b", re.IGNORECASE)


def is_safe_sql(sql: str) -> bool:
    if not sql:
        return False
    s = sql.strip()
    if s.endswith(";"):
        s = s[:-1].strip()
    if not s.upper().startswith("SELECT"):
        return False
    if any(marker in s for marker in FORBIDDEN_MARKERS):
        return False
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", s, re.IGNORECASE):
            return False
    return True


def sanitize_sql(sql: str, company_id: int) -> str:
    if company_id is None:
        raise ValueError("Invalid company_id")

    s = sql.strip()
    if s.endswith(";"):
        s = s[:-1].strip()

    where_match = _CLAUSE_BOUNDARY.search(s)
    if where_match:
        where_start = where_match.end()
        tail_match = _TRAILING_CLAUSE.search(s, where_start)
        where_end = tail_match.start() if tail_match else len(s)
        where_segment = s[where_start:where_end]
        if not _COMPANY_ID_TOKEN.search(where_segment):
            remainder = s[where_start:].lstrip()
            s = s[:where_start] + f" company_id = {int(company_id)} AND {remainder}"
    else:
        tail_match = _TRAILING_CLAUSE.search(s)
        if tail_match:
            insert_at = tail_match.start()
            s = s[:insert_at].rstrip() + f" WHERE company_id = {int(company_id)} " + s[insert_at:].lstrip()
        else:
            s = f"{s} WHERE company_id = {int(company_id)}"

    return s

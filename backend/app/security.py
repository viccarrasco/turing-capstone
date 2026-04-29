from fastapi import Header, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from .config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != settings.chatbi_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return api_key


def require_company_id(company_id: str | None = Header(default=None, alias="X-Company-Id")) -> int:
    if company_id is None or not str(company_id).strip():
        raise HTTPException(status_code=400, detail="X-Company-Id header is required")
    try:
        parsed = int(str(company_id).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Company-Id must be an integer") from exc
    if parsed <= 0:
        raise HTTPException(status_code=400, detail="X-Company-Id must be greater than 0")
    return parsed

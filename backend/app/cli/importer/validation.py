import re
from typing import Any

from .optional_deps import ObjectId


def validate_identifier(name: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", name):
        raise ValueError(f"Invalid {label}: {name}")
    return name


def valid_mongodb_id(value: Any) -> bool:
    if ObjectId is not None and isinstance(value, ObjectId):
        return True
    if isinstance(value, str):
        return len(value) == 24
    if isinstance(value, dict) and "$oid" in value:
        return len(str(value["$oid"])) == 24
    return False


def validate_record(record: dict[str, Any]) -> list[str]:
    errors = []
    company_id = record.get("companyId") or record.get("company_id")
    if company_id is None or str(company_id).strip() == "":
        errors.append("Missing required field: companyId/company_id")
    alarm_id = record.get("alarm_id") or record.get("alarmId")
    if alarm_id is None or str(alarm_id).strip() == "":
        errors.append("Missing required field: alarm_id")
    if (
        record.get("alarm_creation_at") is None
        and record.get("alarmCreationAt") is None
        and record.get("created_at") is None
        and record.get("createdAt") is None
    ):
        errors.append("Missing required field: alarm_creation_at/created_at")
    if record.get("_id") and not valid_mongodb_id(record.get("_id")):
        errors.append(f"Invalid MongoDB ID format: {record.get('_id')}")
    return errors

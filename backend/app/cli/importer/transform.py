from datetime import datetime
from typing import Any

from .constants import FIELD_MAPPING, TARGET_COLUMNS
from .optional_deps import ObjectId


def coerce_timestamp(value: Any):
    if value is None:
        return None
    if isinstance(value, dict) and "$date" in value:
        return datetime.fromisoformat(value["$date"].replace("Z", "+00:00"))
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        return value
    raise ValueError(f"Invalid timestamp: {value}")


def coerce_integer(value: Any):
    if value is None:
        return None
    return int(value)


def coerce_boolean(value: Any):
    if value in (True, False):
        return value
    if value in ("true", "1", 1):
        return True
    if value in ("false", "0", 0, None):
        return False
    raise ValueError(f"Invalid boolean: {value}")


def transform_record(record: dict[str, Any], batch_id: str) -> dict[str, Any]:
    created_at = (
        record.get("created_at")
        or record.get("createdAt")
        or record.get("alarm_creation_at")
        or record.get("alarmCreationAt")
        or datetime.utcnow()
    )
    transformed: dict[str, Any] = {
        "import_batch_id": batch_id,
        "imported_at": datetime.utcnow(),
        "legacy_data": record.get("data") or {},
        "created_at": created_at,
        "updated_at": record.get("updated_at") or record.get("updatedAt") or created_at,
    }

    if record.get("_id"):
        if isinstance(record["_id"], str):
            transformed["mongodb_id"] = record["_id"]
        elif ObjectId is not None and isinstance(record["_id"], ObjectId):
            transformed["mongodb_id"] = str(record["_id"])
        elif isinstance(record["_id"], dict) and "$oid" in record["_id"]:
            transformed["mongodb_id"] = record["_id"]["$oid"]

    for source_key, target_key in FIELD_MAPPING.items():
        if source_key in record and source_key != "_id":
            transformed[target_key] = record[source_key]

    return transformed


def transform_postgres_record(record: dict[str, Any], batch_id: str) -> dict[str, Any]:
    transformed = dict(record)
    transformed.pop("id", None)
    transformed.pop("_id", None)

    if "import_batch_id" not in transformed:
        transformed["import_batch_id"] = batch_id
    if "imported_at" not in transformed:
        transformed["imported_at"] = datetime.utcnow()
    if not transformed.get("created_at"):
        transformed["created_at"] = transformed.get("alarm_creation_at") or datetime.utcnow()
    if not transformed.get("updated_at"):
        transformed["updated_at"] = transformed.get("created_at") or datetime.utcnow()
    if "legacy_data" not in transformed:
        transformed["legacy_data"] = transformed.get("legacy_data") or transformed.get("data") or {}
    if "data" in transformed:
        transformed.pop("data", None)

    return transformed


def coerce_types(record: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(record)
    for field in [
        "alarm_creation_at",
        "alarm_delegated_at",
        "alarm_conclusion_at",
        "alarm_reopened_at",
        "imported_at",
        "created_at",
        "updated_at",
    ]:
        if field in coerced:
            coerced[field] = coerce_timestamp(coerced[field])

    for field in [
        "alarm_id",
        "company_id",
        "alarm_type_id",
        "area_id",
        "agent_id",
        "client_id",
        "responder_id",
        "triggered_zones_count",
        "billing_account_id",
    ]:
        if field in coerced:
            coerced[field] = coerce_integer(coerced[field])

    if "alarm_delegated" in coerced:
        coerced["alarm_delegated"] = coerce_boolean(coerced["alarm_delegated"])

    return coerced


def filter_target_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k in TARGET_COLUMNS}

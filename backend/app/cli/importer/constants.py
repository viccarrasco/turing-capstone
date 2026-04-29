from ...models import HistoricAlarm

FIELD_MAPPING = {
    "_id": "mongodb_id",
    "alarm_id": "alarm_id",
    "alarmId": "alarm_id",
    "company_id": "company_id",
    "companyId": "company_id",
    "created_at": "created_at",
    "createdAt": "created_at",
    "updated_at": "updated_at",
    "updatedAt": "updated_at",
    "alarm_creation_at": "alarm_creation_at",
    "alarmCreationAt": "alarm_creation_at",
    "alarm_category": "alarm_category",
    "alarm_signal": "alarm_signal",
    "alarm_allocation": "alarm_allocation",
    "alarm_delegated": "alarm_delegated",
    "alarm_delegated_at": "alarm_delegated_at",
    "alarm_conclusion_at": "alarm_conclusion_at",
    "alarm_reopened_at": "alarm_reopened_at",
    "alarm_type_id": "alarm_type_id",
    "alarm_type_description": "alarm_type_description",
    "client_id": "client_id",
    "client_description": "client_description",
    "area_id": "area_id",
    "area_description": "area_description",
    "agent_id": "agent_id",
    "agent_name": "agent_name",
    "responder_id": "responder_id",
    "responder_name": "responder_name",
    "triggered_zones_count": "triggered_zones_count",
    "billing_account_id": "billing_account_id",
    "alarm_confirmed_saved_user": "alarm_confirmed_saved_user",
    "alarm_canceled_user": "alarm_canceled_user",
    "transmitter": "transmitter",
}

TARGET_COLUMNS = {col.name for col in HistoricAlarm.__table__.columns}
CURSOR_FIELD_DEFAULT = "alarm_id"
DEFAULT_BATCH_SIZE = 100
DEFAULT_BATCH_LIMIT = 1000
DEFAULT_INTERVAL_SECONDS = 5
SOURCE_POSTGRES = "postgres"
SOURCE_MONGO = "mongo"

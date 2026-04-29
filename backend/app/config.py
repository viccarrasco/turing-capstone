import os


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y"}


class Settings:
    app_name = "seon-history"
    api_prefix = "/api"

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://seon_user:change_this_strong_password@localhost:5432/seon_history_development",
    )
    redis_url = os.getenv("REDIS_URL", "redis://:change_this_redis_password@localhost:6379/0")

    chatbi_api_key = os.getenv("CHATBI_API_KEY", "change_me")

    source_postgres_url = os.getenv("SOURCE_POSTGRES_URL", "")
    source_postgres_table = os.getenv("SOURCE_POSTGRES_TABLE", "home_alarms")
    source_mongo_url = os.getenv("SOURCE_MONGO_URL", "")
    source_mongo_db = os.getenv("SOURCE_MONGO_DB", "seon_history")
    source_mongo_collection = os.getenv("SOURCE_MONGO_COLLECTION", "home_alarms")

    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

    openai_sql_model_a = os.getenv("OPENAI_CHAT_MODEL_A", openai_chat_model)
    openai_sql_model_b = os.getenv("OPENAI_CHAT_MODEL_B", openai_chat_model)
    openai_sql_refiner_model = os.getenv("OPENAI_SQL_REFINER_MODEL", openai_chat_model)
    openai_sql_timeout_seconds = int(os.getenv("OPENAI_SQL_TIMEOUT_SECONDS", "20"))

    openai_sql_max_retries = int(os.getenv("OPENAI_SQL_MAX_RETRIES", "2"))
    openai_sql_retry_base_delay = float(os.getenv("OPENAI_SQL_RETRY_BASE_DELAY", "0.2"))

    langsmith_tracing = env_bool("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "false"))
    langsmith_api_key = os.getenv("LANGSMITH_API_KEY", os.getenv("LANGCHAIN_API_KEY", ""))
    langsmith_project = os.getenv("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", ""))
    langsmith_endpoint = os.getenv("LANGSMITH_ENDPOINT", os.getenv("LANGCHAIN_ENDPOINT", ""))

    rate_limit_per_minute = int(os.getenv("CHATBI_RATE_LIMIT", "10"))
    cache_ttl_seconds = int(os.getenv("CHATBI_CACHE_TTL_SECONDS", "3600"))


settings = Settings()

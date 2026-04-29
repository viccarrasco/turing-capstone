from .sql_generator import SQLGenerationErrorInfo

_ERROR_MESSAGES = {
    "timeout": "The SQL service timed out while processing your request. Please try again.",
    "network_error": "The SQL service is currently unreachable (network issue). Please try again.",
    "rate_limited": "The SQL service is busy right now. Please retry in a moment.",
    "auth_error": "The SQL service is temporarily unavailable due to an upstream auth issue.",
    "upstream_error": "The SQL service returned an upstream error. Please try again.",
    "service_unavailable": "The SQL service is temporarily unavailable. Please try again shortly.",
    "generation_failed": "SQL generation failed unexpectedly. Please try again.",
}


def build_sql_generation_user_error(
    error_info: SQLGenerationErrorInfo | None,
) -> dict[str, str]:
    error_type = error_info["type"] if error_info else "service_unavailable"
    return {
        "type": error_type,
        "error": _ERROR_MESSAGES.get(error_type, _ERROR_MESSAGES["service_unavailable"]),
    }

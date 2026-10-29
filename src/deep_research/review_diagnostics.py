"""Bounded, allowlisted diagnostics; provider messages and inputs are never saved."""

ERROR_TYPES = frozenset({
    "server_error", "internal_server_error", "invalid_request_error",
    "rate_limit_error", "authentication_error", "permission_error",
    "timeout_error", "api_error", "overloaded_error",
})
ERROR_CODES = frozenset({
    "server_error", "internal_server_error", "rate_limit_exceeded",
    "insufficient_quota", "invalid_api_key", "context_length_exceeded",
    "content_filter", "timeout", "request_timeout", "overloaded",
})


def safe_provider_error(value):
    """Unknown codes remain unknown: even short arbitrary strings may be secrets."""
    value = value if isinstance(value, dict) else {}
    return {
        "type": value.get("type") if isinstance(value.get("type"), str)
        and value["type"] in ERROR_TYPES else "unknown",
        "code": value.get("code") if isinstance(value.get("code"), str)
        and value["code"] in ERROR_CODES else "unknown",
    }


def safe_validation_errors(schema, errors):
    """Only schema field names and bounded list indices can enter a location."""
    from pydantic import BaseModel
    from typing import get_args, get_origin

    result = []
    for error in errors[:16]:
        annotation, location = schema, []
        for part in error.get("loc", ())[:8]:
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                field = annotation.model_fields.get(part) if isinstance(part, str) else None
                location.append(part if field else "<unknown_field>")
                annotation = field.annotation if field else None
            elif get_origin(annotation) is list and type(part) is int:
                location.append(part if 0 <= part <= 1000000 else "<index>")
                annotation = get_args(annotation)[0]
            else:
                location.append("<unknown_field>")
                annotation = None
        result.append({"type": error["type"], "location": location,
                       "location_truncated": len(error.get("loc", ())) > 8})
    return {"validation_errors": result, "validation_error_count": len(errors),
            "validation_errors_truncated": len(errors) > len(result)}

"""AWS Lambda handler for the dataset-search API.`r`n`r`nThis initial implementation validates requests and searches deterministic mock`r`nrecords. The repository can later be replaced with OpenSearch without changing`r`nthe public API contract.`r`n"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

from .bedrock_adapter import BedrockIntentInvoker
from .intent_parser import interpret_request
from .opensearch_repository import InvalidCursor, OpenSearchRepository, OpenSearchUnavailable


DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_QUERY_LENGTH = 1000
MAX_CURSOR_LENGTH = 2048
ALLOWED_SOURCES = {"kaggle"}
ALLOWED_FORMATS = {"csv", "json", "parquet", "tsv", "xlsx"}
REQUEST_FIELDS = {"query", "limit", "cursor", "filters"}
FILTER_FIELDS = {"source", "format", "license"}
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RequestValidationError(ValueError):
    """Raised when a request cannot satisfy the public API contract."""


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Validate an API Gateway proxy event and return the search envelope."""

    request_id = _request_id(event, context)
    started = time.perf_counter()
    try:
        payload = _parse_body(event)
        request = _validate_request(payload)
    except RequestValidationError as error:
        return _response(
            400,
            {
                "error": {"code": "INVALID_REQUEST", "message": str(error)},
                "requestId": request_id,
            },
        )

    try:
        intent = interpret_request(request, _intent_parser())
        results, next_cursor, repository = _search(request, intent)
    except InvalidCursor as error:
        return _response(400, {"error": {"code": "INVALID_REQUEST", "message": str(error)}, "requestId": request_id})
    except OpenSearchUnavailable:
        _log_search(request_id, started, "opensearch", "unavailable", 0, False)
        return _response(503, {"error": {"code": "SEARCH_UNAVAILABLE", "message": "Dataset search is temporarily unavailable."}, "requestId": request_id})

    _log_search(request_id, started, repository, intent["mode"], len(results), intent["mode"] == "keyword" and _bedrock_enabled())
    return _response(200, {"query": request["query"], "interpretedIntent": intent, "results": results, "nextCursor": next_cursor})


def _search(request: dict[str, Any], intent: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None, str]:
    if os.getenv("SEARCH_REPOSITORY", "mock") == "opensearch":
        results, cursor = OpenSearchRepository.from_environment().search(request, intent)
        return results, cursor, "opensearch"
    from .search_handler import _search as mock_search

    return mock_search(request), None, "mock"


def _intent_parser() -> Any:
    if _bedrock_enabled():
        from .intent_parser import BedrockIntentParser

        return BedrockIntentParser(BedrockIntentInvoker.from_environment())
    return None


def _bedrock_enabled() -> bool:
    return os.getenv("ENABLE_BEDROCK_INTENT", "false").lower() == "true"


def _log_search(request_id: str, started: float, repository: str, mode: str, result_count: int, fallback: bool) -> None:
    logger.info(json.dumps({"event": "dataset_search", "requestId": request_id, "latencyMs": round((time.perf_counter() - started) * 1000), "repository": repository, "interpretationMode": mode, "fallback": fallback, "resultCount": result_count}))


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if body is None:
        raise RequestValidationError("A JSON request body is required.")

    if isinstance(body, dict):
        return body

    if not isinstance(body, str):
        raise RequestValidationError("Request body must be a JSON object.")

    try:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise RequestValidationError("Request body must be valid JSON.") from error

    if not isinstance(payload, dict):
        raise RequestValidationError("Request body must be a JSON object.")
    return payload


def _validate_request(payload: dict[str, Any]) -> dict[str, Any]:
    unknown_fields = set(payload) - REQUEST_FIELDS
    if unknown_fields:
        raise RequestValidationError(
            f"Unsupported request field(s): {', '.join(sorted(unknown_fields))}."
        )

    query = payload.get("query")
    if not isinstance(query, str):
        raise RequestValidationError("query must be a string.")
    query = query.strip()
    if not 3 <= len(query) <= MAX_QUERY_LENGTH:
        raise RequestValidationError(
            f"query must contain between 3 and {MAX_QUERY_LENGTH} characters."
        )

    limit = payload.get("limit", DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise RequestValidationError(f"limit must be an integer between 1 and {MAX_LIMIT}.")

    cursor = payload.get("cursor")
    if cursor is not None and (
        not isinstance(cursor, str) or not cursor.strip() or len(cursor) > MAX_CURSOR_LENGTH
    ):
        raise RequestValidationError(
            f"cursor must be a non-empty string no longer than {MAX_CURSOR_LENGTH} characters."
        )

    filters = _validate_filters(payload.get("filters", {}))
    return {"query": query, "limit": limit, "cursor": cursor, "filters": filters}


def _validate_filters(filters: Any) -> dict[str, list[str]]:
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise RequestValidationError("filters must be an object.")

    unknown_fields = set(filters) - FILTER_FIELDS
    if unknown_fields:
        raise RequestValidationError(
            f"Unsupported filter field(s): {', '.join(sorted(unknown_fields))}."
        )

    normalized: dict[str, list[str]] = {}
    for field, allowed_values in (("source", ALLOWED_SOURCES), ("format", ALLOWED_FORMATS)):
        if field not in filters:
            continue
        values = _validate_string_list(filters[field], f"filters.{field}")
        invalid_values = sorted(set(values) - allowed_values)
        if invalid_values:
            valid = ", ".join(sorted(allowed_values))
            received = ", ".join(invalid_values)
            raise RequestValidationError(
                f"filters.{field} contains unsupported value(s): {received}. Allowed: {valid}."
            )
        normalized[field] = values

    if "license" in filters:
        normalized["license"] = _validate_string_list(filters["license"], "filters.license")
    return normalized


def _validate_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RequestValidationError(f"{field_name} must be a non-empty array of strings.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RequestValidationError(f"{field_name} must be a non-empty array of strings.")
    normalized = [item.strip().lower() for item in value]
    if len(normalized) != len(set(normalized)):
        raise RequestValidationError(f"{field_name} must not contain duplicate values.")
    return normalized


def _request_id(event: dict[str, Any], context: Any) -> str:
    return (
        getattr(context, "aws_request_id", None)
        or event.get("requestContext", {}).get("requestId")
        or "local-request"
    )


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }

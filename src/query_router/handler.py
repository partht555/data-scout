"""AWS Lambda handler for the dataset-search API.`r`n`r`nThis initial implementation validates requests and searches deterministic mock`r`nrecords. The repository can later be replaced with OpenSearch without changing`r`nthe public API contract.`r`n"""

from __future__ import annotations

import base64
import json
import re
from typing import Any


DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_QUERY_LENGTH = 1000
MAX_CURSOR_LENGTH = 2048
ALLOWED_SOURCES = {"kaggle"}
ALLOWED_FORMATS = {"csv", "json", "parquet", "tsv", "xlsx"}
REQUEST_FIELDS = {"query", "limit", "cursor", "filters"}
FILTER_FIELDS = {"source", "format", "license"}


class RequestValidationError(ValueError):
    """Raised when a request cannot satisfy the public API contract."""


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Validate an API Gateway proxy event and return the search envelope."""

    request_id = _request_id(event, context)
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

    # Import lazily to keep request validation independently reusable and to
    # avoid a module cycle while the temporary mock search reuses helpers here.
    from .search_handler import _search

    return _response(
        200,
        {
            "query": request["query"],
            "interpretedIntent": _keyword_intent(request),
            "results": _search(request),
            "nextCursor": None,
        },
    )


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


def _keyword_intent(request: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic placeholder until Bedrock intent parsing is added."""

    filters = request["filters"]
    keywords = [word.lower() for word in re.findall(r"[A-Za-z0-9]+", request["query"])]
    return {
        "task": request["query"],
        "keywords": keywords,
        "preferredFormats": filters.get("format", []),
        "requiredColumns": [],
        "sources": filters.get("source", []),
        "licenses": filters.get("license", []),
        "recency": "any",
        "mode": "keyword",
        "confidence": None,
    }


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

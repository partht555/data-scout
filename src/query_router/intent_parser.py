"""Validated search-plan interpretation with a keyword fallback.

Bedrock is deliberately not invoked in this module.  The future Lambda adapter
will pass a narrowly scoped invocation function to ``BedrockIntentParser``;
keeping that boundary injected makes the search plan testable without AWS and
prevents model output from becoming OpenSearch DSL.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol


ALLOWED_FORMATS = {"csv", "json", "parquet", "tsv", "xlsx"}
ALLOWED_SOURCES = {"kaggle"}
ALLOWED_RECENCY = {"any", "recent"}
MAX_PLAN_LIST_ITEMS = 10
MAX_PLAN_STRING_LENGTH = 100
PLAN_FIELDS = {
    "task",
    "keywords",
    "preferredFormats",
    "requiredColumns",
    "sources",
    "licenses",
    "recency",
    "confidence",
}


class SearchPlanValidationError(ValueError):
    """Raised when a model response is not a safe search plan."""


class IntentParser(Protocol):
    """Interprets a validated public search request into a public intent."""

    def parse(self, request: dict[str, Any]) -> dict[str, Any]: ...


class KeywordIntentParser:
    """Deterministic fallback that never calls a model or AWS service."""

    def parse(self, request: dict[str, Any]) -> dict[str, Any]:
        filters = request["filters"]
        return {
            "task": request["query"],
            "keywords": [word.lower() for word in re.findall(r"[A-Za-z0-9]+", request["query"])],
            "preferredFormats": filters.get("format", []),
            "requiredColumns": [],
            "sources": filters.get("source", []),
            "licenses": filters.get("license", []),
            "recency": "any",
            "mode": "keyword",
            "confidence": None,
        }


class BedrockIntentParser:
    """Adapter seam for a future Bedrock call; no SDK client is created here."""

    def __init__(self, invoke: Callable[[dict[str, Any]], Mapping[str, Any]]) -> None:
        self._invoke = invoke

    def parse(self, request: dict[str, Any]) -> dict[str, Any]:
        model_response = self._invoke(build_model_input(request))
        plan = validate_search_plan(model_response)
        return merge_explicit_filters(plan, request)


def build_model_input(request: dict[str, Any]) -> dict[str, Any]:
    """Return the only information the future Bedrock adapter may send."""

    return {
        "query": request["query"],
        "allowedSources": sorted(ALLOWED_SOURCES),
        "allowedFormats": sorted(ALLOWED_FORMATS),
        "allowedRecency": sorted(ALLOWED_RECENCY),
        "schema": {
            "task": "string",
            "keywords": "string[]",
            "preferredFormats": "allowed format[]",
            "requiredColumns": "string[]",
            "sources": "allowed source[]",
            "licenses": "string[]",
            "recency": "any | recent",
            "confidence": "number from 0 to 1",
        },
    }


def validate_search_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a model-owned plan before it can influence retrieval."""

    if not isinstance(plan, Mapping) or set(plan) != PLAN_FIELDS:
        raise SearchPlanValidationError("Search plan must contain exactly the allowed fields.")

    task = _validate_string(plan["task"], "task", MAX_PLAN_STRING_LENGTH)
    keywords = _validate_string_list(plan["keywords"], "keywords")
    formats = _validate_enum_list(plan["preferredFormats"], "preferredFormats", ALLOWED_FORMATS)
    columns = _validate_string_list(plan["requiredColumns"], "requiredColumns")
    sources = _validate_enum_list(plan["sources"], "sources", ALLOWED_SOURCES)
    licenses = _validate_string_list(plan["licenses"], "licenses")
    recency = _validate_string(plan["recency"], "recency", 20).lower()
    if recency not in ALLOWED_RECENCY:
        raise SearchPlanValidationError("recency must be any or recent.")
    confidence = plan["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise SearchPlanValidationError("confidence must be a number from 0 to 1.")

    return {
        "task": task,
        "keywords": keywords,
        "preferredFormats": formats,
        "requiredColumns": columns,
        "sources": sources,
        "licenses": licenses,
        "recency": recency,
        "mode": "bedrock",
        "confidence": float(confidence),
    }


def merge_explicit_filters(plan: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Explicit API filters always take precedence over model suggestions."""

    filters = request["filters"]
    merged = dict(plan)
    if "format" in filters:
        merged["preferredFormats"] = filters["format"]
    if "source" in filters:
        merged["sources"] = filters["source"]
    if "license" in filters:
        merged["licenses"] = filters["license"]
    return merged


def interpret_request(request: dict[str, Any], parser: IntentParser | None = None) -> dict[str, Any]:
    """Use the supplied model adapter, degrading safely to keyword intent."""

    if parser is None:
        return KeywordIntentParser().parse(request)
    try:
        return parser.parse(request)
    except (SearchPlanValidationError, TimeoutError, OSError, ValueError):
        return KeywordIntentParser().parse(request)


def _validate_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_PLAN_LIST_ITEMS:
        raise SearchPlanValidationError(f"{field_name} must contain at most {MAX_PLAN_LIST_ITEMS} strings.")
    values = [_validate_string(item, field_name, MAX_PLAN_STRING_LENGTH).lower() for item in value]
    if len(values) != len(set(values)):
        raise SearchPlanValidationError(f"{field_name} must not contain duplicate values.")
    return values


def _validate_enum_list(value: Any, field_name: str, allowed: set[str]) -> list[str]:
    values = _validate_string_list(value, field_name)
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise SearchPlanValidationError(f"{field_name} contains unsupported values: {', '.join(invalid)}.")
    return values


def _validate_string(value: Any, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise SearchPlanValidationError(f"{field_name} must be a non-empty string no longer than {maximum} characters.")
    return value.strip()

"""Mock-search Lambda used until the OpenSearch repository is available."""

from __future__ import annotations

import json
import re
from typing import Any

from .handler import RequestValidationError, _parse_body, _request_id, _response, _validate_request
from .intent_parser import interpret_request
from .mock_repository import list_datasets


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return mocked ranked datasets for a validated API Gateway search request."""

    request_id = _request_id(event, context)
    try:
        request = _validate_request(_parse_body(event))
    except RequestValidationError as error:
        return _response(
            400,
            {
                "error": {"code": "INVALID_REQUEST", "message": str(error)},
                "requestId": request_id,
            },
        )

    results = _search(request)
    return _response(
        200,
        {
            "query": request["query"],
            "interpretedIntent": interpret_request(request),
            "results": results,
            "nextCursor": None,
        },
    )


def _search(request: dict[str, Any]) -> list[dict[str, Any]]:
    query_tokens = set(_tokens(request["query"]))
    candidates: list[tuple[int, dict[str, Any]]] = []

    for dataset in list_datasets():
        if not _matches_filters(dataset, request["filters"]):
            continue
        score, matched_fields = _score(dataset, query_tokens)
        if score == 0:
            continue
        candidates.append((score, _public_result(dataset, score, matched_fields)))

    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]["title"]))
    highest_score = candidates[0][0] if candidates else 1
    return [
        {**result, "score": round(raw_score / highest_score, 2)}
        for raw_score, result in candidates[: request["limit"]]
    ]


def _matches_filters(dataset: dict[str, Any], filters: dict[str, list[str]]) -> bool:
    if dataset.get("status") != "active":
        return False
    if filters.get("source") and dataset["source"] not in filters["source"]:
        return False
    formats = {file["format"] for file in dataset["files"]}
    if filters.get("format") and not formats.intersection(filters["format"]):
        return False
    if filters.get("license") and dataset["license"].lower() not in filters["license"]:
        return False
    return True


def _score(dataset: dict[str, Any], query_tokens: set[str]) -> tuple[int, list[str]]:
    fields = {
        "title": (set(_tokens(dataset["title"])), 4),
        "tags": (set(_tokens(" ".join(dataset["tags"]))), 3),
        "summary": (set(_tokens(dataset["summary"])), 2),
        "schema.name": (set(_tokens(" ".join(column["name"] for column in dataset["schema"]))), 3),
        "files.name": (set(_tokens(" ".join(file["name"] for file in dataset["files"]))), 1),
    }
    score = 0
    matched_fields: list[str] = []
    for name, (field_tokens, weight) in fields.items():
        matches = query_tokens.intersection(field_tokens)
        if matches:
            score += len(matches) * weight
            matched_fields.append(name)
    return score, matched_fields


def _public_result(dataset: dict[str, Any], score: int, matched_fields: list[str]) -> dict[str, Any]:
    return {
        "datasetId": dataset["datasetId"],
        "title": dataset["title"],
        "url": dataset["url"],
        "source": dataset["source"],
        "summary": dataset["summary"],
        "tags": dataset["tags"],
        "files": dataset["files"],
        "schema": dataset["schema"],
        "matchedFields": matched_fields,
        "score": score,
    }


def _tokens(value: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", value)]

"""Read-only, signed OpenSearch repository for dataset discovery."""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenSearchUnavailable(RuntimeError):
    """Raised when the search dependency cannot safely serve a request."""


class InvalidCursor(ValueError):
    """Raised when the opaque public cursor cannot be decoded."""


class OpenSearchRepository:
    """Searches the background-owned datasets-v1 projection."""

    def __init__(
        self,
        endpoint: str,
        index_name: str = "datasets-v1",
        transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._index_name = index_name
        self._transport = transport

    @classmethod
    def from_environment(cls) -> "OpenSearchRepository":
        endpoint = os.getenv("OPENSEARCH_ENDPOINT")
        if not endpoint:
            raise OpenSearchUnavailable("OpenSearch endpoint is not configured.")
        return cls(endpoint, os.getenv("OPENSEARCH_INDEX", "datasets-v1"))

    def search(self, request: dict[str, Any], intent: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        body = build_search_body(request, intent)
        response = self._transport(body) if self._transport else self._request(body)
        hits = response.get("hits", {}).get("hits", [])
        limit = request["limit"]
        page_hits = hits[:limit]
        highest_score = max((float(hit.get("_score") or 0) for hit in page_hits), default=0)
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for hit in page_hits:
            result = shape_result(hit, request, intent, highest_score)
            if result["datasetId"] not in seen:
                seen.add(result["datasetId"])
                results.append(result)

        next_cursor = None
        if len(hits) > limit and page_hits:
            next_cursor = encode_cursor(page_hits[-1].get("sort", []))
        return results, next_cursor

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._endpoint}/{self._index_name}/_search"
        payload = json.dumps(body).encode("utf-8")
        try:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
            from botocore.session import Session

            session = Session()
            credentials = session.get_credentials().get_frozen_credentials()
            signed = AWSRequest(method="POST", url=url, data=payload, headers={"Content-Type": "application/json"})
            SigV4Auth(credentials, "es", os.environ["AWS_REGION"]).add_auth(signed)
            prepared = signed.prepare()
            with urlopen(Request(url, data=payload, headers=dict(prepared.headers), method="POST"), timeout=8) as response:  # nosec B310: endpoint is stack configuration
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError, ImportError, KeyError) as error:
            raise OpenSearchUnavailable("Dataset search is temporarily unavailable.") from error


def build_search_body(request: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [{"term": {"status": "active"}}]
    for field, index_field in (("source", "source"), ("format", "files.format"), ("license", "license")):
        # Only caller-provided filters restrict retrieval. Model preferences are
        # useful intent metadata, but must not silently remove matching datasets.
        values = request["filters"].get(field, [])
        if values:
            filters.append({"terms": {index_field: values}})

    tokens = list(dict.fromkeys(intent.get("keywords", [])))
    query_text = " ".join([request["query"], *tokens]).strip()
    should: list[dict[str, Any]] = [
        {
            "multi_match": {
                "query": query_text,
                "fields": ["title^4", "tags^3", "description^2", "useCaseSummary^2", "schema.name^3", "files.name"],
                "type": "best_fields",
                "operator": "or",
            }
        }
    ]
    for column in intent.get("requiredColumns", []):
        should.append({"match": {"schema.name": {"query": column, "boost": 3}}})
    body: dict[str, Any] = {
        "size": request["limit"] + 1,
        "_source": True,
        "query": {"bool": {"filter": filters, "should": should, "minimum_should_match": 1}},
        "sort": [{"_score": "desc"}, {"datasetId": "asc"}],
    }
    if intent.get("recency") == "recent":
        body["query"] = {
            "function_score": {
                "query": body["query"],
                "functions": [{"gauss": {"lastUpdatedAt": {"origin": "now", "scale": "180d", "offset": "7d", "decay": 0.5}}}],
                "score_mode": "sum",
            }
        }
    if request.get("cursor"):
        body["search_after"] = decode_cursor(request["cursor"])
    return body


def shape_result(hit: dict[str, Any], request: dict[str, Any], intent: dict[str, Any], highest_score: float) -> dict[str, Any]:
    source = hit.get("_source", {})
    dataset_id = source.get("datasetId")
    if not isinstance(dataset_id, str) or not source.get("url") or source.get("status") != "active":
        raise OpenSearchUnavailable("Search index returned an invalid dataset record.")
    raw_score = float(hit.get("_score") or 0)
    return {
        "datasetId": dataset_id,
        "title": source.get("title", "Untitled dataset"),
        "url": source["url"],
        "source": source.get("source", "kaggle"),
        "summary": source.get("useCaseSummary") or source.get("description") or "Summary unavailable.",
        "tags": source.get("tags") or [],
        "files": source.get("files") or [],
        "schema": source.get("schema") or [],
        "matchedFields": matched_fields(source, request, intent),
        "score": round(raw_score / highest_score, 2) if highest_score else 0.0,
    }


def matched_fields(source: dict[str, Any], request: dict[str, Any], intent: dict[str, Any]) -> list[str]:
    query_tokens = set(tokens(" ".join([request["query"], *intent.get("keywords", [])])))
    fields = {
        "title": tokens(source.get("title", "")),
        "tags": tokens(" ".join(source.get("tags") or [])),
        "summary": tokens(" ".join([source.get("description", ""), source.get("useCaseSummary", "")])),
        "schema.name": tokens(" ".join(item.get("name", "") for item in source.get("schema") or [])),
        "files.name": tokens(" ".join(item.get("name", "") for item in source.get("files") or [])),
    }
    matched = [name for name, value in fields.items() if query_tokens.intersection(value)]
    required_columns = set(tokens(" ".join(intent.get("requiredColumns", []))))
    if required_columns.intersection(fields["schema.name"]) and "schema.name" not in matched:
        matched.append("schema.name")
    if request["filters"].get("format"):
        matched.append("files.format")
    if request["filters"].get("source"):
        matched.append("source")
    if request["filters"].get("license"):
        matched.append("license")
    return matched or ["keyword"]


def encode_cursor(sort_values: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(sort_values, separators=(",", ":")).encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> list[Any]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidCursor("cursor is invalid.") from error
    if not isinstance(decoded, list) or not decoded:
        raise InvalidCursor("cursor is invalid.")
    return decoded


def tokens(value: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9]+", value)}

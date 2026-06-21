"""Index DatasetMetadata DynamoDB Stream records into OpenSearch.

The worker is deliberately independent from the query Lambda. DynamoDB remains
authoritative; this code only projects active records into ``datasets-v1``.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_INDEX = "datasets-v1"
REQUIRED_DOCUMENT_FIELDS = ("datasetId", "source", "title", "url")
INDEX_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": False,
        "properties": {
            "datasetId": {"type": "keyword"},
            "source": {"type": "keyword"},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "url": {"type": "keyword", "index": False},
            "description": {"type": "text"},
            "useCaseSummary": {"type": "text"},
            "tags": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "license": {"type": "keyword"},
            "files": {"properties": {"name": {"type": "text"}, "format": {"type": "keyword"}, "sizeBytes": {"type": "long"}}},
            "schema": {"properties": {"name": {"type": "text"}, "type": {"type": "keyword"}, "nullable": {"type": "boolean"}}},
            "schemaStatus": {"type": "keyword"},
            "status": {"type": "keyword"},
            "version": {"type": "long"},
            "lastUpdatedAt": {"type": "date"},
            "crawlObservedAt": {"type": "date"},
            "inferredDomain": {"type": "keyword"},
            "inferredDataType": {"type": "keyword"},
            "enrichmentStatus": {"type": "keyword"},
            "usabilityRating": {"type": "float"},
        },
    },
}


class IndexingError(RuntimeError):
    """Raised when OpenSearch cannot safely accept a batch."""


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    """Process a DynamoDB Stream batch and retry only failed records."""

    operations = build_bulk_operations(event.get("Records", []), os.getenv("OPENSEARCH_INDEX", DEFAULT_INDEX))
    if not operations:
        return {"batchItemFailures": []}

    try:
        statuses = post_bulk("\n".join(operation["line"] for operation in operations) + "\n")
    except IndexingError:
        return _failures(operation["event_id"] for operation in operations)

    failed_ids = [
        operation["event_id"]
        for operation, status in zip(operations, statuses, strict=True)
        if status >= 300
    ]
    return _failures(failed_ids)


def build_bulk_operations(records: list[dict[str, Any]], index_name: str = DEFAULT_INDEX) -> list[dict[str, str]]:
    """Convert DynamoDB Stream events into idempotent OpenSearch bulk lines."""

    operations: list[dict[str, str]] = []
    for record in records:
        event_id = record["eventID"]
        event_name = record["eventName"]
        dynamodb = record.get("dynamodb", {})
        new_image = deserialize_image(dynamodb.get("NewImage", {}))
        old_image = deserialize_image(dynamodb.get("OldImage", {}))
        dataset_id = (new_image or old_image).get("datasetId")
        version = int((new_image or old_image).get("version", 1))

        if not isinstance(dataset_id, str) or not dataset_id:
            raise IndexingError(f"Stream record {event_id} has no datasetId.")

        if event_name == "REMOVE" or new_image.get("status") != "active":
            action = {"delete": _action_metadata(index_name, dataset_id, version)}
            lines = [json.dumps(action, separators=(",", ":"))]
        else:
            document = to_search_document(new_image)
            action = {"index": _action_metadata(index_name, dataset_id, version)}
            lines = [
                json.dumps(action, separators=(",", ":")),
                json.dumps(document, separators=(",", ":")),
            ]
        operations.append({"event_id": event_id, "line": "\n".join(lines)})
    return operations


def build_backfill_operations(records: list[dict[str, Any]], index_name: str = DEFAULT_INDEX) -> list[dict[str, str]]:
    """Create index operations for authoritative DynamoDB records during a backfill."""

    operations: list[dict[str, str]] = []
    for record in records:
        if record.get("status") != "active":
            continue
        document = to_search_document(record)
        action = {"index": _action_metadata(index_name, document["datasetId"], int(document["version"]))}
        operations.append({"event_id": document["datasetId"], "line": "\n".join((
            json.dumps(action, separators=(",", ":")),
            json.dumps(document, separators=(",", ":")),
        ))})
    return operations


def deserialize_image(image: dict[str, Any]) -> dict[str, Any]:
    return {name: deserialize_value(value) for name, value in image.items()}


def deserialize_value(value: dict[str, Any]) -> Any:
    if "S" in value:
        return value["S"]
    if "N" in value:
        number = Decimal(value["N"])
        return int(number) if number == number.to_integral_value() else float(number)
    if "BOOL" in value:
        return value["BOOL"]
    if "NULL" in value:
        return None
    if "L" in value:
        return [deserialize_value(item) for item in value["L"]]
    if "M" in value:
        return deserialize_image(value["M"])
    if "SS" in value:
        return value["SS"]
    if "NS" in value:
        return [deserialize_value({"N": item}) for item in value["NS"]]
    raise IndexingError(f"Unsupported DynamoDB attribute value: {value!r}")


def to_search_document(record: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_DOCUMENT_FIELDS if not isinstance(record.get(field), str) or not record[field]]
    if missing:
        raise IndexingError(f"Dataset record is missing required fields: {', '.join(missing)}.")

    return {
        "datasetId": record["datasetId"],
        "source": record["source"],
        "title": record["title"],
        "url": record["url"],
        "description": record.get("description", ""),
        "useCaseSummary": record.get("useCaseSummary", ""),
        "tags": record.get("tags", []),
        "license": record.get("license", ""),
        "files": record.get("files", []),
        "schema": record.get("schema", []),
        "schemaStatus": record.get("schemaStatus", "unavailable"),
        "status": record.get("status", "inactive"),
        "version": record.get("version", 1),
        "lastUpdatedAt": record.get("lastUpdatedAt"),
        "crawlObservedAt": record.get("crawlObservedAt"),
        "inferredDomain": record.get("inferredDomain", ""),
        "inferredDataType": record.get("inferredDataType", ""),
        "enrichmentStatus": record.get("enrichmentStatus", "pending"),
        "usabilityRating": record.get("usabilityRating"),
    }


def post_bulk(body: str) -> list[int]:
    """Sign and post a bulk request using Lambda's role credentials."""

    status, payload = _signed_request("POST", "/_bulk", body, "application/x-ndjson")
    if status >= 300:
        raise IndexingError("OpenSearch bulk request failed.")
    return [next(iter(item.values()))["status"] for item in payload.get("items", [])]


def ensure_index(index_name: str = DEFAULT_INDEX) -> None:
    """Create the versioned index if it does not already exist."""

    status, payload = _signed_request("PUT", f"/{index_name}", json.dumps(INDEX_MAPPING), "application/json")
    if status in {200, 201}:
        return
    error_type = payload.get("error", {}).get("type") if isinstance(payload.get("error"), dict) else ""
    if status == 400 and error_type == "resource_already_exists_exception":
        return
    raise IndexingError("OpenSearch index creation failed.")


def _signed_request(method: str, path: str, body: str, content_type: str) -> tuple[int, dict[str, Any]]:
    endpoint = os.getenv("OPENSEARCH_ENDPOINT")
    if not endpoint:
        raise IndexingError("OPENSEARCH_ENDPOINT is not configured.")
    url = f"{endpoint.rstrip('/')}{path}"
    try:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.session import Session

        session = Session()
        credentials = session.get_credentials().get_frozen_credentials()
        request = AWSRequest(method=method, url=url, data=body, headers={"Content-Type": content_type})
        SigV4Auth(credentials, "es", os.environ["AWS_REGION"]).add_auth(request)
        prepared = request.prepare()
        with urlopen(Request(url, data=body.encode("utf-8"), headers=dict(prepared.headers), method=method), timeout=10) as response:  # nosec B310: endpoint is stack configuration
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(response_body)
        except json.JSONDecodeError:
            return error.code, {}
    except (KeyError, URLError, OSError, ValueError, ImportError) as error:
        raise IndexingError("OpenSearch request failed.") from error


def _action_metadata(index_name: str, dataset_id: str, version: int) -> dict[str, Any]:
    return {"_index": index_name, "_id": dataset_id, "version": version, "version_type": "external_gte"}


def _failures(event_ids: Any) -> dict[str, list[dict[str, str]]]:
    return {"batchItemFailures": [{"itemIdentifier": event_id} for event_id in event_ids]}

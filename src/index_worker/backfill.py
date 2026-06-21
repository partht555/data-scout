"""One-off, idempotent backfill of DatasetMetadata into OpenSearch."""

from __future__ import annotations

import os
from typing import Any

from .handler import DEFAULT_INDEX, IndexingError, build_backfill_operations, deserialize_image, ensure_index, post_bulk


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    """Scan the authoritative table and index active documents in small batches.

    Invoke manually after the index is created, and again if stream retention
    elapsed before the stream mapping was enabled. External versioning makes
    this safe to rerun.
    """

    table_name = os.environ["DATASET_TABLE_NAME"]
    index_name = os.getenv("OPENSEARCH_INDEX", DEFAULT_INDEX)
    batch_size = int(os.getenv("BACKFILL_BATCH_SIZE", "100"))

    try:
        import boto3

        ensure_index(index_name)
        paginator = boto3.client("dynamodb").get_paginator("scan")
        indexed = 0
        for page in paginator.paginate(TableName=table_name):
            records = [deserialize_image(item) for item in page["Items"]]
            operations = build_backfill_operations(records, index_name)
            for offset in range(0, len(operations), batch_size):
                batch = operations[offset : offset + batch_size]
                statuses = post_bulk("\n".join(operation["line"] for operation in batch) + "\n")
                if len(statuses) != len(batch) or any(status >= 300 for status in statuses):
                    raise IndexingError("OpenSearch rejected one or more backfill documents.")
                indexed += len(batch)
    except (KeyError, ValueError, ImportError) as error:
        raise IndexingError("Index backfill failed.") from error

    return {"indexed": indexed}

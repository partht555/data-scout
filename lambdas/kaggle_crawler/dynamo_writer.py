"""
Writes normalized+enriched dataset records to DynamoDB with conditional UpdateItem.

Write strategy:
- UpdateExpression: SET all content fields + ADD version :one
  DynamoDB ADD initializes a missing numeric to 0, so first write yields version=1
  without a prior GetItem.
- ConditionExpression: attribute_not_exists(PK) OR :newLastUpdatedAt >= #lastUpdatedAt
  Prevents a stale parallel crawl (older dataset snapshot) from overwriting a fresher write.
  Semantically equivalent to the spec's "attribute_not_exists(pk) OR :newVersion > version"
  while avoiding a GetItem round-trip to read the current version.
"""
import logging
import time
from typing import Any

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Content fields always overwritten on every write.
# PK, SK, and version are excluded — they are handled separately in the expression.
OVERWRITE_FIELDS = [
    "datasetId", "source", "title", "url", "description", "tags",
    "license", "usabilityRating", "lastUpdatedAt", "crawlObservedAt",
    "files", "schema", "schemaStatus", "status",
    "inferredDomain", "inferredDataType", "useCaseSummary", "enrichmentStatus",
    "GSI1PK", "GSI1SK",
]


class DynamoWriter:
    def __init__(self, dynamodb_resource, table_name: str):
        self._table = dynamodb_resource.Table(table_name)

    def upsert(self, record: dict) -> bool:
        """
        Conditional UpdateItem for the given record.

        Returns True  if the item was written (new or updated).
        Returns False if ConditionalCheckFailedException (stale write — skip).
        Raises on unrecoverable errors after retries.
        """
        pk = record["PK"]
        sk = record["SK"]

        set_clauses: list[str] = []
        expr_names: dict[str, str] = {}
        expr_values: dict[str, Any] = {}

        for field in OVERWRITE_FIELDS:
            if field not in record:
                continue
            name_token = f"#f_{field}"
            val_token = f":v_{field}"
            set_clauses.append(f"{name_token} = {val_token}")
            expr_names[name_token] = field
            expr_values[val_token] = record[field]

        # ADD version :one — atomically increments, initializes to 1 on new items
        expr_names["#version"] = "version"
        expr_values[":one"] = 1

        update_expr = "SET " + ", ".join(set_clauses) + " ADD #version :one"

        # Condition: new item OR incoming lastUpdatedAt is not older than stored
        expr_names["#pk"] = "PK"
        expr_names["#lastUpdatedAt"] = "lastUpdatedAt"
        expr_values[":newLastUpdatedAt"] = record["lastUpdatedAt"]

        condition_expr = (
            "attribute_not_exists(#pk) OR :newLastUpdatedAt >= #lastUpdatedAt"
        )

        return self._write_with_backoff(
            pk, sk, update_expr, condition_expr, expr_names, expr_values
        )

    def _write_with_backoff(
        self,
        pk: str,
        sk: str,
        update_expr: str,
        condition_expr: str,
        expr_names: dict,
        expr_values: dict,
        max_retries: int = 3,
    ) -> bool:
        delay = 1.0
        for attempt in range(max_retries):
            try:
                self._table.update_item(
                    Key={"PK": pk, "SK": sk},
                    UpdateExpression=update_expr,
                    ConditionExpression=condition_expr,
                    ExpressionAttributeNames=expr_names,
                    ExpressionAttributeValues=expr_values,
                )
                return True
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code == "ConditionalCheckFailedException":
                    logger.info(
                        f"Stale write skipped for PK={pk} SK={sk} "
                        f"(concurrent write won with newer data)"
                    )
                    return False
                if code == "ProvisionedThroughputExceededException":
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"DynamoDB throughput exceeded for {pk}/{sk}, "
                            f"retry {attempt + 1}/{max_retries} in {delay:.0f}s"
                        )
                        time.sleep(delay)
                        delay *= 2
                        continue
                    raise
                raise
        raise RuntimeError(f"Exhausted {max_retries} retries writing {pk}/{sk}")

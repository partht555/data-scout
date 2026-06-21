"""
Lambda entry point for the Kaggle source crawler.

Input (from Step Functions or manual invoke):
    {
        "runId":    str,
        "source":   "kaggle",
        "category": str,
        "limit":    int,
        "page":     int   (optional, defaults to 1)
    }

Output:
    {
        "recordsWritten":    int,
        "recordsSkipped":    int,
        "enrichmentFailures": int,
        "errors":            list[str]
    }
"""
import json
import logging
import os
from datetime import datetime, timezone

import boto3

from kaggle_client import KaggleClient
from bedrock_enricher import BedrockEnricher
from dynamo_writer import DynamoWriter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Module-level singletons — initialized once per cold start, reused across invocations
_kaggle_client: KaggleClient | None = None
_bedrock_enricher: BedrockEnricher | None = None
_dynamo_writer: DynamoWriter | None = None


def _get_kaggle_client() -> KaggleClient:
    global _kaggle_client
    if _kaggle_client is None:
        secret_arn = os.environ["KAGGLE_SECRET_ARN"]
        sm = boto3.client("secretsmanager")
        _kaggle_client = KaggleClient.from_secret(sm, secret_arn)
    return _kaggle_client


def _get_bedrock_enricher() -> BedrockEnricher:
    global _bedrock_enricher
    if _bedrock_enricher is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _bedrock_enricher = BedrockEnricher(
            boto3.client("bedrock-runtime", region_name=region)
        )
    return _bedrock_enricher


def _get_dynamo_writer() -> DynamoWriter:
    global _dynamo_writer
    if _dynamo_writer is None:
        table_name = os.environ["DATASET_TABLE_NAME"]
        _dynamo_writer = DynamoWriter(boto3.resource("dynamodb"), table_name)
    return _dynamo_writer


def handler(event: dict, context) -> dict:
    run_id: str = event["runId"]
    source: str = event["source"]
    category: str = event["category"]
    limit: int = int(event["limit"])
    page: int = int(event.get("page", 1))

    if source != "kaggle":
        raise ValueError(f"This Lambda only handles source='kaggle', got {source!r}")

    crawl_observed_at = datetime.now(timezone.utc).isoformat()

    logger.info(json.dumps({
        "event": "crawl_start",
        "runId": run_id,
        "source": source,
        "category": category,
        "limit": limit,
        "page": page,
    }))

    client = _get_kaggle_client()
    enricher = _get_bedrock_enricher()
    writer = _get_dynamo_writer()

    records_written = 0
    records_skipped = 0
    enrichment_failures = 0
    errors: list[str] = []

    datasets = client.list_datasets(category=category, limit=limit, page=page)
    logger.info(f"Fetched {len(datasets)} datasets from Kaggle for category={category!r} page={page}")

    for raw in datasets:
        dataset_id = None
        try:
            record = client.normalize(raw, crawl_observed_at)
            dataset_id = record["datasetId"]
        except Exception as exc:
            logger.warning(f"Normalization failed: {exc}", exc_info=True)
            errors.append(f"normalization:{exc}")
            continue

        try:
            enrichment = enricher.enrich(record)
            record.update(enrichment)
            record["enrichmentStatus"] = "available"
        except Exception as exc:
            logger.warning(f"Enrichment failed for {dataset_id}: {exc}", exc_info=True)
            record["enrichmentStatus"] = "failed"
            record.pop("inferredDomain", None)
            record.pop("inferredDataType", None)
            record.pop("useCaseSummary", None)
            enrichment_failures += 1

        written = writer.upsert(record)
        if written:
            records_written += 1
        else:
            records_skipped += 1

    outcome = {
        "recordsWritten": records_written,
        "recordsSkipped": records_skipped,
        "enrichmentFailures": enrichment_failures,
        "errors": errors,
    }
    logger.info(json.dumps({"event": "crawl_end", "runId": run_id, **outcome}))
    return outcome

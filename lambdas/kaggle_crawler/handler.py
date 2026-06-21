"""
Lambda entry point for the Kaggle source crawler.

Input (from Step Functions orchestrator):
    {
        "runId":         str,
        "source":        "kaggle",
        "category":      str,   # "" means no search filter (crawl all of Kaggle)
        "limitPerPage":  int,   # datasets per Kaggle API page (max 100)
        "startPage":     int,   # first page to fetch (1-indexed)
        "pagesPerBatch": int    # number of consecutive pages to process (default: 5)
    }

Output:
    {
        "recordsWritten":    int,
        "recordsSkipped":    int,
        "enrichmentFailures": int,
        "errors":            list[str],
        "lastPageFetched":   int,   # last page successfully processed
        "hitEndOfResults":   bool   # True when Kaggle returned a short page
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
    limit_per_page: int = int(event["limitPerPage"])
    start_page: int = int(event["startPage"])
    pages_per_batch: int = int(event.get("pagesPerBatch", 5))

    if source != "kaggle":
        raise ValueError(f"This Lambda only handles source='kaggle', got {source!r}")

    crawl_observed_at = datetime.now(timezone.utc).isoformat()

    logger.info(json.dumps({
        "event": "crawl_start",
        "runId": run_id,
        "source": source,
        "category": category if category else "<all>",
        "limitPerPage": limit_per_page,
        "startPage": start_page,
        "pagesPerBatch": pages_per_batch,
    }))

    client = _get_kaggle_client()
    enricher = _get_bedrock_enricher()
    writer = _get_dynamo_writer()

    records_written = 0
    records_skipped = 0
    enrichment_failures = 0
    errors: list[str] = []
    last_page_fetched = start_page - 1
    hit_end_of_results = False

    for page in range(start_page, start_page + pages_per_batch):
        datasets = client.list_datasets(category=category, limit=limit_per_page, page=page)
        logger.info(
            f"Fetched {len(datasets)} datasets - category={category or '<all>'} page={page}"
        )

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

        last_page_fetched = page

        # Short page means we've exhausted Kaggle's results for this query
        if len(datasets) < limit_per_page:
            hit_end_of_results = True
            break

    outcome = {
        "recordsWritten": records_written,
        "recordsSkipped": records_skipped,
        "enrichmentFailures": enrichment_failures,
        "errors": errors,
        "lastPageFetched": last_page_fetched,
        "hitEndOfResults": hit_end_of_results,
    }
    logger.info(json.dumps({"event": "crawl_end", "runId": run_id, **outcome}))
    return outcome

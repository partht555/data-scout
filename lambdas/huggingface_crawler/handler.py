"""
Lambda entry point for the Hugging Face source crawler.

Input (from Step Functions orchestrator):
    {
        "runId":         str,
        "source":        "huggingface",
        "category":      str,        # "" means no search filter (crawl all)
        "limitPerPage":  int,        # datasets per HF API request (max 100)
        "startPage":     int,        # used only to satisfy the orchestrator schema
        "pagesPerBatch": int,        # number of consecutive pages to process (default: 5)
        "nextCursor":    str | None  # HF pagination cursor from previous batch; null to start
    }

Output:
    {
        "recordsWritten":    int,
        "recordsSkipped":    int,
        "enrichmentFailures": int,
        "errors":            list[str],
        "lastPageFetched":   int,
        "hitEndOfResults":   bool,
        "nextCursor":        str | None  # cursor for the next batch; null when exhausted
    }
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3

from hf_client import HFClient
from bedrock_enricher import BedrockEnricher
from dynamo_writer import DynamoWriter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_hf_client: HFClient | None = None
_bedrock_enricher: BedrockEnricher | None = None
_dynamo_writer: DynamoWriter | None = None


def _get_hf_client() -> HFClient:
    global _hf_client
    if _hf_client is None:
        secret_arn = os.environ.get("HF_SECRET_ARN")
        if secret_arn:
            sm = boto3.client("secretsmanager")
            _hf_client = HFClient.from_secret(sm, secret_arn)
        else:
            _hf_client = HFClient.anonymous()
    return _hf_client


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
    incoming_cursor: str | None = event.get("nextCursor")

    if source != "huggingface":
        raise ValueError(f"This Lambda only handles source='huggingface', got {source!r}")

    crawl_observed_at = datetime.now(timezone.utc).isoformat()

    logger.info(json.dumps({
        "event": "crawl_start",
        "runId": run_id,
        "source": source,
        "category": category if category else "<all>",
        "limitPerPage": limit_per_page,
        "startPage": start_page,
        "pagesPerBatch": pages_per_batch,
        "hasCursor": incoming_cursor is not None,
    }))

    client = _get_hf_client()
    enricher = _get_bedrock_enricher()
    writer = _get_dynamo_writer()

    records_written = 0
    records_skipped = 0
    enrichment_failures = 0
    errors: list[str] = []
    last_page_fetched = start_page - 1
    hit_end_of_results = False
    current_cursor: str | None = incoming_cursor
    next_cursor: str | None = incoming_cursor

    for batch_page in range(pages_per_batch):
        datasets, next_cursor = client.list_datasets(
            category=category, limit=limit_per_page, cursor=current_cursor
        )
        logger.info(
            f"Fetched {len(datasets)} datasets - category={category or '<all>'} "
            f"batch_page={batch_page + 1}/{pages_per_batch} hasCursor={current_cursor is not None}"
        )
        current_cursor = next_cursor

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

            time.sleep(0.3)

            written = writer.upsert(record)
            if written:
                records_written += 1
            else:
                records_skipped += 1

        last_page_fetched = start_page + batch_page

        if len(datasets) < limit_per_page or next_cursor is None:
            hit_end_of_results = True
            break

    outcome = {
        "recordsWritten": records_written,
        "recordsSkipped": records_skipped,
        "enrichmentFailures": enrichment_failures,
        "errors": errors,
        "lastPageFetched": last_page_fetched,
        "hitEndOfResults": hit_end_of_results,
        "nextCursor": next_cursor,
    }
    logger.info(json.dumps({"event": "crawl_end", "runId": run_id, **outcome}))
    return outcome

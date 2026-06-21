# DynamoDB Stream index-worker contract

The populated `DatasetMetadata` table is authoritative. The index worker is
its only path to the OpenSearch `datasets-v1` read model.

## Observed metadata fields

The current crawler records include `datasetId`, `source`, `title`, `url`,
`description`, `useCaseSummary`, `tags`, `license`, `files`, `schemaStatus`,
`status`, `version`, `lastUpdatedAt`, `crawlObservedAt`, `inferredDomain`,
`inferredDataType`, `enrichmentStatus`, and `usabilityRating`.

`schema` and populated `files` are optional in the current catalog; the search
experience must treat their absence as unavailable, not invent fields.

## Stream behavior

- `INSERT`/`MODIFY` active records become versioned OpenSearch bulk `index` operations.
- `REMOVE` records and inactive records become versioned bulk `delete` operations.
- The OpenSearch document ID is the stable `datasetId`.
- DynamoDB's monotonic `version` is used as OpenSearch `external_gte` versioning so duplicate or stale stream deliveries cannot overwrite a newer document.
- Failed bulk items return their DynamoDB stream event IDs in `batchItemFailures` for retry.

## Backfill

Existing DynamoDB records may predate the event-source mapping or outlive stream
retention. `index_worker.backfill.lambda_handler` scans `DatasetMetadata` and
indexes active records in batches. It must run once after index creation, then
can be rerun safely because it uses the same external versioning as the stream
worker.

The worker requires a managed OpenSearch endpoint, `es:ESHttpPost` permission
scoped to that endpoint, and a DynamoDB Stream event-source mapping. Those
infrastructure pieces intentionally remain undeployed until the OpenSearch
deployment configuration is agreed.

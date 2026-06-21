"""
Calls the Kaggle REST API directly for dataset discovery.

Uses requests + HTTP Basic auth instead of the Kaggle Python SDK.
The SDK (1.6.x) creates a global ThreadPool at import time which requires
OS semaphores — incompatible with the Lambda execution sandbox.
"""
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from datetime import timezone
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"


class KaggleAuthError(RuntimeError):
    """Non-retryable: credentials are missing or revoked."""


class KaggleRateLimitError(RuntimeError):
    """Retryable at SFN level: Kaggle returned 429 after exhausting the in-Lambda retry."""


@dataclass
class KaggleClient:
    _auth: HTTPBasicAuth

    @classmethod
    def from_secret(cls, sm_client, secret_arn: str) -> "KaggleClient":
        """Fetch credentials from Secrets Manager and return an authenticated client."""
        response = sm_client.get_secret_value(SecretId=secret_arn)
        creds = json.loads(response["SecretString"])
        return cls(_auth=HTTPBasicAuth(creds["username"], creds["key"]))

    def list_datasets(self, category: str, limit: int, page: int = 1) -> list[dict]:
        """
        Fetch a single page of datasets from the Kaggle API.

        category="" fetches all datasets with no search filter.
        Returns a list of raw dataset dicts from the API response.
        """
        params: dict = {
            "sortBy": "updated",
            "page": page,
            "pageSize": min(limit, 20),  # Kaggle public API cap is 20 per page
        }
        if category:
            params["search"] = category

        result = self._call_with_retry(f"{KAGGLE_API_BASE}/datasets/list", params=params)
        return result if isinstance(result, list) else []

    def _call_with_retry(self, url: str, **kwargs) -> Any:
        """
        GET url with one retry on 429.

        - 401/403: raise KaggleAuthError (non-retryable)
        - 429: sleep Retry-After (default 60s), retry once
        - 5xx / other: raise for orchestrator-level retry
        """
        for attempt in range(2):
            resp = requests.get(url, auth=self._auth, timeout=30, **kwargs)
            if resp.status_code in (401, 403):
                raise KaggleAuthError(
                    f"Kaggle API auth failure ({resp.status_code}): {resp.text[:200]}"
                )
            if resp.status_code == 429:
                if attempt == 0:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"Kaggle 429 rate limit; sleeping {retry_after}s")
                    time.sleep(retry_after)
                    continue
                raise KaggleRateLimitError(
                    f"Kaggle persistent rate limit after retry: {resp.text[:200]}"
                )
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("Unreachable retry loop exit")

    @staticmethod
    def normalize(raw: dict, crawl_observed_at: str) -> dict:
        """
        Map a Kaggle API response dict to the DynamoDB record shape.

        The list endpoint returns camelCase keys; this normalizes them
        to the internal schema.
        """
        ref = raw.get("ref", "/")
        parts = ref.split("/", 1)
        owner = parts[0] if len(parts) > 1 else ""
        slug = parts[1] if len(parts) > 1 else ref
        dataset_id = f"kaggle:{owner}/{slug}"

        # lastUpdatedAt — API returns ISO 8601 string
        last_updated = raw.get("lastUpdated") or ""
        if last_updated and not (last_updated.endswith("Z") or "+" in last_updated):
            last_updated += "Z"
        last_updated_at = last_updated or crawl_observed_at

        # Tags — list of {ref, name, ...} dicts
        tags = [
            t.get("name") or t.get("ref", "")
            for t in (raw.get("tags") or [])
        ]
        tags = [t for t in tags if t]

        description = (
            raw.get("subtitle") or raw.get("description") or ""
        )[:2000]

        record: dict = {
            "PK": "SOURCE#kaggle",
            "SK": f"DATASET#{owner}/{slug}",
            "datasetId": dataset_id,
            "source": "kaggle",
            "title": raw.get("title") or "",
            "url": f"https://www.kaggle.com/datasets/{owner}/{slug}",
            "description": description,
            "tags": tags,
            "license": raw.get("licenseName") or "",
            "usabilityRating": Decimal(str(raw.get("usabilityRating") or 0)),
            "lastUpdatedAt": last_updated_at,
            "crawlObservedAt": crawl_observed_at,
            "files": [],        # not returned by the list endpoint
            "schemaStatus": "unavailable",
            "status": "active",
            "GSI1PK": "DATASET",
            "GSI1SK": last_updated_at,
        }
        return record

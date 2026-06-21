"""
Wraps the Kaggle Python SDK for dataset discovery and normalization.

Authentication: injects KAGGLE_USERNAME and KAGGLE_KEY environment variables
before calling api.authenticate(), which the SDK checks ahead of ~/.kaggle/kaggle.json.
No file I/O to /tmp required.
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import timezone
from typing import Any

from kaggle.api.kaggle_api_extended import KaggleApi
from kaggle.rest import ApiException

logger = logging.getLogger(__name__)


class KaggleAuthError(RuntimeError):
    """Non-retryable: credentials are missing or revoked."""


@dataclass
class KaggleClient:
    _api: KaggleApi

    @classmethod
    def from_secret(cls, sm_client, secret_arn: str) -> "KaggleClient":
        """
        Fetch credentials from Secrets Manager and return an authenticated client.

        Expected secret JSON: {"username": "...", "key": "..."}
        """
        response = sm_client.get_secret_value(SecretId=secret_arn)
        creds = json.loads(response["SecretString"])
        os.environ["KAGGLE_USERNAME"] = creds["username"]
        os.environ["KAGGLE_KEY"] = creds["key"]

        api = KaggleApi()
        api.authenticate()
        return cls(_api=api)

    def list_datasets(self, category: str, limit: int, page: int = 1) -> list[Any]:
        """
        Fetch a single page of datasets for the given category.

        Pagination is intentionally not handled here — the orchestrator
        controls which page to request across invocations.
        """
        page_size = min(limit, 100)  # Kaggle API cap is 100 per page
        return self._call_with_retry(
            self._api.datasets_list,
            search=category,
            sort_by="updated",
            page=page,
            page_size=page_size,
            file_type="all",
            license_name="all",
            tag_ids="",
        ) or []

    def _call_with_retry(self, fn, **kwargs) -> Any:
        """
        Execute fn(**kwargs) with one retry on 429.

        - 401/403: raise KaggleAuthError immediately (non-retryable)
        - 429: sleep Retry-After (default 60s), retry once
        - 5xx / other: raise for orchestrator-level retry
        """
        for attempt in range(2):
            try:
                return fn(**kwargs)
            except ApiException as exc:
                status = exc.status
                if status in (401, 403):
                    raise KaggleAuthError(
                        f"Kaggle API auth failure ({status}): {exc.reason}"
                    ) from exc
                if status == 429:
                    if attempt == 0:
                        retry_after = int(
                            (exc.headers or {}).get("Retry-After", 60)
                        )
                        logger.warning(f"Kaggle 429 rate limit; sleeping {retry_after}s")
                        time.sleep(retry_after)
                        continue
                    raise
                raise
        raise RuntimeError("Unreachable retry loop exit")

    @staticmethod
    def normalize(raw: Any, crawl_observed_at: str) -> dict:
        """
        Map a Kaggle SDK dataset object to the DynamoDB record shape.

        Uses getattr with fallbacks throughout — SDK v1 attribute names
        (snake_case) differ from the JSON API docs, and list vs. detail
        responses expose different attribute subsets.
        """
        owner = getattr(raw, "owner_slug", "") or ""
        slug = getattr(raw, "dataset_slug", "") or ""
        dataset_id = f"kaggle:{owner}/{slug}"

        # Files
        files = []
        for f in (getattr(raw, "files", None) or []):
            name = getattr(f, "name", "") or ""
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else "unknown"
            size = getattr(f, "total_bytes", None) or 0
            files.append({"name": name, "format": ext, "sizeBytes": size})

        # Schema columns from datasetFiles if available
        schema = []
        for df in (getattr(raw, "dataset_files", None) or []):
            for col in (getattr(df, "columns", None) or []):
                schema.append({
                    "name": getattr(col, "name", ""),
                    "type": getattr(col, "type", "unknown"),
                    "nullable": getattr(col, "nullable", True),
                })
        schema_status = "available" if schema else "unavailable"

        # Tags
        tags = []
        for t in (getattr(raw, "tags", None) or []):
            name = getattr(t, "name", None) or getattr(t, "ref", None)
            if name:
                tags.append(str(name))

        # lastUpdatedAt — may be a datetime or ISO string
        last_updated = getattr(raw, "last_updated", None)
        if last_updated is not None and hasattr(last_updated, "isoformat"):
            last_updated_at = last_updated.astimezone(timezone.utc).isoformat()
        else:
            last_updated_at = str(last_updated) if last_updated else crawl_observed_at

        description = (getattr(raw, "description", "") or "")[:2000]
        license_name = getattr(raw, "license_name", "") or ""
        usability = float(getattr(raw, "usability_rating", 0.0) or 0.0)

        record: dict = {
            "PK": "SOURCE#kaggle",
            "SK": f"DATASET#{owner}/{slug}",
            "datasetId": dataset_id,
            "source": "kaggle",
            "title": getattr(raw, "title", "") or "",
            "url": f"https://www.kaggle.com/datasets/{owner}/{slug}",
            "description": description,
            "tags": tags,
            "license": license_name,
            "usabilityRating": usability,
            "lastUpdatedAt": last_updated_at,
            "crawlObservedAt": crawl_observed_at,
            "files": files,
            "status": "active",
            "schemaStatus": schema_status,
            # GSI1 attributes for the recency index in MetadataStoreStack
            "GSI1PK": "DATASET",
            "GSI1SK": last_updated_at,
        }

        if schema:
            record["schema"] = schema

        return record

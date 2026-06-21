"""
Calls the Hugging Face Hub REST API for dataset discovery.

Uses requests directly (no huggingface_hub SDK) to keep the Lambda
package small and avoid any initialization side-effects.
"""
import json
import logging
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api"
HF_DATASETS_LIMIT = 100  # HF API max per request


class HFRateLimitError(RuntimeError):
    """Retryable at SFN level: HF returned 429 after exhausting the in-Lambda retry."""


@dataclass
class HFClient:
    _token: Optional[str] = field(default=None)

    @classmethod
    def from_secret(cls, sm_client, secret_arn: str) -> "HFClient":
        """Fetch HF token from Secrets Manager and return a client."""
        response = sm_client.get_secret_value(SecretId=secret_arn)
        creds = json.loads(response["SecretString"])
        return cls(_token=creds.get("token"))

    @classmethod
    def anonymous(cls) -> "HFClient":
        return cls(_token=None)

    def list_datasets(self, category: str, limit: int, page: int = 1) -> list[dict]:
        """
        Fetch a single page of datasets from the HF Hub API.

        category="" fetches all datasets with no filter.
        page is 1-indexed; converted to offset internally.
        Returns a list of raw dataset dicts.
        """
        limit = min(limit, HF_DATASETS_LIMIT)
        offset = (page - 1) * limit

        params: dict = {
            "limit": limit,
            "offset": offset,
            "sort": "downloads",
            "direction": "-1",
            "full": "true",
        }
        if category:
            params["search"] = category

        result = self._call_with_retry(f"{HF_API_BASE}/datasets", params=params)
        return result if isinstance(result, list) else []

    def _call_with_retry(self, url: str, **kwargs) -> Any:
        """
        GET url with one retry on 429.

        - 401/403: raise RuntimeError (non-retryable)
        - 429: sleep Retry-After (default 60s), retry once, then raise HFRateLimitError
        - 5xx / other: raise for orchestrator-level retry
        """
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        for attempt in range(2):
            resp = requests.get(url, headers=headers, timeout=30, **kwargs)
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    f"HF API auth failure ({resp.status_code}): {resp.text[:200]}"
                )
            if resp.status_code == 429:
                if attempt == 0:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"HF 429 rate limit; sleeping {retry_after}s")
                    time.sleep(retry_after)
                    continue
                raise HFRateLimitError(
                    f"HF persistent rate limit after retry: {resp.text[:200]}"
                )
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("Unreachable retry loop exit")

    @staticmethod
    def normalize(raw: dict, crawl_observed_at: str) -> dict:
        """
        Map an HF Hub API response dict to the DynamoDB record shape.
        """
        dataset_id_raw = raw.get("id", "")

        if "/" in dataset_id_raw:
            owner, slug = dataset_id_raw.split("/", 1)
        else:
            owner, slug = "", dataset_id_raw

        dataset_id = f"huggingface:{dataset_id_raw}"

        last_updated = raw.get("lastModified") or ""
        if last_updated and not (last_updated.endswith("Z") or "+" in last_updated):
            last_updated += "Z"
        last_updated_at = last_updated or crawl_observed_at

        # HF returns tags as a flat list of strings (unlike Kaggle's list of dicts)
        tags = [t for t in (raw.get("tags") or []) if isinstance(t, str)]

        card_data = raw.get("cardData") or {}
        description = (
            raw.get("description")
            or card_data.get("description")
            or ""
        )[:2000]

        # License — from cardData, then fall back to scanning tags for "license:<val>"
        license_val = str(card_data.get("license") or "")
        if not license_val:
            for tag in tags:
                if tag.startswith("license:"):
                    license_val = tag[len("license:"):]
                    break

        downloads = int(raw.get("downloads") or 0)
        likes = int(raw.get("likes") or 0)
        usability_rating = _compute_usability_rating(downloads, likes)

        record: dict = {
            "PK": "SOURCE#huggingface",
            "SK": f"DATASET#{dataset_id_raw}",
            "datasetId": dataset_id,
            "source": "huggingface",
            "title": dataset_id_raw,
            "url": f"https://huggingface.co/datasets/{dataset_id_raw}",
            "description": description,
            "tags": tags,
            "license": license_val,
            "usabilityRating": usability_rating,
            "lastUpdatedAt": last_updated_at,
            "crawlObservedAt": crawl_observed_at,
            "files": [],
            "schemaStatus": "unavailable",
            "status": "active",
            "GSI1PK": "DATASET",
            "GSI1SK": last_updated_at,
        }
        return record


def _compute_usability_rating(downloads: int, likes: int) -> Decimal:
    """
    Derive a 0–1 usabilityRating from HF download and like counts.

    Calibrated against real HF API top-100 distribution:
      downloads: median=3.5K, P90=131K, P99=1.3M
      likes:     median=70,   P90=826,  P99=2.9K

    Divisors are set so P99 values score ~0.94 on each dimension.
    Floor at 0.40 aligns the output range with Kaggle's quality-based
    usabilityRating (which skews toward 0.6–1.0 for published datasets).
    """
    download_score = math.log10(downloads + 1) / 6.5
    like_score = math.log10(likes + 1) / 3.5
    popularity = 0.60 * download_score + 0.40 * like_score
    rating = 0.40 + 0.60 * popularity
    return Decimal(str(round(min(rating, 1.0), 4)))

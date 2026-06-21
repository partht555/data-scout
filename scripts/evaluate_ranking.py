"""Read-only baseline versus phrase-aware OpenSearch ranking evaluation.

This intentionally bypasses API Gateway and Bedrock so both variants are
deterministic and do not alter production traffic, the index, or DynamoDB.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from query_router.intent_parser import KeywordIntentParser  # noqa: E402
from query_router.opensearch_repository import build_search_body  # noqa: E402

DEFAULT_CASES = Path(__file__).with_name("ranking_queries.json")
SEARCH_FIELDS = ["title^4", "tags^3", "description^2", "useCaseSummary^2", "schema.name^3", "files.name"]
GENERIC_QUERY_WORDS = {"a", "an", "the", "data", "dataset", "datasets", "find", "for", "give", "me", "on", "show"}


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not all(isinstance(case.get("query"), str) for case in cases):
        raise ValueError("Ranking cases must be a JSON list with a query per case.")
    return cases


def request_for(case: dict[str, Any], limit: int) -> dict[str, Any]:
    return {"query": case["query"], "limit": limit, "cursor": None, "filters": case.get("filters", {})}


def baseline_body(case: dict[str, Any], limit: int) -> dict[str, Any]:
    request = request_for(case, limit)
    return build_search_body(request, KeywordIntentParser().parse(request))


def phrase_aware_body(case: dict[str, Any], limit: int) -> dict[str, Any]:
    """Candidate only: require meaningful terms separately, then boost phrases."""

    body = baseline_body(case, limit)
    boolean = body["query"]["bool"]
    meaningful_terms = [term for term in re.findall(r"[A-Za-z0-9]+", case["query"].lower()) if term not in GENERIC_QUERY_WORDS]
    boolean["must"] = [{
        "multi_match": {
            "query": term,
            "fields": SEARCH_FIELDS,
            "type": "best_fields",
            "operator": "or",
        }
    } for term in meaningful_terms]
    boolean["should"].insert(0, {
        "multi_match": {
            "query": case["query"],
            "fields": SEARCH_FIELDS,
            "type": "phrase",
            "boost": 6,
        }
    })
    boolean["minimum_should_match"] = 0
    return body


def signed_search(endpoint: str, index: str, body: dict[str, Any], region: str, profile: str | None) -> list[dict[str, Any]]:
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    session = boto3.Session(profile_name=profile, region_name=region)
    credentials = session.get_credentials().get_frozen_credentials()
    url = f"{endpoint.rstrip('/')}/{index}/_search"
    payload = json.dumps(body).encode("utf-8")
    signed = AWSRequest(method="POST", url=url, data=payload, headers={"Content-Type": "application/json"})
    SigV4Auth(credentials, "es", region).add_auth(signed)
    with urlopen(Request(url, data=payload, headers=dict(signed.prepare().headers), method="POST"), timeout=10) as response:  # nosec B310: CLI endpoint is supplied by the operator
        return json.loads(response.read().decode("utf-8")).get("hits", {}).get("hits", [])


def rank_of(hits: list[dict[str, Any]], expected_ids: list[str]) -> int | None:
    expected = set(expected_ids)
    for rank, hit in enumerate(hits, start=1):
        if hit.get("_source", {}).get("datasetId") in expected:
            return rank
    return None


def hit_ids(hits: list[dict[str, Any]]) -> list[str]:
    return [hit.get("_source", {}).get("datasetId", "unknown") for hit in hits]


def evaluate(cases: list[dict[str, Any]], search: Any, limit: int) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        baseline = search(baseline_body(case, limit))
        phrase_aware = search(phrase_aware_body(case, limit))
        expected = case.get("expectedDatasetIds", [])
        rows.append({
            "name": case["name"],
            "query": case["query"],
            "expectedRankBaseline": rank_of(baseline, expected),
            "expectedRankPhraseAware": rank_of(phrase_aware, expected),
            "baseline": hit_ids(baseline),
            "phraseAware": hit_ids(phrase_aware),
            "expectEmpty": case.get("expectEmpty", False),
        })
    return rows


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["# Ranking evaluation", "", "| Query | Baseline expected rank | Phrase-aware expected rank |", "|---|---:|---:|"]
    for row in rows:
        baseline = row["expectedRankBaseline"] if row["expectedRankBaseline"] is not None else "—"
        candidate = row["expectedRankPhraseAware"] if row["expectedRankPhraseAware"] is not None else "—"
        lines.append(f"| {row['name']} | {baseline} | {candidate} |")
        lines.append(f"  - baseline: {', '.join(row['baseline']) or '(empty)'}")
        lines.append(f"  - phrase-aware: {', '.join(row['phraseAware']) or '(empty)'}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare read-only OpenSearch ranking candidates.")
    parser.add_argument("--endpoint", default=os.getenv("OPENSEARCH_ENDPOINT"), required=not os.getenv("OPENSEARCH_ENDPOINT"))
    parser.add_argument("--index", default=os.getenv("OPENSEARCH_INDEX", "datasets-v1"))
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--limit", type=int, default=5, choices=range(1, 21))
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of Markdown.")
    args = parser.parse_args()

    def search(body: dict[str, Any]) -> list[dict[str, Any]]:
        return signed_search(args.endpoint, args.index, body, args.region, args.profile)

    rows = evaluate(load_cases(args.cases), search, args.limit)
    print(json.dumps(rows, indent=2) if args.json else render_markdown(rows))


if __name__ == "__main__":
    main()

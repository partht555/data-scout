"""Small command-line client for the Data Curator search API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_ENDPOINT_ENV = "DATA_CURATOR_API_URL"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search the curated dataset catalog.")
    parser.add_argument("query", help="Natural-language dataset request")
    parser.add_argument("--endpoint", default=os.getenv(DEFAULT_ENDPOINT_ENV))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--source", action="append", choices=["kaggle"])
    parser.add_argument("--format", dest="formats", action="append", choices=["csv", "json", "parquet", "tsv", "xlsx"])
    parser.add_argument("--json", action="store_true", help="Print the API response as JSON")
    args = parser.parse_args(argv)
    if not args.endpoint:
        parser.error(f"--endpoint or {DEFAULT_ENDPOINT_ENV} is required")
    return args


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    filters = {key: value for key, value in {"source": args.source, "format": args.formats}.items() if value}
    payload: dict[str, Any] = {"query": args.query, "limit": args.limit}
    if filters:
        payload["filters"] = filters
    return payload


def request_search(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:  # nosec B310: endpoint is explicit user configuration
        return json.loads(response.read().decode("utf-8"))


def render_text(response: dict[str, Any]) -> str:
    results = response.get("results", [])
    if not results:
        return "No matching datasets found. Try broadening the request or removing filters."

    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        files = ", ".join(file["format"] for file in result.get("files", [])) or "format unavailable"
        schema = ", ".join(field["name"] for field in result.get("schema", [])[:6]) or "schema unavailable"
        reasons = ", ".join(result.get("matchedFields", [])) or "keyword match"
        lines.extend(
            [
                f"{index}. {result['title']} ({result['source']}, score {result['score']:.2f})",
                f"   {result['url']}",
                f"   {result['summary']}",
                f"   Formats: {files} | Fields: {schema}",
                f"   Matched: {reasons}",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print("Searching catalog...", file=sys.stderr)
    try:
        response = request_search(args.endpoint, build_payload(args))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"API error ({error.code}): {detail}", file=sys.stderr)
        return 1
    except URLError as error:
        print(f"Could not reach the search API: {error.reason}", file=sys.stderr)
        return 1

    print(json.dumps(response, indent=2) if args.json else render_text(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
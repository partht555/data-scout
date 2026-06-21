"""
Calls Amazon Bedrock Claude Haiku to classify and summarize a dataset record.

Model: anthropic.claude-haiku-4-5-20251001
API:   boto3 bedrock-runtime invoke_model
"""
import json
import logging
import time
from typing import Any

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

DOMAIN_ALLOWLIST = frozenset({
    "healthcare", "finance", "retail", "climate",
    "transportation", "education", "government",
    "sports", "science", "nlp", "computer-vision",
    "geospatial", "robotics", "other",
})
DATA_TYPE_ALLOWLIST = frozenset({
    "tabular", "time-series", "text", "image",
    "audio", "video", "graph", "geospatial", "multimodal", "other",
})

SYSTEM_PROMPT = (
    "You are a dataset classifier. Given metadata about a dataset, return a JSON object "
    "with exactly three fields:\n\n"
    '{\n'
    '  "inferredDomain": "<one of: healthcare, finance, retail, climate, transportation, '
    'education, government, sports, science, nlp, computer-vision, geospatial, robotics, other>",\n'
    '  "inferredDataType": "<one of: tabular, time-series, text, image, audio, video, graph, geospatial, multimodal, other>",\n'
    '  "useCaseSummary": "<one or two factual sentences about what analytical tasks this '
    'dataset supports>"\n'
    "}\n\n"
    "Rules:\n"
    "- Return JSON only. No markdown fences, no explanation, no extra keys.\n"
    "- Choose inferredDomain from the exact allowlist; use \"other\" if uncertain.\n"
    "- Choose inferredDataType from the exact allowlist; use \"other\" if uncertain.\n"
    "- Write useCaseSummary based only on the provided metadata. Do not invent column names "
    "or capabilities. Use an empty string if the metadata is insufficient."
)


_RETRYABLE_BEDROCK_CODES = frozenset({
    "ThrottlingException",
    "ModelNotReadyException",
    "ServiceUnavailableException",
})
_BEDROCK_MAX_ATTEMPTS = 4
_BEDROCK_BASE_DELAY = 2.0  # seconds; doubles each attempt: 2s, 4s, 8s


class BedrockEnricher:
    def __init__(self, bedrock_client):
        self._client = bedrock_client

    def enrich(self, record: dict) -> dict[str, Any]:
        """
        Invoke Claude Haiku with the record's metadata and return enrichment fields.

        Returns:
            {"inferredDomain": str, "inferredDataType": str, "useCaseSummary": str}

        Raises:
            ValueError   — model returned invalid JSON or out-of-allowlist enum value
            ClientError  — Bedrock error that persists after retries
        Both are caught by the caller in handler.py, which sets enrichmentStatus="failed".
        """
        user_message = self._build_user_message(record)
        body_bytes = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 256,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        })

        last_exc: ClientError | None = None
        for attempt in range(_BEDROCK_MAX_ATTEMPTS):
            try:
                response = self._client.invoke_model(
                    modelId=MODEL_ID,
                    contentType="application/json",
                    accept="application/json",
                    body=body_bytes,
                )
                body = json.loads(response["body"].read())
                raw_text = body["content"][0]["text"].strip()
                return self._validate(raw_text)
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code in _RETRYABLE_BEDROCK_CODES and attempt < _BEDROCK_MAX_ATTEMPTS - 1:
                    delay = _BEDROCK_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Bedrock {code} on attempt {attempt + 1}; retrying in {delay:.0f}s"
                    )
                    time.sleep(delay)
                    last_exc = exc
                    continue
                raise
        raise last_exc  # type: ignore[misc]  # unreachable; satisfies type checker

    @staticmethod
    def _build_user_message(record: dict) -> str:
        file_formats = sorted({f["format"] for f in record.get("files", [])})
        schema_names = [
            f"{col.get('name', '')} ({col.get('type', 'unknown')})"
            for col in (record.get("schema") or [])[:20]
        ]

        parts = [
            f"Title: {record.get('title', '')}",
            f"Description: {(record.get('description', '') or '')[:500]}",
            f"Tags: {', '.join(record.get('tags', []))}",
            f"File formats: {', '.join(file_formats) if file_formats else 'unknown'}",
        ]
        if schema_names:
            parts.append(f"Schema columns: {', '.join(schema_names)}")

        return "\n".join(parts)

    @staticmethod
    def _validate(raw_text: str) -> dict[str, Any]:
        # Strip markdown code fences if the model ignores the "no fences" instruction
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]   # drop the opening ```json line
            text = text.rsplit("```", 1)[0]  # drop the closing ```
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model returned non-JSON: {raw_text!r}") from exc

        for field in ("inferredDomain", "inferredDataType", "useCaseSummary"):
            if field not in data:
                raise ValueError(f"Missing required field {field!r} in model response")

        if data["inferredDomain"] not in DOMAIN_ALLOWLIST:
            raise ValueError(
                f"inferredDomain {data['inferredDomain']!r} not in allowlist"
            )
        if data["inferredDataType"] not in DATA_TYPE_ALLOWLIST:
            raise ValueError(
                f"inferredDataType {data['inferredDataType']!r} not in allowlist"
            )

        return {
            "inferredDomain": data["inferredDomain"],
            "inferredDataType": data["inferredDataType"],
            "useCaseSummary": str(data.get("useCaseSummary", "")),
        }

# Bedrock search-plan contract

Bedrock will interpret a user request; it will never receive DynamoDB records,
OpenSearch DSL, AWS identifiers, or authority to select dataset links.

The future invocation must return exactly this JSON object:

```json
{
  "task": "forecast retail sales",
  "keywords": ["retail", "sales"],
  "preferredFormats": ["csv"],
  "requiredColumns": ["date", "sales"],
  "sources": ["kaggle"],
  "licenses": [],
  "recency": "recent",
  "confidence": 0.92
}
```

The Lambda validates every field before using it. Explicit request filters win
over model-proposed values. Invalid, timed-out, or unavailable model output
uses deterministic keyword interpretation instead, so retrieval continues
without inventing recommendations.

`BedrockIntentParser` currently accepts an injected invocation function. It
does not create a Bedrock client or make AWS calls; the production adapter will
be added only after selecting a model and narrowing IAM permissions.

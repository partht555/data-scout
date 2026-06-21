import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from query_router.opensearch_repository import (  # noqa: E402
    InvalidCursor,
    OpenSearchRepository,
    build_search_body,
    decode_cursor,
    encode_cursor,
)


REQUEST = {
    "query": "formula one racing data",
    "limit": 2,
    "cursor": None,
    "filters": {"source": ["kaggle"], "format": ["csv"], "license": ["cc-by-4.0"]},
}
INTENT = {
    "keywords": ["telemetry"],
    "preferredFormats": [],
    "requiredColumns": ["lap_time"],
    "sources": [],
    "licenses": [],
    "recency": "any",
}


class OpenSearchRepositoryTests(unittest.TestCase):
    def test_builds_bounded_active_only_query_with_explicit_filters(self):
        body = build_search_body(REQUEST, INTENT)

        self.assertEqual(body["size"], 3)
        self.assertEqual(body["query"]["bool"]["filter"], [
            {"term": {"status": "active"}},
            {"terms": {"source": ["kaggle"]}},
            {"terms": {"files.format": ["csv"]}},
            {"terms": {"license": ["cc-by-4.0"]}},
        ])
        fields = body["query"]["bool"]["should"][0]["multi_match"]["fields"]
        self.assertIn("schema.name^3", fields)
        self.assertIn("files.name", fields)
        self.assertEqual(body["query"]["bool"]["should"][1]["match"]["schema.name"]["query"], "lap_time")

    def test_cursor_is_opaque_and_attached_as_search_after(self):
        cursor = encode_cursor([1.25, "kaggle:1"])
        self.assertEqual(decode_cursor(cursor), [1.25, "kaggle:1"])
        request = dict(REQUEST, cursor=cursor)
        self.assertEqual(build_search_body(request, INTENT)["search_after"], [1.25, "kaggle:1"])
        with self.assertRaises(InvalidCursor):
            decode_cursor("not-a-cursor")

    def test_model_preferences_do_not_become_hidden_hard_filters(self):
        request = dict(REQUEST, filters={})
        body = build_search_body(request, INTENT)
        self.assertEqual(body["query"]["bool"]["filter"], [{"term": {"status": "active"}}])

    def test_recent_intent_uses_a_function_score_recency_boost(self):
        body = build_search_body(REQUEST, dict(INTENT, recency="recent"))
        self.assertIn("function_score", body["query"])
        self.assertIn("gauss", body["query"]["function_score"]["functions"][0])

    def test_shapes_public_results_deduplicates_and_creates_next_cursor(self):
        fixture = {
            "hits": {"hits": [
                {"_score": 10, "sort": [10, "kaggle:formula"], "_source": {
                    "datasetId": "kaggle:formula", "title": "Formula racing telemetry", "url": "https://www.kaggle.com/datasets/example/formula",
                    "source": "kaggle", "status": "active", "useCaseSummary": "Predict lap performance.",
                    "description": "Fallback description", "tags": ["racing"],
                    "files": [{"name": "laps.csv", "format": "csv"}], "schema": [{"name": "lap_time", "type": "number"}],
                }},
                {"_score": 8, "sort": [8, "kaggle:formula"], "_source": {
                    "datasetId": "kaggle:formula", "title": "Formula racing telemetry", "url": "https://www.kaggle.com/datasets/example/formula",
                    "status": "active",
                }},
                {"_score": 6, "sort": [6, "kaggle:next"], "_source": {
                    "datasetId": "kaggle:next", "title": "Other", "url": "https://www.kaggle.com/datasets/example/next", "status": "active",
                }},
            ]}
        }
        results, cursor = OpenSearchRepository("https://example.com", transport=lambda _: fixture).search(REQUEST, INTENT)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["summary"], "Predict lap performance.")
        self.assertEqual(results[0]["score"], 1.0)
        self.assertIn("schema.name", results[0]["matchedFields"])
        self.assertEqual(decode_cursor(cursor), [8, "kaggle:formula"])

    def test_missing_files_and_schema_are_compact_empty_arrays(self):
        fixture = {"hits": {"hits": [{"_score": 1, "sort": [1, "kaggle:one"], "_source": {
            "datasetId": "kaggle:one", "title": "Racing data", "url": "https://www.kaggle.com/datasets/example/one", "status": "active",
            "description": "Simple description",
        }}]}}
        request = dict(REQUEST, limit=1, filters={})
        results, cursor = OpenSearchRepository("https://example.com", transport=lambda _: fixture).search(request, INTENT)
        self.assertIsNone(cursor)
        self.assertEqual(results[0]["files"], [])
        self.assertEqual(results[0]["schema"], [])
        self.assertEqual(results[0]["summary"], "Simple description")


if __name__ == "__main__":
    unittest.main()

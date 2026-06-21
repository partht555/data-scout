import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from query_router.handler import lambda_handler  # noqa: E402


class QueryRouterTests(unittest.TestCase):
    context = SimpleNamespace(aws_request_id="test-request-id")

    def test_accepts_a_valid_search_request_with_defaults(self):
        response = lambda_handler(
            {"body": json.dumps({"query": "food datasets for nutrition analysis"})},
            self.context,
        )

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["query"], "food datasets for nutrition analysis")
        self.assertEqual(body["results"][0]["datasetId"], "kaggle:utsavdey1410/food-nutrition-dataset")
        self.assertEqual(body["interpretedIntent"]["mode"], "keyword")
        self.assertEqual(body["interpretedIntent"]["keywords"], ["food", "datasets", "for", "nutrition", "analysis"])

    def test_accepts_filters_and_normalizes_values(self):
        response = lambda_handler(
            {
                "body": json.dumps(
                    {
                        "query": "nutrition CSV files",
                        "limit": 2,
                        "filters": {"source": ["KAGGLE"], "format": ["CSV"]},
                    }
                )
            },
            self.context,
        )

        self.assertEqual(response["statusCode"], 200)
        intent = json.loads(response["body"])["interpretedIntent"]
        self.assertEqual(intent["sources"], ["kaggle"])
        self.assertEqual(intent["preferredFormats"], ["csv"])

    def test_rejects_short_query(self):
        response = lambda_handler({"body": json.dumps({"query": "hi"})}, self.context)

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertEqual(body["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(body["requestId"], "test-request-id")

    def test_rejects_unknown_filter_and_bad_limit(self):
        response = lambda_handler(
            {
                "body": json.dumps(
                    {"query": "nutrition data", "limit": 21, "filters": {"region": ["US"]}}
                )
            },
            self.context,
        )

        self.assertEqual(response["statusCode"], 400)
        self.assertIn("limit", json.loads(response["body"])["error"]["message"])


if __name__ == "__main__":
    unittest.main()

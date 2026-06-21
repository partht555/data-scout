import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from query_router.search_handler import lambda_handler  # noqa: E402


class MockSearchTests(unittest.TestCase):
    context = SimpleNamespace(aws_request_id="test-request-id")

    def request(self, body):
        response = lambda_handler({"body": json.dumps(body)}, self.context)
        return response["statusCode"], json.loads(response["body"])

    def test_food_query_returns_nutrition_dataset(self):
        status, body = self.request({"query": "food datasets for nutrition analysis"})

        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["datasetId"], "kaggle:utsavdey1410/food-nutrition-dataset")
        self.assertIn("tags", body["results"][0]["matchedFields"])

    def test_format_filter_returns_only_csv_records(self):
        status, body = self.request(
            {"query": "sales forecasting", "filters": {"source": ["kaggle"], "format": ["csv"]}}
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["results"])
        self.assertEqual(body["results"][0]["title"], "Retail Sales Data")
        self.assertTrue(all(file["format"] == "csv" for file in body["results"][0]["files"]))

    def test_no_match_returns_success_with_empty_results(self):
        status, body = self.request({"query": "quantum entanglement qubits"})

        self.assertEqual(status, 200)
        self.assertEqual(body["results"], [])
        self.assertIsNone(body["nextCursor"])

    def test_limit_caps_mock_results(self):
        status, body = self.request({"query": "data", "limit": 1})

        self.assertEqual(status, 200)
        self.assertEqual(len(body["results"]), 1)


if __name__ == "__main__":
    unittest.main()

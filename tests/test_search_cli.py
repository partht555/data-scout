import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search_datasets import build_payload, render_text  # noqa: E402


class SearchCliTests(unittest.TestCase):
    def test_build_payload_omits_empty_filters(self):
        args = SimpleNamespace(query="retail sales", limit=3, source=None, formats=None)
        self.assertEqual(build_payload(args), {"query": "retail sales", "limit": 3})

    def test_build_payload_includes_explicit_filters(self):
        args = SimpleNamespace(query="retail sales", limit=3, source=["kaggle"], formats=["csv"])
        self.assertEqual(
            build_payload(args),
            {"query": "retail sales", "limit": 3, "filters": {"source": ["kaggle"], "format": ["csv"]}},
        )

    def test_render_text_shows_empty_state(self):
        self.assertIn("broadening", render_text({"results": []}))

    def test_render_text_shows_recommendation_details(self):
        output = render_text(
            {"results": [{"title": "Retail Sales", "source": "kaggle", "score": 0.91, "url": "https://example.test", "summary": "Sales by month.", "files": [{"format": "csv"}], "schema": [{"name": "date"}, {"name": "sales"}], "matchedFields": ["title", "schema.name"]}]}
        )
        self.assertIn("Retail Sales", output)
        self.assertIn("Formats: csv", output)
        self.assertIn("Fields: date, sales", output)


if __name__ == "__main__":
    unittest.main()
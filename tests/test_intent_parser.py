import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from query_router.intent_parser import (  # noqa: E402
    BedrockIntentParser,
    KeywordIntentParser,
    build_model_input,
    interpret_request,
    validate_search_plan,
)


def request(filters=None):
    return {"query": "Find recent retail sales CSV data", "limit": 5, "filters": filters or {}}


def plan():
    return {
        "task": "forecast retail sales",
        "keywords": ["retail", "sales"],
        "preferredFormats": ["csv"],
        "requiredColumns": ["date", "sales"],
        "sources": ["kaggle"],
        "licenses": [],
        "recency": "recent",
        "confidence": 0.92,
    }


class IntentParserTests(unittest.TestCase):
    def test_valid_bedrock_plan_is_normalized(self):
        parsed = validate_search_plan(plan())
        self.assertEqual(parsed["mode"], "bedrock")
        self.assertEqual(parsed["requiredColumns"], ["date", "sales"])
        self.assertEqual(parsed["confidence"], 0.92)

    def test_explicit_filters_override_model_values(self):
        parser = BedrockIntentParser(lambda _: plan())
        parsed = parser.parse(request({"format": ["parquet"], "source": ["kaggle"], "license": ["cc0"]}))
        self.assertEqual(parsed["preferredFormats"], ["parquet"])
        self.assertEqual(parsed["licenses"], ["cc0"])

    def test_model_dsl_is_rejected_and_falls_back_to_keywords(self):
        unsafe_plan = {**plan(), "rawOpenSearchDsl": {"match_all": {}}}
        parsed = interpret_request(request(), BedrockIntentParser(lambda _: unsafe_plan))
        self.assertEqual(parsed["mode"], "keyword")
        self.assertIn("retail", parsed["keywords"])

    def test_invalid_enum_falls_back_to_keywords(self):
        invalid = {**plan(), "preferredFormats": ["sql"]}
        parsed = interpret_request(request(), BedrockIntentParser(lambda _: invalid))
        self.assertEqual(parsed["mode"], "keyword")

    def test_model_input_exposes_only_the_bounded_contract(self):
        model_input = build_model_input(request())
        self.assertEqual(model_input["allowedSources"], ["kaggle"])
        self.assertNotIn("rawOpenSearchDsl", model_input["schema"])

    def test_keyword_parser_remains_available_without_bedrock(self):
        parsed = KeywordIntentParser().parse(request({"format": ["csv"]}))
        self.assertEqual(parsed["mode"], "keyword")
        self.assertEqual(parsed["preferredFormats"], ["csv"])


if __name__ == "__main__":
    unittest.main()

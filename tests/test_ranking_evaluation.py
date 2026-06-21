import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_ranking import evaluate, phrase_aware_body, rank_of  # noqa: E402


class RankingEvaluationTests(unittest.TestCase):
    def test_phrase_candidate_requires_meaningful_terms_and_boosts_the_phrase(self):
        body = phrase_aware_body({"name": "housing", "query": "housing prices"}, 5)
        boolean = body["query"]["bool"]
        self.assertEqual([item["multi_match"]["query"] for item in boolean["must"]], ["housing", "prices"])
        self.assertEqual(boolean["should"][0]["multi_match"]["type"], "phrase")
        self.assertEqual(boolean["minimum_should_match"], 0)

    def test_rank_and_report_compare_each_variant_without_writes(self):
        hits = {
            "housing prices": [
                {"_source": {"datasetId": "kaggle:crypto"}},
                {"_source": {"datasetId": "kaggle:zillow"}},
            ]
        }
        rows = evaluate(
            [{"name": "housing", "query": "housing prices", "expectedDatasetIds": ["kaggle:zillow"]}],
            lambda _: hits["housing prices"],
            5,
        )
        self.assertEqual(rank_of(hits["housing prices"], ["kaggle:zillow"]), 2)
        self.assertEqual(rows[0]["expectedRankBaseline"], 2)
        self.assertEqual(rows[0]["expectedRankPhraseAware"], 2)


if __name__ == "__main__":
    unittest.main()

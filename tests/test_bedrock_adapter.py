import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from query_router.bedrock_adapter import BedrockIntentInvoker, MODEL_ID  # noqa: E402
from query_router.intent_parser import build_model_input


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.kwargs = None

    def invoke_model(self, **kwargs):
        self.kwargs = kwargs
        return {"body": io.BytesIO(json.dumps({"content": [{"text": self.text}]}).encode())}


class BedrockAdapterTests(unittest.TestCase):
    def test_sends_only_search_plan_input_and_parses_json(self):
        client = FakeClient('```json\n{"task":"racing","keywords":[],"preferredFormats":[],"requiredColumns":[],"sources":[],"licenses":[],"recency":"any","suggestedLimit":5,"confidence":0.8}\n```')
        result = BedrockIntentInvoker(client)(build_model_input({"query": "racing data", "filters": {}}))

        self.assertEqual(result["task"], "racing")
        self.assertEqual(client.kwargs["modelId"], MODEL_ID)
        prompt = json.loads(client.kwargs["body"])
        self.assertEqual(json.loads(prompt["messages"][0]["content"])["query"], "racing data")

    def test_provider_failure_becomes_keyword_fallback_signal(self):
        class FailingClient:
            def invoke_model(self, **kwargs):
                raise RuntimeError("throttled")

        with self.assertRaises(OSError):
            BedrockIntentInvoker(FailingClient())({"query": "racing data"})


if __name__ == "__main__":
    unittest.main()

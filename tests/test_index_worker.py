import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from index_worker.handler import (  # noqa: E402
    INDEX_MAPPING,
    build_backfill_operations,
    build_bulk_operations,
    deserialize_image,
    to_search_document,
)


def image(status="active"):
    return {
        "datasetId": {"S": "kaggle:demo/retail-sales"},
        "version": {"N": "3"},
        "status": {"S": status},
        "source": {"S": "kaggle"},
        "title": {"S": "Retail Sales"},
        "url": {"S": "https://www.kaggle.com/datasets/demo/retail-sales"},
        "description": {"S": "Monthly retail sales."},
        "useCaseSummary": {"S": "Forecast retail revenue."},
        "tags": {"L": [{"S": "retail"}, {"S": "forecasting"}]},
        "license": {"S": "CC0"},
        "files": {"L": [{"M": {"name": {"S": "sales.csv"}, "format": {"S": "csv"}}}]},
        "schemaStatus": {"S": "unavailable"},
        "lastUpdatedAt": {"S": "2026-06-20T00:00:00Z"},
        "crawlObservedAt": {"S": "2026-06-21T00:00:00Z"},
        "inferredDomain": {"S": "finance"},
        "inferredDataType": {"S": "tabular"},
        "enrichmentStatus": {"S": "available"},
        "usabilityRating": {"N": "0.94"},
    }


def stream_record(name="INSERT", new_status="active"):
    return {"eventID": "event-1", "eventName": name, "dynamodb": {"NewImage": image(new_status), "OldImage": image()}}


class IndexWorkerTests(unittest.TestCase):
    def test_deserializes_the_populated_table_shape(self):
        record = deserialize_image(image())
        self.assertEqual(record["tags"], ["retail", "forecasting"])
        self.assertEqual(record["files"][0]["format"], "csv")
        self.assertEqual(record["usabilityRating"], 0.94)

    def test_active_record_becomes_versioned_index_operation(self):
        operation = build_bulk_operations([stream_record()])[0]
        action, document = map(json.loads, operation["line"].split("\n"))
        self.assertEqual(action["index"]["_index"], "datasets-v1")
        self.assertEqual(action["index"]["version_type"], "external_gte")
        self.assertEqual(document["useCaseSummary"], "Forecast retail revenue.")

    def test_inactive_record_becomes_delete_operation(self):
        operation = build_bulk_operations([stream_record(new_status="inactive")])[0]
        self.assertIn("delete", json.loads(operation["line"]))

    def test_remove_event_becomes_delete_operation(self):
        operation = build_bulk_operations([stream_record(name="REMOVE")])[0]
        self.assertIn("delete", json.loads(operation["line"]))

    def test_public_search_document_preserves_metadata_fields(self):
        document = to_search_document(deserialize_image(image()))
        self.assertEqual(document["status"], "active")
        self.assertEqual(document["inferredDomain"], "finance")
        self.assertEqual(document["version"], 3)

    def test_backfill_indexes_active_records_and_skips_inactive_ones(self):
        active = deserialize_image(image())
        inactive = deserialize_image(image("inactive"))
        operations = build_backfill_operations([active, inactive])
        self.assertEqual(len(operations), 1)
        action, document = map(json.loads, operations[0]["line"].split("\n"))
        self.assertEqual(action["index"]["_id"], "kaggle:demo/retail-sales")
        self.assertEqual(document["status"], "active")

    def test_index_mapping_covers_search_and_filter_fields(self):
        properties = INDEX_MAPPING["mappings"]["properties"]
        self.assertEqual(properties["title"]["type"], "text")
        self.assertEqual(properties["files"]["properties"]["format"]["type"], "keyword")
        self.assertEqual(properties["status"]["type"], "keyword")


if __name__ == "__main__":
    unittest.main()

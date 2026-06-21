import os
import unittest

os.environ["CDK_SKIP_BUNDLING"] = "1"

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Template  # noqa: E402

from stacks.index_worker_stack import IndexWorkerStack  # noqa: E402
from stacks.metadata_store_stack import MetadataStoreStack  # noqa: E402


class IndexWorkerStackTests(unittest.TestCase):
    def setUp(self):
        app = cdk.App()
        metadata = MetadataStoreStack(app, "Metadata")
        self.stack = IndexWorkerStack(
            app,
            "Indexer",
            table=metadata.table,
            index_worker_role=metadata.index_worker_role,
            dead_letter_queue=metadata.index_worker_dlq,
        )
        self.template = Template.from_stack(self.stack)

    def test_creates_stream_worker_backfill_and_dead_letter_queue(self):
        self.template.resource_count_is("AWS::Lambda::Function", 2)
        self.template.resource_count_is("AWS::Lambda::EventSourceMapping", 1)

    def test_stream_mapping_uses_partial_batch_failures(self):
        self.template.has_resource_properties(
            "AWS::Lambda::EventSourceMapping",
            {"BatchSize": 25, "FunctionResponseTypes": ["ReportBatchItemFailures"]},
        )


if __name__ == "__main__":
    unittest.main()

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    CfnParameter,
    Duration,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lmb,
    aws_lambda_event_sources as event_sources,
    aws_sqs as sqs,
)
from constructs import Construct


class IndexWorkerStack(cdk.Stack):
    """Projects authoritative DatasetMetadata records into OpenSearch."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: dynamodb.ITable,
        index_worker_role: iam.IRole,
        dead_letter_queue: sqs.IQueue,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        endpoint = CfnParameter(
            self,
            "OpenSearchEndpoint",
            type="String",
            description="Signed HTTPS endpoint, for example https://search-example.us-east-1.es.amazonaws.com",
        )
        domain_arn = CfnParameter(
            self,
            "OpenSearchDomainArn",
            type="String",
            description="OpenSearch domain ARN used to scope data-plane permissions.",
        )

        # The metadata stack already grants stream reads to this role. Backfill
        # also needs a table scan; no write permissions are granted here.
        table.grant_read_data(index_worker_role)
        iam.Policy(
            self,
            "IndexWorkerOpenSearchPolicy",
            roles=[index_worker_role],
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["es:ESHttpDelete", "es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut"],
                    resources=[f"{domain_arn.value_as_string}/*"],
                )
            ],
        )

        code = lmb.Code.from_asset("../src")
        common_environment = {
            "OPENSEARCH_ENDPOINT": endpoint.value_as_string,
            "OPENSEARCH_INDEX": "datasets-v1",
        }
        self.index_worker = lmb.Function(
            self,
            "IndexWorker",
            function_name="dataset-index-worker",
            runtime=lmb.Runtime.PYTHON_3_12,
            handler="index_worker.handler.lambda_handler",
            code=code,
            role=index_worker_role,
            timeout=Duration.seconds(30),
            memory_size=512,
            environment=common_environment,
            description="Projects DatasetMetadata DynamoDB Stream records into OpenSearch.",
        )
        self.index_worker.add_event_source(
            event_sources.DynamoEventSource(
                table,
                starting_position=lmb.StartingPosition.LATEST,
                batch_size=25,
                bisect_batch_on_error=True,
                retry_attempts=3,
                on_failure=event_sources.SqsDlq(dead_letter_queue),
                report_batch_item_failures=True,
            )
        )

        self.backfill_worker = lmb.Function(
            self,
            "IndexBackfillWorker",
            function_name="dataset-index-backfill",
            runtime=lmb.Runtime.PYTHON_3_12,
            handler="index_worker.backfill.lambda_handler",
            code=code,
            role=index_worker_role,
            timeout=Duration.minutes(15),
            memory_size=1024,
            environment={**common_environment, "DATASET_TABLE_NAME": table.table_name, "BACKFILL_BATCH_SIZE": "100"},
            description="Manually backfills active DatasetMetadata records into OpenSearch.",
        )

        CfnOutput(self, "IndexWorkerFunctionName", value=self.index_worker.function_name)
        CfnOutput(self, "BackfillFunctionName", value=self.backfill_worker.function_name)
        CfnOutput(self, "IndexWorkerDlqUrl", value=dead_letter_queue.queue_url)

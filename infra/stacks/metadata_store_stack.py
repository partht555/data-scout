import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
)
from constructs import Construct


class MetadataStoreStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── DynamoDB table ──────────────────────────────────────────────────
        self.table = dynamodb.Table(
            self,
            "DatasetMetadata",
            table_name="DatasetMetadata",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            point_in_time_recovery=True,
            # TTL intentionally omitted — items are retained indefinitely and
            # soft-deleted via status="inactive" rather than expiring.
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI1: list all datasets ordered by recency (GSI1PK constant "DATASET",
        # GSI1SK = lastUpdatedAt ISO string written by the crawler).
        # Included at creation time — adding a GSI post-creation requires
        # UpdateTable and is more operationally complex.
        self.table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ── Crawler Lambda role ─────────────────────────────────────────────
        # PutItem + UpdateItem + GetItem on this table only.
        # DeleteItem is intentionally absent — soft-delete via status field only.
        self.crawler_role = iam.Role(
            self,
            "CrawlerLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            description="IAM role for source crawler Lambdas (Kaggle and future sources)",
        )

        self.table.grant(
            self.crawler_role,
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:GetItem",
        )

        # ── Index worker Lambda role ────────────────────────────────────────
        # Stream reads only — scoped to the stream ARN, not the table data plane.
        self.index_worker_role = iam.Role(
            self,
            "IndexWorkerLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            description="IAM role for DynamoDB Streams index worker Lambda",
        )

        self.index_worker_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:GetRecords",
                    "dynamodb:GetShardIterator",
                    "dynamodb:DescribeStream",
                    "dynamodb:ListStreams",
                ],
                resources=[self.table.table_stream_arn],
            )
        )

        # ── CloudFormation outputs ──────────────────────────────────────────
        # Future stacks import these via Fn.import_value(...) to avoid tight
        # cross-stack deployment order dependencies.
        CfnOutput(
            self, "TableArn",
            value=self.table.table_arn,
            export_name="DatasetMetadataTableArn",
        )
        CfnOutput(
            self, "TableStreamArn",
            value=self.table.table_stream_arn,
            export_name="DatasetMetadataStreamArn",
        )
        CfnOutput(
            self, "CrawlerRoleArn",
            value=self.crawler_role.role_arn,
            export_name="CrawlerLambdaRoleArn",
        )
        CfnOutput(
            self, "IndexWorkerRoleArn",
            value=self.index_worker_role.role_arn,
            export_name="IndexWorkerLambdaRoleArn",
        )

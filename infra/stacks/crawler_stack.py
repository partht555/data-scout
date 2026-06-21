import os
import shutil

import jsii
import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    Fn,
    ILocalBundling,
    aws_iam as iam,
    aws_lambda as lmb,
    aws_secretsmanager as sm,
)
from constructs import Construct

# Standard AWS SAM build image for Python 3.12 Lambda bundling — no auth required
_BUNDLING_IMAGE = "public.ecr.aws/sam/build-python3.12"


@jsii.implements(ILocalBundling)
class _LocalBundler:
    """
    Local bundler for CDK unit tests.

    When CDK_SKIP_BUNDLING=1 is set (pytest), returns True so CDK skips
    Docker and stages the source files only — sufficient to synthesize the
    CloudFormation template for assertion tests without running pip install.
    In real deployments (env var absent), returns False so CDK falls back to
    the Docker image, which runs pip install and produces a proper Lambda zip.
    """

    def __init__(self, source_path: str) -> None:
        self._source_path = os.path.abspath(source_path)

    def try_bundle(self, output_dir: str, *, options: cdk.BundlingOptions = None) -> bool:
        if not os.environ.get("CDK_SKIP_BUNDLING"):
            return False  # real deploy: let Docker handle dependency installation
        for item in os.listdir(self._source_path):
            src = os.path.join(self._source_path, item)
            dst = os.path.join(output_dir, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            else:
                shutil.copytree(src, dst, dirs_exist_ok=True)
        return True


class CrawlerStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Kaggle credentials secret ───────────────────────────────────────
        # Deployed as an empty placeholder. Populate after deploy:
        #   aws secretsmanager put-secret-value \
        #     --secret-id data-curator/kaggle-credentials \
        #     --secret-string '{"username":"<user>","key":"<api_key>"}'
        kaggle_secret = sm.Secret(
            self,
            "KaggleCredentials",
            secret_name="data-curator/kaggle-credentials",
            description=(
                "Kaggle API credentials for the crawler Lambda. "
                'Populate manually: {"username":"<user>","key":"<api_key>"}'
            ),
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # ── Import DynamoDB table ARN from MetadataStoreStack ───────────────
        table_arn = Fn.import_value("DatasetMetadataTableArn")

        # ── IAM role with all required permissions ──────────────────────────
        # A fresh role is defined here rather than patching the stub
        # CrawlerLambdaRole from MetadataStoreStack — CDK cannot add policies
        # to imported roles.
        crawler_role = iam.Role(
            self,
            "KaggleCrawlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            description="Complete IAM role for the Kaggle crawler Lambda",
        )

        # Secrets Manager — scoped to Kaggle secret only
        crawler_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["secretsmanager:GetSecretValue"],
                resources=[kaggle_secret.secret_arn],
            )
        )

        # DynamoDB — table + GSI index ARNs; no DeleteItem
        crawler_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:GetItem",
                ],
                resources=[table_arn, f"{table_arn}/index/*"],
            )
        )

        # Bedrock — Claude Haiku model ARN scoped to deployment region
        # Newer Claude models require an inference profile rather than a direct model ID.
        # IAM must allow both the inference profile ARN and the underlying foundation model ARN.
        crawler_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
                    f"arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
                ],
            )
        )

        # ── Lambda function ─────────────────────────────────────────────────
        self.fn = lmb.Function(
            self,
            "KaggleCrawlerFn",
            function_name="kaggle-crawler",
            runtime=lmb.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lmb.Code.from_asset(
                path="../lambdas/kaggle_crawler",
                bundling=cdk.BundlingOptions(
                    image=cdk.DockerImage.from_registry(_BUNDLING_IMAGE),
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output --quiet "
                        "&& cp -r . /asset-output",
                    ],
                    local=_LocalBundler("../lambdas/kaggle_crawler"),
                ),
            ),
            role=crawler_role,
            timeout=Duration.minutes(15),
            memory_size=512,
            environment={
                "KAGGLE_SECRET_ARN": kaggle_secret.secret_arn,
                "DATASET_TABLE_NAME": "DatasetMetadata",
            },
            description=(
                "Crawls Kaggle for dataset metadata, enriches via Bedrock Haiku, "
                "and upserts records to DynamoDB."
            ),
        )

        # ── CloudFormation outputs ──────────────────────────────────────────
        CfnOutput(
            self, "KaggleCrawlerFunctionArn",
            value=self.fn.function_arn,
            export_name="KaggleCrawlerFunctionArn",
            description="Register this ARN in SSM for the Step Functions orchestrator",
        )
        CfnOutput(
            self, "KaggleSecretArn",
            value=kaggle_secret.secret_arn,
            export_name="KaggleCredentialsSecretArn",
            description="Populate with Kaggle credentials before running crawls",
        )

        # ── Hugging Face crawler ────────────────────────────────────────────
        # No mandatory secret — public HF API works without auth.
        # Optionally populate data-curator/huggingface-credentials with
        # {"token": "<hf_token>"} after deploy for higher rate limits.
        hf_secret = sm.Secret(
            self,
            "HuggingFaceCredentials",
            secret_name="data-curator/huggingface-credentials",
            description=(
                "Optional HF API token for the HuggingFace crawler Lambda. "
                'Populate manually: {"token":"<hf_token>"}. '
                "Leave empty to crawl anonymously (lower rate limit)."
            ),
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        hf_crawler_role = iam.Role(
            self,
            "HuggingFaceCrawlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            description="IAM role for the HuggingFace crawler Lambda",
        )

        hf_crawler_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["secretsmanager:GetSecretValue"],
                resources=[hf_secret.secret_arn],
            )
        )

        hf_crawler_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:GetItem",
                ],
                resources=[table_arn, f"{table_arn}/index/*"],
            )
        )

        hf_crawler_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
                    f"arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
                ],
            )
        )

        self.hf_fn = lmb.Function(
            self,
            "HuggingFaceCrawlerFn",
            function_name="huggingface-crawler",
            runtime=lmb.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lmb.Code.from_asset(
                path="../lambdas/huggingface_crawler",
                bundling=cdk.BundlingOptions(
                    image=cdk.DockerImage.from_registry(_BUNDLING_IMAGE),
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output --quiet "
                        "&& cp -r . /asset-output",
                    ],
                    local=_LocalBundler("../lambdas/huggingface_crawler"),
                ),
            ),
            role=hf_crawler_role,
            timeout=Duration.minutes(15),
            memory_size=512,
            environment={
                "HF_SECRET_ARN": hf_secret.secret_arn,
                "DATASET_TABLE_NAME": "DatasetMetadata",
            },
            description=(
                "Crawls Hugging Face Hub for dataset metadata, enriches via Bedrock Haiku, "
                "and upserts records to DynamoDB."
            ),
        )

        CfnOutput(
            self, "HuggingFaceCrawlerFunctionArn",
            value=self.hf_fn.function_arn,
            export_name="HuggingFaceCrawlerFunctionArn",
            description="Register this ARN in SSM for the Step Functions orchestrator",
        )
        CfnOutput(
            self, "HuggingFaceSecretArn",
            value=hf_secret.secret_arn,
            export_name="HuggingFaceCredentialsSecretArn",
            description="Optionally populate with HF token for higher rate limits",
        )

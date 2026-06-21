import os

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest
from stacks.metadata_store_stack import MetadataStoreStack
from stacks.crawler_stack import CrawlerStack


@pytest.fixture(scope="module")
def template():
    # Tell _LocalBundler to skip Docker — copies source files only, which is
    # sufficient to synthesize the CloudFormation template for assertion tests.
    os.environ["CDK_SKIP_BUNDLING"] = "1"

    app = cdk.App(context={"account": "123456789012", "region": "us-east-1"})
    # MetadataStoreStack must be synthesized first so its Fn.import_value exports resolve
    metadata_stack = MetadataStoreStack(app, "TestMetadataStore")
    crawler_stack = CrawlerStack(app, "TestCrawler")
    crawler_stack.add_dependency(metadata_stack)
    return assertions.Template.from_stack(crawler_stack)


def test_lambda_function_name(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"FunctionName": "kaggle-crawler"},
    )


def test_lambda_runtime(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"Runtime": "python3.12"},
    )


def test_lambda_handler(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"Handler": "handler.handler"},
    )


def test_lambda_timeout_15_minutes(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"Timeout": 900},
    )


def test_lambda_memory(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"MemorySize": 512},
    )


def test_lambda_env_table_name(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": assertions.Match.object_like({
                    "DATASET_TABLE_NAME": "DatasetMetadata",
                })
            }
        },
    )


def test_secret_name(template):
    template.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {"Name": "data-curator/kaggle-credentials"},
    )


def test_secret_deletion_policy_retain(template):
    resources = template.find_resources("AWS::SecretsManager::Secret")
    for resource in resources.values():
        assert resource.get("DeletionPolicy") == "Retain", (
            "Kaggle credentials secret must have DeletionPolicy=Retain"
        )


def test_role_has_secretsmanager_permission(template):
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "secretsmanager:GetSecretValue",
                        "Effect": "Allow",
                    })
                ])
            })
        },
    )


def test_role_has_bedrock_permission(template):
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "bedrock:InvokeModel",
                        "Effect": "Allow",
                    })
                ])
            })
        },
    )


def test_role_has_dynamodb_write_permissions(template):
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": assertions.Match.array_with([
                            "dynamodb:PutItem",
                            "dynamodb:UpdateItem",
                            "dynamodb:GetItem",
                        ]),
                        "Effect": "Allow",
                    })
                ])
            })
        },
    )


def test_no_delete_item_permission(template):
    policies = template.find_resources("AWS::IAM::Policy")
    for policy in policies.values():
        stmts = (
            policy.get("Properties", {})
            .get("PolicyDocument", {})
            .get("Statement", [])
        )
        for stmt in stmts:
            actions = stmt.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            assert "dynamodb:DeleteItem" not in actions, (
                "No role in CrawlerStack may have dynamodb:DeleteItem"
            )


def test_crawler_function_arn_output(template):
    template.has_output(
        "KaggleCrawlerFunctionArn",
        {"Export": {"Name": "KaggleCrawlerFunctionArn"}},
    )


def test_kaggle_secret_arn_output(template):
    template.has_output(
        "KaggleSecretArn",
        {"Export": {"Name": "KaggleCredentialsSecretArn"}},
    )

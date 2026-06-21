import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest
from stacks.metadata_store_stack import MetadataStoreStack


@pytest.fixture(scope="module")
def template():
    app = cdk.App(context={"account": "123456789012", "region": "us-east-1"})
    stack = MetadataStoreStack(app, "TestMetadataStore")
    return assertions.Template.from_stack(stack)


def test_table_name(template):
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"TableName": "DatasetMetadata"},
    )


def test_billing_mode_pay_per_request(template):
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"BillingMode": "PAY_PER_REQUEST"},
    )


def test_stream_view_type(template):
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"StreamSpecification": {"StreamViewType": "NEW_AND_OLD_IMAGES"}},
    )


def test_pitr_enabled(template):
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}},
    )


def test_ttl_not_configured(template):
    resources = template.find_resources("AWS::DynamoDB::Table")
    for resource in resources.values():
        props = resource.get("Properties", {})
        assert "TimeToLiveSpecification" not in props, (
            "TTL must not be configured on DatasetMetadata table"
        )


def test_partition_key(template):
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "KeySchema": assertions.Match.array_with([
                {"AttributeName": "PK", "KeyType": "HASH"},
            ])
        },
    )


def test_sort_key(template):
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "KeySchema": assertions.Match.array_with([
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ])
        },
    )


def test_gsi1_exists(template):
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "GlobalSecondaryIndexes": assertions.Match.array_with([
                assertions.Match.object_like({
                    "IndexName": "GSI1",
                    "KeySchema": assertions.Match.array_with([
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ]),
                })
            ])
        },
    )


def test_deletion_policy_retain(template):
    resources = template.find_resources("AWS::DynamoDB::Table")
    for resource in resources.values():
        assert resource.get("DeletionPolicy") == "Retain", (
            "DatasetMetadata table must have DeletionPolicy=Retain"
        )


def test_crawler_role_allowed_actions(template):
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


def test_no_role_has_delete_item(template):
    policies = template.find_resources("AWS::IAM::Policy")
    for policy in policies.values():
        statements = (
            policy.get("Properties", {})
            .get("PolicyDocument", {})
            .get("Statement", [])
        )
        for statement in statements:
            actions = statement.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            assert "dynamodb:DeleteItem" not in actions, (
                "No role may have dynamodb:DeleteItem permission"
            )


def test_index_worker_stream_actions(template):
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": assertions.Match.array_with([
                            "dynamodb:GetRecords",
                            "dynamodb:GetShardIterator",
                            "dynamodb:DescribeStream",
                            "dynamodb:ListStreams",
                        ]),
                        "Effect": "Allow",
                    })
                ])
            })
        },
    )

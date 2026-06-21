import os

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest
from stacks.metadata_store_stack import MetadataStoreStack
from stacks.crawler_stack import CrawlerStack
from stacks.orchestrator_stack import OrchestratorStack


@pytest.fixture(scope="module")
def template():
    os.environ["CDK_SKIP_BUNDLING"] = "1"
    app = cdk.App(context={"account": "123456789012", "region": "us-east-1"})
    metadata_stack = MetadataStoreStack(app, "TestMetadataStore")
    crawler_stack = CrawlerStack(app, "TestCrawler")
    crawler_stack.add_dependency(metadata_stack)
    orchestrator_stack = OrchestratorStack(app, "TestOrchestrator")
    orchestrator_stack.add_dependency(crawler_stack)
    return assertions.Template.from_stack(orchestrator_stack)


def _asl_string(template) -> str:
    """Extract the raw ASL text from the synthesized state machine resource."""
    resources = template.find_resources("AWS::StepFunctions::StateMachine")
    assert resources, "No StateMachine resource found in template"
    resource = next(iter(resources.values()))
    definition_string = resource["Properties"]["DefinitionString"]
    # When definition_substitutions is set, CDK emits Fn::Sub — a list
    # whose first element is the template string with ${Placeholder} tokens.
    if isinstance(definition_string, dict):
        return definition_string["Fn::Sub"][0]
    return definition_string


def test_state_machine_type_standard(template):
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {"StateMachineType": "STANDARD"},
    )


def test_state_machine_name(template):
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {"StateMachineName": "data-curator-crawler-orchestrator"},
    )


def test_logging_configuration(template):
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {
            "LoggingConfiguration": assertions.Match.object_like({
                "Level": "ALL",
                "IncludeExecutionData": True,
            })
        },
    )


def test_definition_start_at_validate_input(template):
    assert '"StartAt": "ValidateInput"' in _asl_string(template)


def test_definition_contains_normalize_categories(template):
    asl = _asl_string(template)
    assert "NormalizeCategories" in asl
    assert "SetAllCategories" in asl


def test_definition_contains_fan_out_map(template):
    asl = _asl_string(template)
    assert "FanOutCategories" in asl
    assert "MaxConcurrency" in asl


def test_definition_contains_pagination_loop(template):
    asl = _asl_string(template)
    assert "IncrementBatch" in asl
    assert "MathAdd" in asl
    assert "CheckIfMore" in asl


def test_definition_contains_retry(template):
    asl = _asl_string(template)
    assert "Lambda.ServiceException" in asl
    assert "IntervalSeconds" in asl
    assert "MaxAttempts" in asl


def test_definition_contains_aggregate_results(template):
    assert "AggregateResults" in _asl_string(template)


def test_role_has_lambda_invoke_permission(template):
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "lambda:InvokeFunction",
                        "Effect": "Allow",
                    })
                ])
            })
        },
    )


def test_role_has_ssm_get_parameter(template):
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "ssm:GetParameter",
                        "Effect": "Allow",
                    })
                ])
            })
        },
    )


def test_no_unauthorized_permissions(template):
    forbidden = {
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "secretsmanager:GetSecretValue",
        "bedrock:InvokeModel",
    }
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
            for action in actions:
                assert action not in forbidden, (
                    f"OrchestratorStack must not grant {action}"
                )


def test_source_registry_parameter_name(template):
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {"Name": "/data-curator/crawler-orchestrator/source-registry"},
    )


def test_log_group_retention(template):
    template.has_resource_properties(
        "AWS::Logs::LogGroup",
        {
            "LogGroupName": "/data-curator/crawler-orchestrator",
            "RetentionInDays": 90,
        },
    )


def test_state_machine_arn_output(template):
    template.has_output(
        "StateMachineArn",
        {"Export": {"Name": "CrawlerOrchestratorStateMachineArn"}},
    )


def test_source_registry_parameter_output(template):
    template.has_output(
        "SourceRegistryParameterName",
        {"Export": {"Name": "CrawlerOrchestratorSourceRegistryParameterName"}},
    )

import json

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    Fn,
    RemovalPolicy,
    aws_iam as iam,
    aws_logs as logs,
    aws_ssm as ssm,
    aws_stepfunctions as sfn,
)
from constructs import Construct

# ---------------------------------------------------------------------------
# State machine definition (Amazon States Language)
# ---------------------------------------------------------------------------
# ${KaggleCrawlerArn} is a CDK definition substitution placeholder —
# replaced with the actual ARN at synth time via definition_substitutions.
# ---------------------------------------------------------------------------

_ASL = json.dumps({
    "Comment": (
        "Crawler orchestrator — fans out category crawls, loops over page batches, "
        "and aggregates per-category outcomes."
    ),
    "StartAt": "ValidateInput",
    "States": {

        # ── Input validation ────────────────────────────────────────────────
        "ValidateInput": {
            "Type": "Choice",
            "Choices": [
                {
                    "Not": {"Variable": "$.runId", "IsPresent": True},
                    "Next": "FailMissingRunId",
                },
                {
                    "Not": {"Variable": "$.source", "IsPresent": True},
                    "Next": "FailMissingSource",
                },
                {
                    "Not": {"Variable": "$.limitPerPage", "IsPresent": True},
                    "Next": "FailMissingLimitPerPage",
                },
                {
                    "Not": {"Variable": "$.maxBatches", "IsPresent": True},
                    "Next": "FailMissingMaxBatches",
                },
            ],
            "Default": "NormalizeCategories",
        },
        "FailMissingRunId": {
            "Type": "Fail",
            "Error": "ValidationError",
            "Cause": "Input missing required field: runId",
        },
        "FailMissingSource": {
            "Type": "Fail",
            "Error": "ValidationError",
            "Cause": "Input missing required field: source",
        },
        "FailMissingLimitPerPage": {
            "Type": "Fail",
            "Error": "ValidationError",
            "Cause": "Input missing required field: limitPerPage",
        },
        "FailMissingMaxBatches": {
            "Type": "Fail",
            "Error": "ValidationError",
            "Cause": "Input missing required field: maxBatches",
        },

        # ── Normalize empty categories → [""] (all-Kaggle crawl) ───────────
        "NormalizeCategories": {
            "Type": "Choice",
            "Choices": [
                {
                    # categories absent or empty array → crawl everything
                    "Or": [
                        {"Variable": "$.categories", "IsPresent": False},
                        {
                            "Variable": "$.categories[0]",
                            "IsPresent": False,
                        },
                    ],
                    "Next": "SetAllCategories",
                }
            ],
            "Default": "FanOutCategories",
        },
        "SetAllCategories": {
            "Type": "Pass",
            "Parameters": {
                "runId.$": "$.runId",
                "source.$": "$.source",
                "categories": [""],
                "limitPerPage.$": "$.limitPerPage",
                "pagesPerBatch.$": "$.pagesPerBatch",
                "maxBatches.$": "$.maxBatches",
            },
            "Next": "FanOutCategories",
        },

        # ── Fan out across categories ───────────────────────────────────────
        "FanOutCategories": {
            "Type": "Map",
            "ItemsPath": "$.categories",
            "MaxConcurrency": 5,
            "ItemSelector": {
                "runId.$": "$$.Execution.Input.runId",
                "source.$": "$$.Execution.Input.source",
                "category.$": "$$.Map.Item.Value",
                "limitPerPage.$": "$$.Execution.Input.limitPerPage",
                "pagesPerBatch.$": "$$.Execution.Input.pagesPerBatch",
                "maxBatches.$": "$$.Execution.Input.maxBatches",
                "startPage": 1,
                "batchCount": 0,
            },
            "Iterator": {
                "StartAt": "FetchBatch",
                "States": {

                    # ── Invoke the crawler Lambda for one batch of pages ────
                    "FetchBatch": {
                        "Type": "Task",
                        "Resource": "arn:aws:states:::lambda:invoke",
                        "Parameters": {
                            "FunctionName": "${KaggleCrawlerArn}",
                            "Payload.$": "$",
                        },
                        "ResultSelector": {
                            "recordsWritten.$": "$.Payload.recordsWritten",
                            "recordsSkipped.$": "$.Payload.recordsSkipped",
                            "enrichmentFailures.$": "$.Payload.enrichmentFailures",
                            "errors.$": "$.Payload.errors",
                            "lastPageFetched.$": "$.Payload.lastPageFetched",
                            "hitEndOfResults.$": "$.Payload.hitEndOfResults",
                        },
                        "ResultPath": "$.batchResult",
                        "Retry": [
                            {
                                # Retry is safe: DynamoDB condition attribute_not_exists(PK)
                                # OR :newLastUpdatedAt > #lastUpdatedAt ensures re-processing
                                # already-written records is a no-op.
                                "ErrorEquals": [
                                    "Lambda.ServiceException",
                                    "Lambda.AWSLambdaException",
                                    "States.TaskFailed",
                                ],
                                "IntervalSeconds": 10,
                                "BackoffRate": 2,
                                "MaxAttempts": 3,
                            }
                        ],
                        "Catch": [
                            {
                                "ErrorEquals": ["States.ALL"],
                                "ResultPath": "$.errorInfo",
                                "Next": "CategoryFailed",
                            }
                        ],
                        "Next": "CheckIfMore",
                    },

                    # ── Decide whether to fetch another batch ───────────────
                    "CheckIfMore": {
                        "Type": "Choice",
                        "Choices": [
                            {
                                "Variable": "$.batchResult.hitEndOfResults",
                                "BooleanEquals": True,
                                "Next": "CategoryDone",
                            },
                            {
                                # batchCount is 0-indexed; stop when we've run maxBatches batches
                                "Variable": "$.batchCount",
                                "NumericGreaterThanEqualsPath": "$.maxBatches",
                                "Next": "CategoryDone",
                            },
                        ],
                        "Default": "IncrementBatch",
                    },

                    # ── Advance to next batch ───────────────────────────────
                    "IncrementBatch": {
                        "Type": "Pass",
                        "Parameters": {
                            "runId.$": "$.runId",
                            "source.$": "$.source",
                            "category.$": "$.category",
                            "limitPerPage.$": "$.limitPerPage",
                            "pagesPerBatch.$": "$.pagesPerBatch",
                            "maxBatches.$": "$.maxBatches",
                            "startPage.$": "States.MathAdd($.batchResult.lastPageFetched, 1)",
                            "batchCount.$": "States.MathAdd($.batchCount, 1)",
                        },
                        "Next": "FetchBatch",
                    },

                    # ── Terminal states ─────────────────────────────────────
                    "CategoryDone": {
                        "Type": "Pass",
                        "Parameters": {
                            "category.$": "$.category",
                            "status": "succeeded",
                            "batchResult.$": "$.batchResult",
                        },
                        "End": True,
                    },
                    "CategoryFailed": {
                        "Type": "Pass",
                        "Parameters": {
                            "category.$": "$.category",
                            "status": "failed",
                            "errorInfo.$": "$.errorInfo",
                        },
                        "End": True,
                    },
                },
            },
            "ResultPath": "$.categoryResults",
            "Next": "AggregateResults",
        },

        # ── Aggregate and emit run summary ──────────────────────────────────
        # Step Functions execution logging (LogLevel.ALL, include_execution_data=True)
        # captures this final state output as the CloudWatch run summary.
        "AggregateResults": {
            "Type": "Pass",
            "Parameters": {
                "runId.$": "$.runId",
                "source.$": "$.source",
                "results.$": "$.categoryResults",
            },
            "End": True,
        },
    },
})


class OrchestratorStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        kaggle_fn_arn = Fn.import_value("KaggleCrawlerFunctionArn")

        # ── SSM source registry ─────────────────────────────────────────────
        # Authoritative record of the source→Lambda ARN mapping.
        # The state machine uses CDK definition substitutions (not a runtime
        # SSM read) to avoid JSONPath dynamic key-lookup limitations.
        source_registry_param = ssm.StringParameter(
            self,
            "SourceRegistry",
            parameter_name="/data-curator/crawler-orchestrator/source-registry",
            string_value=json.dumps({"kaggle": kaggle_fn_arn}),
            description=(
                "Source→Lambda ARN registry for the crawler orchestrator. "
                "ARNs are also baked into the state machine via CDK definition substitutions."
            ),
        )

        # ── CloudWatch log group ────────────────────────────────────────────
        log_group = logs.LogGroup(
            self,
            "OrchestratorLogs",
            log_group_name="/data-curator/crawler-orchestrator",
            retention=logs.RetentionDays.THREE_MONTHS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── IAM role for Step Functions ─────────────────────────────────────
        sm_role = iam.Role(
            self,
            "OrchestratorRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
            description="Execution role for the crawler orchestrator state machine",
        )

        sm_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=[kaggle_fn_arn],
            )
        )

        sm_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["ssm:GetParameter"],
                resources=[source_registry_param.parameter_arn],
            )
        )

        # Step Functions CWL delivery API requires account-wide resource scope —
        # this is the documented AWS pattern for execution logging.
        sm_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogDelivery",
                    "logs:GetLogDelivery",
                    "logs:UpdateLogDelivery",
                    "logs:DeleteLogDelivery",
                    "logs:ListLogDeliveries",
                    "logs:PutResourcePolicy",
                    "logs:DescribeResourcePolicies",
                    "logs:DescribeLogGroups",
                ],
                resources=["*"],
            )
        )

        log_group.grant_write(sm_role)

        # ── State machine ───────────────────────────────────────────────────
        self.state_machine = sfn.StateMachine(
            self,
            "CrawlerOrchestrator",
            state_machine_name="data-curator-crawler-orchestrator",
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_string(_ASL),
            definition_substitutions={"KaggleCrawlerArn": kaggle_fn_arn},
            role=sm_role,
            logs=sfn.LogOptions(
                destination=log_group,
                level=sfn.LogLevel.ALL,
                include_execution_data=True,
            ),
            tracing_enabled=False,
            removal_policy=RemovalPolicy.DESTROY,
            timeout=Duration.hours(2),
        )

        # ── CloudFormation outputs ──────────────────────────────────────────
        CfnOutput(
            self,
            "StateMachineArn",
            value=self.state_machine.state_machine_arn,
            export_name="CrawlerOrchestratorStateMachineArn",
            description="Use this ARN to start executions via the StartExecution API",
        )
        CfnOutput(
            self,
            "StateMachineName",
            value=self.state_machine.state_machine_name,
            export_name="CrawlerOrchestratorStateMachineName",
        )
        CfnOutput(
            self,
            "SourceRegistryParameterName",
            value=source_registry_param.parameter_name,
            export_name="CrawlerOrchestratorSourceRegistryParameterName",
            description=(
                "SSM parameter containing the source→Lambda ARN registry "
                "(authoritative record; update when adding new crawler sources)"
            ),
        )
        CfnOutput(
            self,
            "OrchestratorLogGroupName",
            value=log_group.log_group_name,
            export_name="CrawlerOrchestratorLogGroupName",
        )

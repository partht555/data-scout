#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.metadata_store_stack import MetadataStoreStack

app = cdk.App()

MetadataStoreStack(
    app,
    "DataCuratorMetadataStore",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region"),
    ),
)

app.synth()

#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.metadata_store_stack import MetadataStoreStack
from stacks.crawler_stack import CrawlerStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region"),
)

metadata_stack = MetadataStoreStack(app, "DataCuratorMetadataStore", env=env)

crawler_stack = CrawlerStack(app, "DataCuratorCrawler", env=env)
crawler_stack.add_dependency(metadata_stack)

app.synth()

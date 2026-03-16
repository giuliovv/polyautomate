#!/usr/bin/env python3
"""CDK app entry point for Bot Platform."""

import aws_cdk as cdk

from botplatform_stack import BotplatformStack

app = cdk.App()

BotplatformStack(
    app,
    "BotplatformStack",
    env=cdk.Environment(
        region="eu-west-1",
    ),
)

app.synth()

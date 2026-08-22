#!/usr/bin/env python3
import os

import aws_cdk as cdk

from polyautomate_stack import PolyautomateStack

app = cdk.App()
PolyautomateStack(
    app,
    "PolyautomateStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "eu-west-1"),
    ),
    synthesizer=cdk.DefaultStackSynthesizer(qualifier="polyauto1"),
)
app.synth()

#!/usr/bin/env python3
import aws_cdk as cdk

from polyautomate_stack import PolyautomateStack
from polyautomate_lambda_stack import PolyautomateLambdaStack

app = cdk.App()
PolyautomateStack(
    app,
    "PolyautomateStack",
    synthesizer=cdk.DefaultStackSynthesizer(qualifier="polyauto1"),
)
if app.node.try_get_context("executorSecretArn") and app.node.try_get_context("portfolioBucketName"):
    PolyautomateLambdaStack(
        app,
        "PolyautomateLambdaStack",
        synthesizer=cdk.DefaultStackSynthesizer(qualifier="polyauto1"),
        env=cdk.Environment(region="eu-west-1"),
    )
app.synth()

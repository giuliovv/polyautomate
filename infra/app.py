#!/usr/bin/env python3
import aws_cdk as cdk

from polyautomate_stack import PolyautomateStack

app = cdk.App()
PolyautomateStack(
    app,
    "PolyautomateStack",
    synthesizer=cdk.DefaultStackSynthesizer(qualifier="polyauto1"),
)
app.synth()

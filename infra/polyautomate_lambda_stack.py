from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    aws_events as events,
    aws_events_targets as targets,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
)


class PolyautomateLambdaStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        executor_secret_arn = self.node.try_get_context("executorSecretArn")
        portfolio_bucket_name = self.node.try_get_context("portfolioBucketName")
        if not executor_secret_arn:
            raise ValueError("executorSecretArn context is required")
        if not portfolio_bucket_name:
            raise ValueError("portfolioBucketName context is required")

        longshot_data_provider = self.node.try_get_context("longshotDataProvider") or "gamma_clob"
        longshot_data_timeout = str(self.node.try_get_context("longshotDataTimeout") or "10")
        lambda_executor_schedule = self.node.try_get_context("lambdaExecutorSchedule") or "rate(5 minutes)"
        lambda_portfolio_schedule = self.node.try_get_context("lambdaPortfolioSchedule") or "rate(5 minutes)"
        lambda_executor_dry_run = str(self.node.try_get_context("lambdaExecutorDryRun") or "1")

        executor_secret = secretsmanager.Secret.from_secret_complete_arn(
            self,
            "ImportedExecutorCredentialsSecret",
            executor_secret_arn,
        )
        portfolio_bucket = s3.Bucket.from_bucket_name(
            self,
            "ImportedPortfolioDashboardBucket",
            portfolio_bucket_name,
        )

        executor_state_bucket = s3.Bucket(
            self,
            "ExecutorStateBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(30))],
            removal_policy=cdk.RemovalPolicy.RETAIN,
            auto_delete_objects=False,
        )

        lambda_common_env = {
            "EXECUTOR_SECRET_ARN": executor_secret_arn,
            "LONGSHOT_STATE_BUCKET": executor_state_bucket.bucket_name,
            "LONGSHOT_STATE_KEY": "executor/longshot-state.json",
            "LONGSHOT_DATA_PROVIDER": longshot_data_provider,
            "LONGSHOT_DATA_TIMEOUT": longshot_data_timeout,
            "LONGSHOT_THRESHOLD": "0.40",
            "LONGSHOT_MIN_DAYS_LEFT": "2",
            "LONGSHOT_MAX_SPREAD": "0.03",
            "LONGSHOT_MAX_REL_SPREAD": "0.15",
            "LONGSHOT_HOLD_GRACE_HOURS": "24",
            "LONGSHOT_ORDER_SIZE": "5",
            "LONGSHOT_MAX_ACTIONS_PER_CYCLE": "1",
            "LONGSHOT_USE_KELLY": "1",
            "LONGSHOT_BANKROLL_USD": "500",
            "LONGSHOT_KELLY_FRACTION": "0.25",
            "LONGSHOT_MAX_BANKROLL_FRACTION": "0.03",
            "LONGSHOT_MIN_NOTIONAL_USD": "2",
            "LONGSHOT_MAX_NOTIONAL_USD": "25",
            "LONGSHOT_GUARDRAIL_ENABLED": "1",
            "LONGSHOT_GUARDRAIL_WINDOW_TRADES": "12",
            "LONGSHOT_GUARDRAIL_MIN_TRADES": "4",
            "LONGSHOT_GUARDRAIL_MIN_PNL_USD": "-5",
            "LONGSHOT_GUARDRAIL_MIN_WIN_RATE": "0.35",
            "LONGSHOT_GUARDRAIL_COOLDOWN_MIN": "180",
        }

        lambda_image_code = _lambda.DockerImageCode.from_image_asset(
            directory="..",
            file="docker/lambda/Dockerfile",
        )
        executor_lambda = _lambda.DockerImageFunction(
            self,
            "ExecutorLambda",
            code=lambda_image_code,
            timeout=Duration.minutes(15),
            memory_size=512,
            architecture=_lambda.Architecture.ARM_64,
            environment={
                **lambda_common_env,
                "DRY_RUN": lambda_executor_dry_run,
            },
            description="Scheduled longshot executor shadow path. Defaults to dry-run until EC2 cutover.",
        )
        executor_secret.grant_read(executor_lambda)
        executor_state_bucket.grant_read_write(executor_lambda)

        portfolio_lambda = _lambda.DockerImageFunction(
            self,
            "PortfolioPublisherLambda",
            code=_lambda.DockerImageCode.from_image_asset(
                directory="..",
                file="docker/lambda/Dockerfile",
                cmd=["polyautomate.runtime.lambda_handlers.portfolio_handler"],
            ),
            timeout=Duration.minutes(5),
            memory_size=512,
            architecture=_lambda.Architecture.ARM_64,
            environment={
                **lambda_common_env,
                "DRY_RUN": "1",
                "PORTFOLIO_BUCKET": portfolio_bucket.bucket_name,
                "PORTFOLIO_KEY": "index.html",
                "PORTFOLIO_INCLUDE_CLOB_BALANCE": "1",
            },
            description="Scheduled static portfolio dashboard publisher for Lambda cutover.",
        )
        executor_secret.grant_read(portfolio_lambda)
        executor_state_bucket.grant_read_write(portfolio_lambda)
        portfolio_bucket.grant_put(portfolio_lambda)

        events.Rule(
            self,
            "LambdaExecutorSchedule",
            schedule=events.Schedule.expression(lambda_executor_schedule),
            targets=[targets.LambdaFunction(executor_lambda)],
            description="Shadow scheduled Lambda executor. Keep DRY_RUN=1 until EC2 cutover.",
        )
        events.Rule(
            self,
            "LambdaPortfolioPublisherSchedule",
            schedule=events.Schedule.expression(lambda_portfolio_schedule),
            targets=[targets.LambdaFunction(portfolio_lambda)],
            description="Scheduled Lambda portfolio dashboard publisher.",
        )

        CfnOutput(self, "ExecutorStateBucketName", value=executor_state_bucket.bucket_name)
        CfnOutput(self, "ExecutorLambdaName", value=executor_lambda.function_name)
        CfnOutput(self, "PortfolioPublisherLambdaName", value=portfolio_lambda.function_name)

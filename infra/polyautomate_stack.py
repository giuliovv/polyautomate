from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
)


class PolyautomateStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        action_threshold = self.node.try_get_context("actionThreshold") or 200
        daily_schedule = self.node.try_get_context("dailySchedule") or "cron(0 3 * * ? *)"
        executor_repo_url = (
            self.node.try_get_context("executorRepoUrl")
            or "https://github.com/giuliovv/polyautomate.git"
        )
        executor_repo_branch = self.node.try_get_context("executorRepoBranch") or "main"
        executor_instance_type = (
            self.node.try_get_context("executorInstanceType") or "t3.micro"
        )

        vpc = ec2.Vpc(
            self,
            "PolyautomateVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        executor_repo = ecr.Repository(
            self,
            "ExecutorRepo",
            image_scan_on_push=True,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=20)],
        )

        researcher_repo = ecr.Repository(
            self,
            "ResearcherRepo",
            image_scan_on_push=True,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=20)],
        )

        executor_log_group = logs.LogGroup(
            self,
            "ExecutorLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        researcher_log_group = logs.LogGroup(
            self,
            "ResearcherLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        researcher_state_bucket = s3.Bucket(
            self,
            "ResearcherStateBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(30))],
            removal_policy=cdk.RemovalPolicy.RETAIN,
            auto_delete_objects=False,
        )

        executor_credentials_secret = secretsmanager.Secret(
            self,
            "ExecutorCredentialsSecret",
            description="Executor runtime credentials for Polymarket trading",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"POLYMARKET_API_KEY":"REPLACE_ME","POLYMARKET_PASSPHRASE":"REPLACE_ME","POLYMARKET_SIGNING_KEY":"REPLACE_ME","POLYMARKETDATA_API_KEY":"REPLACE_ME","EXECUTOR_GITHUB_TOKEN":"REPLACE_ME"}',
                generate_string_key="bootstrap",
            ),
        )

        researcher_credentials_secret = secretsmanager.Secret(
            self,
            "ResearcherCredentialsSecret",
            description="Researcher runtime credentials for Claude and PolymarketData",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"ANTHROPIC_API_KEY":"REPLACE_ME","POLYMARKETDATA_API_KEY":"REPLACE_ME","TELEGRAM_BOT_TOKEN":"REPLACE_ME","TELEGRAM_CHAT_ID":"REPLACE_ME","GITHUB_TOKEN":"REPLACE_ME"}',
                generate_string_key="bootstrap",
            ),
        )

        executor_error_topic = sns.Topic(
            self,
            "ExecutorErrorTopic",
            display_name="polyautomate-executor-errors",
        )

        action_metric_filter = logs.MetricFilter(
            self,
            "ExecutorActionMetricFilter",
            log_group=executor_log_group,
            metric_name="ExecutorActions",
            metric_namespace="Polyautomate",
            filter_pattern=logs.FilterPattern.literal("ACTION_EXECUTED"),
            metric_value="1",
            default_value=0,
        )

        action_alarm = cloudwatch.Alarm(
            self,
            "ExecutorActionAlarm",
            metric=action_metric_filter.metric(statistic="Sum", period=Duration.hours(1)),
            threshold=float(action_threshold),
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_description="Triggers researcher task after executor performs many actions",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        error_metric_filter = logs.MetricFilter(
            self,
            "ExecutorErrorMetricFilter",
            log_group=executor_log_group,
            metric_name="ExecutorErrors",
            metric_namespace="Polyautomate",
            filter_pattern=logs.FilterPattern.literal("executor_cycle_failed"),
            metric_value="1",
            default_value=0,
        )

        error_alarm = cloudwatch.Alarm(
            self,
            "ExecutorErrorAlarm",
            metric=error_metric_filter.metric(statistic="Sum", period=Duration.minutes(5)),
            threshold=1.0,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_description="Triggers when executor logs an execution failure",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        error_alarm.add_alarm_action(cloudwatch_actions.SnsAction(executor_error_topic))

        executor_sg = ec2.SecurityGroup(
            self,
            "ExecutorSecurityGroup",
            vpc=vpc,
            allow_all_outbound=True,
            description="Executor bot host security group",
        )

        executor_role = iam.Role(
            self,
            "ExecutorInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
        )
        executor_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy")
        )
        executor_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
        )
        executor_log_group.grant_write(executor_role)
        executor_credentials_secret.grant_read(executor_role)

        executor_instance = ec2.Instance(
            self,
            "ExecutorHostInstanceV2",
            vpc=vpc,
            instance_type=ec2.InstanceType(executor_instance_type),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(
                cpu_type=ec2.AmazonLinuxCpuType.X86_64
            ),
            role=executor_role,
            security_group=executor_sg,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            require_imdsv2=True,
        )

        user_data = executor_instance.user_data
        user_data.add_commands(
            "dnf update -y",
            "dnf install -y docker awscli cronie",
            "systemctl enable docker",
            "systemctl start docker",
            "systemctl enable crond",
            "systemctl start crond",
            f"REGION={cdk.Aws.REGION}",
            """cat > /usr/local/bin/reconcile-executor.sh <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
REGION="${REGION:-eu-west-1}"
SECRET_ARN="${SECRET_ARN:-}"
REPO_URL="${REPO_URL:-}"
REPO_BRANCH="${REPO_BRANCH:-main}"
REPO_DIR="${REPO_DIR:-/opt/polyautomate-src}"
STATE_DIR="/var/lib/polyautomate"
LOG_GROUP="${LOG_GROUP:-/polyautomate/executor}"
POLL_SECONDS="${POLL_SECONDS:-30}"
STRATEGY_RUNNER="${STRATEGY_RUNNER:-polyautomate.runtime.example_strategy:run_once}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"

if [[ -z "$SECRET_ARN" || -z "$REPO_URL" ]]; then
  echo "missing_required_env"
  exit 1
fi

SECRET_JSON="$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$SECRET_ARN" --query SecretString --output text)"
POLYMARKET_API_KEY="$(printf '%s' "$SECRET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("POLYMARKET_API_KEY", ""))')"
POLYMARKET_PASSPHRASE="$(printf '%s' "$SECRET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("POLYMARKET_PASSPHRASE", ""))')"
POLYMARKET_SIGNING_KEY="$(printf '%s' "$SECRET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("POLYMARKET_SIGNING_KEY", ""))')"
POLYMARKETDATA_API_KEY="$(printf '%s' "$SECRET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("POLYMARKETDATA_API_KEY", ""))')"
GITHUB_TOKEN="$(printf '%s' "$SECRET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("EXECUTOR_GITHUB_TOKEN", ""))')"
if [[ "$GITHUB_TOKEN" == "REPLACE_ME" || "$GITHUB_TOKEN" == "null" ]]; then
  GITHUB_TOKEN=""
fi

mkdir -p "$STATE_DIR"

AUTH_REPO_URL="$REPO_URL"
if [[ -n "$GITHUB_TOKEN" && "$REPO_URL" == https://github.com/* ]]; then
  AUTH_REPO_URL="${REPO_URL/https:\/\/github.com\//https:\/\/x-access-token:${GITHUB_TOKEN}@github.com\/}"
fi

if [[ ! -d "$REPO_DIR/.git" ]]; then
  rm -rf "$REPO_DIR"
  git clone --depth 1 --branch "$REPO_BRANCH" "$AUTH_REPO_URL" "$REPO_DIR"
else
  git -C "$REPO_DIR" remote set-url origin "$AUTH_REPO_URL"
  git -C "$REPO_DIR" fetch origin "$REPO_BRANCH"
  git -C "$REPO_DIR" checkout "$REPO_BRANCH"
  git -C "$REPO_DIR" reset --hard "origin/$REPO_BRANCH"
  git -C "$REPO_DIR" clean -fd
fi

NEW_SHA="$(git -C "$REPO_DIR" rev-parse HEAD)"
SECRET_SIG="$(printf '%s' "$POLYMARKET_API_KEY:$POLYMARKET_PASSPHRASE:$POLYMARKET_SIGNING_KEY:$POLL_SECONDS:$STRATEGY_RUNNER" | sha256sum | awk '{print $1}')"
DESIRED_SIG="$NEW_SHA:$SECRET_SIG"
CURRENT_SIG="$(cat "$STATE_DIR/deploy.sig" 2>/dev/null || true)"

if [[ "$DESIRED_SIG" != "$CURRENT_SIG" ]]; then
  docker build -f "$REPO_DIR/docker/executor/Dockerfile" -t "polyautomate-executor:$NEW_SHA" "$REPO_DIR" >/dev/null
  docker rm -f polyautomate-executor >/dev/null 2>&1 || true
  docker run -d --name polyautomate-executor --restart unless-stopped \
    -e EXECUTOR_MODE=live \
    -e POLL_SECONDS="$POLL_SECONDS" \
    -e STRATEGY_RUNNER="$STRATEGY_RUNNER" \
    -e DRY_RUN="$DRY_RUN" \
    -e POLYMARKET_API_KEY="$POLYMARKET_API_KEY" \
    -e POLYMARKET_PASSPHRASE="$POLYMARKET_PASSPHRASE" \
    -e POLYMARKET_SIGNING_KEY="$POLYMARKET_SIGNING_KEY" \
    -e POLYMARKETDATA_API_KEY="$POLYMARKETDATA_API_KEY" \
    -e LONGSHOT_THRESHOLD="$LONGSHOT_THRESHOLD" \
    -e LONGSHOT_MIN_DAYS_LEFT="$LONGSHOT_MIN_DAYS_LEFT" \
    -e LONGSHOT_ORDER_SIZE="$LONGSHOT_ORDER_SIZE" \
    -e LONGSHOT_MAX_ACTIONS_PER_CYCLE="$LONGSHOT_MAX_ACTIONS_PER_CYCLE" \
    --log-driver=awslogs \
    --log-opt awslogs-region="$REGION" \
    --log-opt awslogs-group="$LOG_GROUP" \
    --log-opt awslogs-stream=executor-ec2 \
    "polyautomate-executor:$NEW_SHA" >/dev/null
  echo "$DESIRED_SIG" > "$STATE_DIR/deploy.sig"
fi
SCRIPT""",
            "chmod +x /usr/local/bin/reconcile-executor.sh",
            f"echo 'REGION={cdk.Aws.REGION}' > /etc/polyautomate-executor.env",
            f"echo 'SECRET_ARN={executor_credentials_secret.secret_arn}' >> /etc/polyautomate-executor.env",
            f"echo 'REPO_URL={executor_repo_url}' >> /etc/polyautomate-executor.env",
            f"echo 'REPO_BRANCH={executor_repo_branch}' >> /etc/polyautomate-executor.env",
            f"echo 'LOG_GROUP={executor_log_group.log_group_name}' >> /etc/polyautomate-executor.env",
            "echo 'POLL_SECONDS=30' >> /etc/polyautomate-executor.env",
            "echo 'DRY_RUN=0' >> /etc/polyautomate-executor.env",
            "echo 'STRATEGY_RUNNER=polyautomate.runtime.longshot_executor:run_once' >> /etc/polyautomate-executor.env",
            "echo 'LONGSHOT_THRESHOLD=0.40' >> /etc/polyautomate-executor.env",
            "echo 'LONGSHOT_MIN_DAYS_LEFT=2' >> /etc/polyautomate-executor.env",
            "echo 'LONGSHOT_ORDER_SIZE=5' >> /etc/polyautomate-executor.env",
            "echo 'LONGSHOT_MAX_ACTIONS_PER_CYCLE=1' >> /etc/polyautomate-executor.env",
            "bash -lc 'set -a; source /etc/polyautomate-executor.env; set +a; /usr/local/bin/reconcile-executor.sh'",
            "echo '*/10 * * * * root bash -lc \"set -a; source /etc/polyautomate-executor.env; set +a; /usr/local/bin/reconcile-executor.sh\"' > /etc/cron.d/polyautomate-reconcile",
            "chmod 644 /etc/cron.d/polyautomate-reconcile",
            "systemctl restart crond",
        )

        cluster = ecs.Cluster(self, "ResearcherCluster", vpc=vpc)

        researcher_task_role = iam.Role(
            self,
            "ResearcherTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        executor_log_group.grant_read(researcher_task_role)
        researcher_credentials_secret.grant_read(researcher_task_role)
        researcher_state_bucket.grant_read_write(researcher_task_role)

        researcher_task_definition = ecs.FargateTaskDefinition(
            self,
            "ResearcherTaskDefinition",
            cpu=1024,
            memory_limit_mib=2048,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
            task_role=researcher_task_role,
        )

        researcher_container = researcher_task_definition.add_container(
            "ResearcherContainer",
            image=ecs.ContainerImage.from_ecr_repository(researcher_repo, "latest"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="researcher",
                log_group=researcher_log_group,
            ),
            environment={
                "EXECUTOR_LOG_GROUP": executor_log_group.log_group_name,
                "AWS_REGION": cdk.Aws.REGION,
                "ENABLE_CLAUDE": "1",
                "ENABLE_PR_AUTOMATION": "1",
                "STATE_BUCKET": researcher_state_bucket.bucket_name,
                "STATE_KEY": "researcher/state.json",
                "GITHUB_REPO": "giuliovv/polyautomate",
                "GITHUB_BASE_BRANCH": "main",
            },
            secrets={
                "ANTHROPIC_API_KEY": ecs.Secret.from_secrets_manager(
                    researcher_credentials_secret, "ANTHROPIC_API_KEY"
                ),
                "POLYMARKETDATA_API_KEY": ecs.Secret.from_secrets_manager(
                    researcher_credentials_secret, "POLYMARKETDATA_API_KEY"
                ),
                "TELEGRAM_BOT_TOKEN": ecs.Secret.from_secrets_manager(
                    researcher_credentials_secret, "TELEGRAM_BOT_TOKEN"
                ),
                "TELEGRAM_CHAT_ID": ecs.Secret.from_secrets_manager(
                    researcher_credentials_secret, "TELEGRAM_CHAT_ID"
                ),
                "GITHUB_TOKEN": ecs.Secret.from_secrets_manager(
                    researcher_credentials_secret, "GITHUB_TOKEN"
                ),
            },
        )

        researcher_security_group = ec2.SecurityGroup(
            self,
            "ResearcherSecurityGroup",
            vpc=vpc,
            allow_all_outbound=True,
            description="Researcher task security group",
        )

        run_task_target = targets.EcsTask(
            cluster=cluster,
            task_definition=researcher_task_definition,
            subnet_selection=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            assign_public_ip=True,
            security_groups=[researcher_security_group],
            task_count=1,
            platform_version=ecs.FargatePlatformVersion.LATEST,
        )

        events.Rule(
            self,
            "DailyResearcherRun",
            schedule=events.Schedule.expression(daily_schedule),
            targets=[run_task_target],
            description="Daily strategy validation and tuning run",
        )

        events.Rule(
            self,
            "AlarmResearcherRun",
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                resources=[action_alarm.alarm_arn],
                detail={"state": {"value": ["ALARM"]}},
            ),
            targets=[run_task_target],
            description="Run researcher task when executor action threshold is crossed",
        )

        error_trigger_function = _lambda.Function(
            self,
            "ErrorTriggerFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.seconds(60),
            code=_lambda.Code.from_inline(
                "import boto3, os\n"
                "def handler(event, context):\n"
                "  ecs = boto3.client('ecs')\n"
                "  ecs.run_task(\n"
                "    cluster=os.environ['CLUSTER_ARN'],\n"
                "    taskDefinition=os.environ['TASK_DEFINITION_ARN'],\n"
                "    launchType='FARGATE',\n"
                "    count=1,\n"
                "    networkConfiguration={\n"
                "      'awsvpcConfiguration': {\n"
                "        'subnets': os.environ['SUBNETS'].split(','),\n"
                "        'securityGroups': os.environ['SECURITY_GROUPS'].split(','),\n"
                "        'assignPublicIp': 'ENABLED'\n"
                "      }\n"
                "    }\n"
                "  )\n"
                "  return {'ok': True}\n"
            ),
            environment={
                "CLUSTER_ARN": cluster.cluster_arn,
                "TASK_DEFINITION_ARN": researcher_task_definition.task_definition_arn,
                "SUBNETS": ",".join([s.subnet_id for s in vpc.public_subnets]),
                "SECURITY_GROUPS": researcher_security_group.security_group_id,
            },
        )
        error_trigger_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[researcher_task_definition.task_definition_arn],
            )
        )
        error_trigger_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[
                    researcher_task_definition.execution_role.role_arn,
                    researcher_task_definition.task_role.role_arn,
                ],
            )
        )
        executor_error_topic.add_subscription(
            sns_subscriptions.LambdaSubscription(error_trigger_function)
        )

        CfnOutput(self, "ExecutorEcrUri", value=executor_repo.repository_uri)
        CfnOutput(self, "ResearcherEcrUri", value=researcher_repo.repository_uri)
        CfnOutput(self, "ExecutorLogGroupName", value=executor_log_group.log_group_name)
        CfnOutput(self, "ResearcherLogGroupName", value=researcher_log_group.log_group_name)
        CfnOutput(self, "ActionAlarmName", value=action_alarm.alarm_name)
        CfnOutput(self, "ErrorAlarmName", value=error_alarm.alarm_name)
        CfnOutput(self, "ExecutorErrorTopicArn", value=executor_error_topic.topic_arn)
        CfnOutput(self, "ResearcherStateBucketName", value=researcher_state_bucket.bucket_name)
        CfnOutput(self, "ExecutorCredentialsSecretArn", value=executor_credentials_secret.secret_arn)
        CfnOutput(self, "ResearcherCredentialsSecretArn", value=researcher_credentials_secret.secret_arn)

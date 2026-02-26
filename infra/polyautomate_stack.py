from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
)


class PolyautomateStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        action_threshold = self.node.try_get_context("actionThreshold") or 200
        daily_schedule = self.node.try_get_context("dailySchedule") or "cron(0 3 * * ? *)"
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

        executor_credentials_secret = secretsmanager.Secret(
            self,
            "ExecutorCredentialsSecret",
            description="Executor runtime credentials for Polymarket trading",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"POLYMARKET_API_KEY":"REPLACE_ME","POLYMARKET_PASSPHRASE":"REPLACE_ME","POLYMARKET_SIGNING_KEY":"REPLACE_ME"}',
                generate_string_key="bootstrap",
            ),
        )

        researcher_credentials_secret = secretsmanager.Secret(
            self,
            "ResearcherCredentialsSecret",
            description="Researcher runtime credentials for Claude and PolymarketData",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"ANTHROPIC_API_KEY":"REPLACE_ME","POLYMARKETDATA_API_KEY":"REPLACE_ME"}',
                generate_string_key="bootstrap",
            ),
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
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonEC2ContainerRegistryReadOnly"
            )
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
            "dnf install -y docker awscli",
            "systemctl enable docker",
            "systemctl start docker",
            f"REGION={cdk.Aws.REGION}",
            f"ACCOUNT_ID={cdk.Aws.ACCOUNT_ID}",
            f"IMAGE_URI={executor_repo.repository_uri}:latest",
            "aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com",
            "docker pull $IMAGE_URI",
            "docker rm -f polyautomate-executor || true",
            f"SECRET_JSON=$(aws secretsmanager get-secret-value --region $REGION --secret-id {executor_credentials_secret.secret_arn} --query SecretString --output text)",
            "POLYMARKET_API_KEY=$(printf '%s' \"$SECRET_JSON\" | python3 -c 'import json,sys; print(json.load(sys.stdin).get(\"POLYMARKET_API_KEY\", \"\"))')",
            "POLYMARKET_PASSPHRASE=$(printf '%s' \"$SECRET_JSON\" | python3 -c 'import json,sys; print(json.load(sys.stdin).get(\"POLYMARKET_PASSPHRASE\", \"\"))')",
            "POLYMARKET_SIGNING_KEY=$(printf '%s' \"$SECRET_JSON\" | python3 -c 'import json,sys; print(json.load(sys.stdin).get(\"POLYMARKET_SIGNING_KEY\", \"\"))')",
            (
                "docker run -d --name polyautomate-executor --restart unless-stopped "
                "-e EXECUTOR_MODE=live "
                "-e POLYMARKET_API_KEY=\"$POLYMARKET_API_KEY\" "
                "-e POLYMARKET_PASSPHRASE=\"$POLYMARKET_PASSPHRASE\" "
                "-e POLYMARKET_SIGNING_KEY=\"$POLYMARKET_SIGNING_KEY\" "
                "--log-driver=awslogs "
                "--log-opt awslogs-region=$REGION "
                f"--log-opt awslogs-group={executor_log_group.log_group_name} "
                "--log-opt awslogs-stream=executor-ec2 "
                "$IMAGE_URI"
            ),
        )

        cluster = ecs.Cluster(self, "ResearcherCluster", vpc=vpc)

        researcher_task_role = iam.Role(
            self,
            "ResearcherTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        executor_log_group.grant_read(researcher_task_role)
        researcher_credentials_secret.grant_read(researcher_task_role)

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
            },
            secrets={
                "ANTHROPIC_API_KEY": ecs.Secret.from_secrets_manager(
                    researcher_credentials_secret, "ANTHROPIC_API_KEY"
                ),
                "POLYMARKETDATA_API_KEY": ecs.Secret.from_secrets_manager(
                    researcher_credentials_secret, "POLYMARKETDATA_API_KEY"
                ),
            },
        )

        run_task_target = targets.EcsTask(
            cluster=cluster,
            task_definition=researcher_task_definition,
            subnet_selection=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            assign_public_ip=True,
            security_groups=[
                ec2.SecurityGroup(
                    self,
                    "ResearcherSecurityGroup",
                    vpc=vpc,
                    allow_all_outbound=True,
                    description="Researcher task security group",
                )
            ],
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

        CfnOutput(self, "ExecutorEcrUri", value=executor_repo.repository_uri)
        CfnOutput(self, "ResearcherEcrUri", value=researcher_repo.repository_uri)
        CfnOutput(self, "ExecutorLogGroupName", value=executor_log_group.log_group_name)
        CfnOutput(self, "ResearcherLogGroupName", value=researcher_log_group.log_group_name)
        CfnOutput(self, "ActionAlarmName", value=action_alarm.alarm_name)
        CfnOutput(self, "ExecutorCredentialsSecretArn", value=executor_credentials_secret.secret_arn)
        CfnOutput(self, "ResearcherCredentialsSecretArn", value=researcher_credentials_secret.secret_arn)

# Polyautomate AWS Deployment

This CDK app provisions a two-runtime architecture:

1. `executor`: always-on bot on a low-cost `t4g.nano` EC2 host.
2. `researcher`: container task on ECS Fargate, triggered daily and when executor activity spikes.

## Why this split

- EC2 `t4g.nano` is the cheapest practical place for an always-on process.
- The researcher is bursty and heavier (logs + backtests + Claude Code), so on-demand Fargate is cheaper and safer than running 24/7.
- The executor still runs in a Docker container on EC2 for reproducibility and easier updates.

## What gets created

- VPC with public subnets (no NAT gateway, lower cost)
- ECR repos:
  - `polyautomate-executor`
  - `polyautomate-researcher`
- CloudWatch log groups:
  - `/polyautomate/executor`
  - `/polyautomate/researcher`
- Private S3 bucket + CloudFront distribution for the read-only portfolio dashboard
- `t4g.nano` Auto Scaling Group with desired=1 for executor
- ECS cluster + Fargate task definition for researcher
- EventBridge daily schedule for researcher
- CloudWatch metric filter and alarm on `ACTION_EXECUTED` log lines, wired to trigger researcher runs

## Build and push images

From repo root:

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Executor image (ARM64)
docker buildx build --platform linux/arm64 -f docker/executor/Dockerfile -t polyautomate-executor:latest .
docker tag polyautomate-executor:latest "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/polyautomate-executor:latest"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/polyautomate-executor:latest"

# Researcher image (ARM64)
docker buildx build --platform linux/arm64 -f docker/researcher/Dockerfile -t polyautomate-researcher:latest .
docker tag polyautomate-researcher:latest "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/polyautomate-researcher:latest"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/polyautomate-researcher:latest"
```

## Deploy CDK

```bash
cd infra
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap
cdk deploy \
  -c actionThreshold=200 \
  -c dailySchedule='cron(0 3 * * ? *)'
```


## Lambda Executor Migration

`PolyautomateLambdaStack` provisions a parallel Lambda-based executor path in
`eu-west-1`. It imports the existing executor secret and portfolio dashboard
bucket, so Lambda can be iterated without updating the EC2 executor stack. This
is intended to replace the always-on EC2 executor after a parity window.

Lambda resources:

- `ExecutorStateBucket`: private S3 state for `executor/longshot-state.json`
- `ExecutorLambda`: scheduled longshot executor, default `DRY_RUN=1` for shadow testing
- `PortfolioPublisherLambda`: scheduled dashboard publisher writing `index.html` to the existing dashboard bucket
- `LambdaExecutorSchedule`: default `rate(5 minutes)`
- `LambdaPortfolioPublisherSchedule`: default `rate(5 minutes)`

Deploy the shadow stack with the existing resource names:

```bash
cdk deploy PolyautomateLambdaStack \
  -c executorSecretArn=<ExecutorCredentialsSecretArn> \
  -c portfolioBucketName=<PortfolioDashboardBucketName> \
  -c lambdaExecutorDryRun=1
```

The Lambda image uses ARM64 so it builds natively on Graviton hosts and runs
cheaper than x86. The executor handler also uses an S3 lock object to avoid
overlapping scheduled runs; this replaces Lambda reserved concurrency, which may
not be available in low-concurrency accounts.

The EC2 executor remains unchanged while Lambda is in dry-run. Cutover process:

1. Copy the latest EC2 state file to S3:

```bash
aws ssm send-command \
  --region eu-west-1 \
  --instance-ids <executor-instance-id> \
  --document-name AWS-RunShellScript \
  --parameters commands='["aws s3 cp /var/lib/polyautomate/longshot-state.json s3://<ExecutorStateBucketName>/executor/longshot-state.json --region eu-west-1"]'
```

If the deployer cannot call `ssm:SendCommand`, copy the state file manually or
temporarily grant that permission before running parity checks.

2. Compare EC2 executor logs with `ExecutorLambda` dry-run logs for at least one day.
3. Deploy `PolyautomateLambdaStack` with `-c lambdaExecutorDryRun=0`.
4. Disable or terminate the EC2 executor after Lambda places no duplicate-risk orders and the dashboard remains current.

Do not run EC2 and Lambda both live (`DRY_RUN=0`) for the same wallet. The live
position dedupe is a safety net, not the primary concurrency control.

## Runtime configuration

Executor container env vars:

- `STRATEGY_RUNNER` (default: `polyautomate.runtime.example_strategy:run_once`)
- `POLL_SECONDS` (default: `30`)
- `DRY_RUN` (default: `1`)

Researcher container env vars:

- `EXECUTOR_LOG_GROUP` (default: `/polyautomate/executor`)
- `BACKTEST_CMD` (default: `python examples/basic_usage.py`)
- `ENABLE_CLAUDE` (`1` to enable Claude CLI execution)
- `RESEARCHER_SUMMARY_PATH` (default: `/tmp/research_summary.json`)

## Portfolio dashboard

The executor host publishes a sanitized static report from
`/var/lib/polyautomate/longshot-state.json` to the dashboard S3 bucket every
minute. CloudFront serves that `index.html` with caching disabled, so there is no
public listener on the trading EC2 and no dashboard process with access to
trading credentials.

Deployment outputs include:

- `PortfolioDashboardBucketName`
- `PortfolioDashboardUrl`

The executor role only receives read/write access to that dashboard bucket. The
bucket blocks public access; CloudFront reads it through an origin access
control.

### Custom dashboard domain

The dashboard CloudFront distribution can be attached to a custom subdomain,
for example `poly.mydomain.it`, with CDK context:

```bash
cd infra
cdk deploy \
  -c portfolioDomainName=poly.mydomain.it \
  -c portfolioCertificateArn=arn:aws:acm:us-east-1:123456789012:certificate/...
```

If the domain is inside a Route 53 hosted zone controlled by this AWS account,
also pass `portfolioHostedZoneName` and CDK will create the DNS alias record:

```bash
cdk deploy \
  -c portfolioDomainName=polybot.aws.giuliovaccari.it \
  -c portfolioHostedZoneName=aws.giuliovaccari.it \
  -c portfolioHostedZoneId=Z08788173CZC2PM1CQDUQ \
  -c portfolioCertificateArn=arn:aws:acm:us-east-1:854656252703:certificate/...
```

Important details:

- CloudFront requires the ACM certificate to be in `us-east-1`, even though this
  stack is deployed in `eu-west-1`.
- If DNS stays in Squarespace, request the ACM certificate with DNS validation,
  add the validation CNAME in Squarespace, wait for issuance, then deploy CDK
  with the certificate ARN.
- After CDK deploys the alias, add a Squarespace DNS CNAME:
  `poly` -> the `PortfolioDashboardUrl` CloudFront hostname.
- CDK can automate DNS records only if the hosted zone is in Route 53. With
  Squarespace DNS, the Squarespace DNS records remain a manual step unless we
  later delegate a subdomain to Route 53.
- The shared delegated experiment zone is `aws.giuliovaccari.it`. Once
  Squarespace delegates that subdomain to Route 53, future experiment domains
  should use names like `polybot.aws.giuliovaccari.it` and pass
  `portfolioHostedZoneName=aws.giuliovaccari.it`.

## Important next wiring

- Implement your strategy function at the `STRATEGY_RUNNER` import path.
- Provide API credentials via a secure source (AWS Secrets Manager or SSM Parameter Store).
- Configure Claude Code credentials (`ANTHROPIC_API_KEY`) for the researcher task.
- Add a safe CI/CD path for researcher-generated code changes (PR flow is recommended over direct deploy).

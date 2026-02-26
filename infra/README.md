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

## Important next wiring

- Implement your strategy function at the `STRATEGY_RUNNER` import path.
- Provide API credentials via a secure source (AWS Secrets Manager or SSM Parameter Store).
- Configure Claude Code credentials (`ANTHROPIC_API_KEY`) for the researcher task.
- Add a safe CI/CD path for researcher-generated code changes (PR flow is recommended over direct deploy).

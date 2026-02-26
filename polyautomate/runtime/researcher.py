from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import boto3


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger("researcher")


def _fetch_recent_executor_events(log_group: str, lookback_hours: int = 24) -> list[dict]:
    logs_client = boto3.client("logs")
    start_time = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp() * 1000)
    paginator = logs_client.get_paginator("filter_log_events")

    events = []
    for page in paginator.paginate(
        logGroupName=log_group,
        startTime=start_time,
        filterPattern='"ACTION_EXECUTED"',
    ):
        events.extend(page.get("events", []))
    return events


def _run_backtest() -> int:
    cmd = os.getenv("BACKTEST_CMD", "python examples/basic_usage.py")
    result = subprocess.run(cmd, shell=True, check=False)
    return result.returncode


def _run_claude_if_enabled(summary_path: str) -> int:
    if os.getenv("ENABLE_CLAUDE", "0") != "1":
        LOGGER.info("claude_disabled")
        return 0

    if not shutil.which("claude"):
        LOGGER.warning("claude_cli_not_found")
        return 1

    prompt = (
        "Review executor behavior in the attached summary JSON and propose updates "
        "to strategy parameters or executor code. Run tests before finalizing changes. "
        f"Summary file: {summary_path}"
    )
    result = subprocess.run(["claude", "-p", prompt], check=False)
    return result.returncode


def main() -> None:
    log_group = os.getenv("EXECUTOR_LOG_GROUP", "/polyautomate/executor")
    output_path = os.getenv("RESEARCHER_SUMMARY_PATH", "/tmp/research_summary.json")

    events = _fetch_recent_executor_events(log_group=log_group)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "executor_action_events_last_24h": len(events),
        "sample_messages": [e.get("message", "") for e in events[:20]],
    }

    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    LOGGER.info("executor_summary_written path=%s actions=%s", output_path, len(events))

    backtest_rc = _run_backtest()
    if backtest_rc != 0:
        LOGGER.error("backtest_failed rc=%s", backtest_rc)
    else:
        LOGGER.info("backtest_succeeded")

    # Optional automated coding loop via Claude Code CLI.
    try:
        claude_rc = _run_claude_if_enabled(output_path)
    except Exception:
        LOGGER.exception("claude_run_failed")
        claude_rc = 1

    if backtest_rc != 0 or claude_rc != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

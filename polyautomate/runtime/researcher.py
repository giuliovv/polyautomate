from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import boto3
import requests


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger("researcher")


def _load_state(state_bucket: str | None, state_key: str) -> dict:
    if not state_bucket:
        return {}
    s3 = boto3.client("s3")
    try:
        result = s3.get_object(Bucket=state_bucket, Key=state_key)
    except s3.exceptions.NoSuchKey:
        return {}
    except Exception:
        LOGGER.exception("state_load_failed")
        return {}
    body = result["Body"].read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        LOGGER.warning("state_json_invalid")
        return {}


def _save_state(state: dict, state_bucket: str | None, state_key: str) -> None:
    if not state_bucket:
        return
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=state_bucket,
        Key=state_key,
        Body=json.dumps(state, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _send_telegram_message(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10).raise_for_status()
    except Exception:
        LOGGER.exception("telegram_send_failed")


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


def _run_claude_if_enabled(summary_path: str, prior_state: dict) -> int:
    if os.getenv("ENABLE_CLAUDE", "0") != "1":
        LOGGER.info("claude_disabled")
        return 0

    if not shutil.which("claude"):
        LOGGER.warning("claude_cli_not_found")
        return 1

    prior_notes = prior_state.get("claude_notes", "none")
    prompt = (
        "You are maintaining a polymarket trading system. "
        "Review latest executor behavior and improve strategy and/or code. "
        "Before proposing changes, summarize what happened and what changed since last run. "
        f"Summary file: {summary_path}. "
        f"Previous handoff notes: {prior_notes}. "
        "Return concise actionable patch plan and updated handoff notes."
    )
    result = subprocess.run(["claude", "-p", prompt], check=False)
    return result.returncode


def main() -> None:
    log_group = os.getenv("EXECUTOR_LOG_GROUP", "/polyautomate/executor")
    output_path = os.getenv("RESEARCHER_SUMMARY_PATH", "/tmp/research_summary.json")
    state_bucket = os.getenv("STATE_BUCKET")
    state_key = os.getenv("STATE_KEY", "researcher/state.json")
    prior_state = _load_state(state_bucket=state_bucket, state_key=state_key)

    events = _fetch_recent_executor_events(log_group=log_group)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "executor_action_events_last_24h": len(events),
        "sample_messages": [e.get("message", "") for e in events[:20]],
        "prior_state_present": bool(prior_state),
        "previous_run_at": prior_state.get("last_run_at"),
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
        claude_rc = _run_claude_if_enabled(output_path, prior_state=prior_state)
    except Exception:
        LOGGER.exception("claude_run_failed")
        claude_rc = 1

    next_state = {
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "last_action_event_count": len(events),
        "last_backtest_rc": backtest_rc,
        "last_claude_rc": claude_rc,
        "claude_notes": (
            "Backtest failed, investigate data/strategy assumptions."
            if backtest_rc != 0
            else "Backtest passed. Continue iterative tuning from latest executor behavior."
        ),
    }
    _save_state(next_state, state_bucket=state_bucket, state_key=state_key)

    if backtest_rc == 0 and claude_rc == 0:
        _send_telegram_message(
            f"Researcher run OK. Actions(24h)={len(events)}. State saved to {state_key}."
        )
    else:
        _send_telegram_message(
            f"Researcher run FAILED. backtest_rc={backtest_rc}, claude_rc={claude_rc}."
        )

    if backtest_rc != 0 or claude_rc != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

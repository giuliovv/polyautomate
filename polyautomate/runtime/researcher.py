from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import botocore.exceptions
import requests


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger("researcher")


@dataclass
class RunOutcome:
    backtest_rc: int
    claude_rc: int
    pr_url: str | None
    claude_notes: str


def _fetch_recent_executor_events(log_group: str, lookback_hours: int = 24) -> list[dict]:
    logs_client = boto3.client("logs")
    start_time = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp() * 1000)
    paginator = logs_client.get_paginator("filter_log_events")

    events = []
    for page in paginator.paginate(
        logGroupName=log_group,
        startTime=start_time,
    ):
        for event in page.get("events", []):
            message = event.get("message", "")
            if "ACTION_EXECUTED" in message or "executor_cycle_failed" in message:
                events.append(event)
    return events


def _load_state(state_bucket: str | None, state_key: str) -> dict:
    if not state_bucket:
        return {}
    s3 = boto3.client("s3")
    try:
        result = s3.get_object(Bucket=state_bucket, Key=state_key)
    except botocore.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "NoSuchKey":
            return {}
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
        LOGGER.info("telegram_not_configured")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10).raise_for_status()
    except Exception:
        LOGGER.exception("telegram_send_failed")


def _run_backtest(workspace_dir: Path) -> int:
    cmd_str = os.getenv("BACKTEST_CMD", "python examples/basic_usage.py")
    result = subprocess.run(shlex.split(cmd_str), cwd=str(workspace_dir), check=False)
    return result.returncode


def _run_claude_if_enabled(summary_path: str, prior_state: dict, workspace_dir: Path) -> tuple[int, str]:
    if os.getenv("ENABLE_CLAUDE", "0") != "1":
        LOGGER.info("claude_disabled")
        return 0, "Claude disabled by configuration."

    if not shutil.which("claude"):
        LOGGER.warning("claude_cli_not_found")
        return 1, "Claude CLI not found in PATH."

    prior_notes = prior_state.get("claude_notes", "none")
    prompt = (
        "You are maintaining a Polymarket algorithmic trading system. "
        "Review the latest executor behavior and improve strategy and/or code with discipline. "
        "Do NOT make random parameter churn. Prefer no-change if evidence is weak. "
        "Use historical data/backtests, state assumptions explicitly, and avoid overfitting. "
        "Before proposing changes, summarize what happened and what changed since last run. "
        f"Summary file: {summary_path}. "
        f"Previous handoff notes: {prior_notes}. "
        "\n\n"
        "=== STRATEGY CONTEXT ===\n"
        "\n"
        "CURRENT LIVE STRATEGY: Longshot Bias (SELL-only)\n"
        "  File: polyautomate/runtime/longshot_executor.py\n"
        "  Core logic: Scan open markets for YES price <= LONGSHOT_THRESHOLD (default 0.40). "
        "Buy NO tokens (equivalent to selling YES). Hold to market resolution.\n"
        "\n"
        "THEORETICAL BASIS:\n"
        "  Prediction markets exhibit longshot bias: bettors systematically overweight low-probability "
        "events. A YES token priced at 0.20 implies 20% resolution probability but empirically resolves "
        "YES far less often. Empirical results (89-day window, 400 resolved markets — see LONGSHOT_ANALYSIS.md):\n"
        "    - threshold=0.25: 69 trades, 89.9% win rate, +4.29 P&L, Sharpe 0.489\n"
        "    - threshold=0.35: 72 trades, 90.3% win rate, +6.68 P&L, Sharpe 0.614\n"
        "    - threshold=0.40: 72 trades, 91.7% win rate, +7.68 P&L, Sharpe 0.647  ← current live setting\n"
        "  Calibration at threshold=0.35: markets priced 0.20-0.35 resolved YES only 4.3% vs 27.5% implied.\n"
        "\n"
        "WHY SELL-ONLY (no BUY for favorites):\n"
        "  The symmetric trade — buying YES when price >= 0.65 — was tested and failed. Root cause: "
        "live sports/esports markets regularly spike above 0.65 during games then resolve the other way, "
        "generating false BUY signals. With no-sports filter, only 7 trades remained at 57.1% win — not "
        "statistically meaningful. The academic 'favorites are underpriced' effect may exist but requires "
        "a different entry condition (market opens above threshold, not zone-crossing). NOT implemented. "
        "Do NOT add a BUY YES leg unless you have strong statistical evidence from a dedicated backtest.\n"
        "\n"
        "SPREAD FILTER (critical for execution quality):\n"
        "  The executor filters candidates by: avg_spread <= LONGSHOT_MAX_SPREAD (default 0.03) and "
        "rel_spread <= LONGSHOT_MAX_REL_SPREAD (default 0.15). This is essential because spread cost "
        "directly eats into per-trade P&L (~1-1.5pp per trade at typical 2-3pp spread). "
        "The analytics backtesting engine models spread friction via bid/ask execution prices "
        "(entries at best ask, exits at best bid), but the LongshotBiasStrategy analytics class "
        "does not pre-filter by spread — only the executor does. When evaluating backtest P&L, "
        "account for this: gross P&L overstates net returns if spread filtering wasn't applied.\n"
        "\n"
        "POSITION SIZING — Kelly Criterion:\n"
        "  The executor uses fractional Kelly sizing (LONGSHOT_USE_KELLY=1). Parameters:\n"
        "    - LONGSHOT_BANKROLL_USD: total capital base (default 500)\n"
        "    - LONGSHOT_KELLY_FRACTION: fraction of full Kelly to apply (default 0.25 = quarter-Kelly)\n"
        "    - LONGSHOT_MAX_BANKROLL_FRACTION: hard cap per trade (default 0.03 = 3% of bankroll)\n"
        "    - LONGSHOT_MIN_NOTIONAL_USD / LONGSHOT_MAX_NOTIONAL_USD: absolute size bounds (2-25 USD)\n"
        "  Kelly formula uses _estimate_no_win_prob() which returns heuristic NO win probabilities "
        "calibrated from LONGSHOT_ANALYSIS.md: p=0.995 for YES<=0.10, p=0.985 for YES<=0.20, "
        "p=0.957 for YES<=0.35, p=0.917 otherwise.\n"
        "  Quarter-Kelly is intentional: the tail risk is severe — a YES<=0.25 trade that resolves "
        "YES loses ~0.75 per unit, wiping out many small wins (worst trade: -0.749 on Costa Rica).\n"
        "\n"
        "POSITION MANAGEMENT — Hold to Resolution:\n"
        "  No stop-loss or take-profit. Positions are held until the market status becomes "
        "'resolved' or 'closed', or until end_date + LONGSHOT_HOLD_GRACE_HOURS (default 24h) elapses. "
        "Intermediate price moves are noise — the edge is captured at resolution.\n"
        "\n"
        "MARKET SELECTION RULES:\n"
        "  - Exclude sports/live-game markets (keyword filter in _is_sports_market())\n"
        "  - Require min LONGSHOT_MIN_DAYS_LEFT (default 2) days to resolution\n"
        "  - One position per market at a time (open_positions state)\n"
        "  - Preferred: political events, geopolitical outcomes, earnings beats, long-duration events\n"
        "  - Avoid: same-day sports, crypto 5-min markets, intra-game props\n"
        "\n"
        "SAFETY SYSTEMS:\n"
        "  - Guardrail: halts trading if recent win rate < LONGSHOT_GUARDRAIL_MIN_WIN_RATE (0.35) "
        "or total P&L < LONGSHOT_GUARDRAIL_MIN_PNL_USD (-5) over last N closed positions\n"
        "  - Dry-run mode: DRY_RUN=1 logs all decisions without placing orders\n"
        "  - Shadow runner: SHADOW_STRATEGY_RUNNER runs a variant in parallel with DRY_RUN=1\n"
        "\n"
        "ANALYTICS vs EXECUTOR:\n"
        "  The analytics layer (polyautomate/analytics/) provides backtesting via BacktestEngine "
        "and strategy classes (LongshotBiasStrategy, MACDMomentumStrategy, RSIMeanReversionStrategy, "
        "WhaleWatcherStrategy, ProfileStrategy). The executor does NOT use these — it is a standalone "
        "implementation of the longshot logic with its own state management and market scanning. "
        "There is also an ML-based ProfileStrategy (optimal_entry.py) that learns indicator "
        "fingerprints of optimal entry bars — it is available for backtesting but not wired into "
        "any live executor.\n"
        "\n"
        "=== GUIDELINES FOR CHANGES ===\n"
        "- Any new strategy variant must be configured as SHADOW_STRATEGY_RUNNER with SHADOW_DRY_RUN=1 "
        "and SHADOW_ENV_OVERRIDES_JSON for its params. Run in parallel without risk before promoting.\n"
        "- Only promote shadow to main after statistically meaningful outperformance (suggest >= 20 "
        "closed trades and win rate / Sharpe clearly better than baseline).\n"
        "- Tunable parameters (safe to adjust based on evidence): LONGSHOT_THRESHOLD, "
        "LONGSHOT_MIN_DAYS_LEFT, LONGSHOT_MAX_SPREAD, LONGSHOT_MAX_REL_SPREAD, LONGSHOT_KELLY_FRACTION, "
        "LONGSHOT_BANKROLL_USD, LONGSHOT_MAX_ACTIONS_PER_CYCLE.\n"
        "- Do NOT remove the spread filter — it is critical for execution quality.\n"
        "- Do NOT add BUY YES signals without a dedicated backtest proving the entry condition works.\n"
        "- Do NOT change position management from hold-to-resolution to SL/TP — that defeats the strategy.\n"
        "Apply concrete code updates if justified, run validations, and provide concise handoff notes "
        "plus promotion criteria for any shadow strategy."
    )

    result = subprocess.run(
        ["claude", "-p", prompt],
        cwd=str(workspace_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "").strip()
    if not output:
        output = (result.stderr or "").strip()
    notes = output[:2000] if output else "Claude produced no output."
    return result.returncode, notes


def _prepare_workspace() -> tuple[Path, str | None, str]:
    workspace_root = Path(os.getenv("RESEARCHER_WORKSPACE", "/tmp/researcher-repo"))
    repo_full_name = os.getenv("GITHUB_REPO", "")
    base_branch = os.getenv("GITHUB_BASE_BRANCH", "main")
    github_token = os.getenv("GITHUB_TOKEN", "")

    if not repo_full_name or not github_token:
        LOGGER.warning("github_not_configured_using_image_workspace")
        return Path("/app"), None, base_branch

    clone_url = f"https://x-access-token:{github_token}@github.com/{repo_full_name}.git"
    if (workspace_root / ".git").exists():
        subprocess.run(["git", "remote", "set-url", "origin", clone_url], cwd=str(workspace_root), check=True)
        subprocess.run(["git", "fetch", "origin", base_branch], cwd=str(workspace_root), check=True)
        subprocess.run(["git", "checkout", base_branch], cwd=str(workspace_root), check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=str(workspace_root), check=True)
        subprocess.run(["git", "clean", "-fd"], cwd=str(workspace_root), check=True)
    else:
        if workspace_root.exists():
            shutil.rmtree(workspace_root)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", base_branch, clone_url, str(workspace_root)],
            check=True,
        )

    branch_name = f"researcher/{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    subprocess.run(["git", "checkout", "-b", branch_name], cwd=str(workspace_root), check=True)
    subprocess.run(["git", "config", "user.name", "polyautomate-researcher"], cwd=str(workspace_root), check=True)
    subprocess.run(["git", "config", "user.email", "researcher@local"], cwd=str(workspace_root), check=True)
    return workspace_root, branch_name, base_branch


def _open_pull_request(repo_full_name: str, token: str, branch_name: str, base_branch: str, body: str) -> str:
    url = f"https://api.github.com/repos/{repo_full_name}/pulls"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "title": f"researcher: automated strategy update ({branch_name})",
        "head": branch_name,
        "base": base_branch,
        "body": body,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=20)
    response.raise_for_status()
    return response.json().get("html_url", "")


def _maybe_commit_and_pr(workspace_dir: Path, summary: dict, claude_notes: str) -> str | None:
    if os.getenv("ENABLE_PR_AUTOMATION", "0") != "1":
        LOGGER.info("pr_automation_disabled")
        return None

    repo_full_name = os.getenv("GITHUB_REPO", "")
    base_branch = os.getenv("GITHUB_BASE_BRANCH", "main")
    github_token = os.getenv("GITHUB_TOKEN", "")
    if not repo_full_name or not github_token:
        LOGGER.warning("pr_automation_not_configured")
        return None

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(workspace_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        LOGGER.info("no_changes_to_commit")
        return None

    branch_name = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(workspace_dir),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    subprocess.run(["git", "add", "-A"], cwd=str(workspace_dir), check=True)
    subprocess.run(
        ["git", "commit", "-m", "researcher: automated strategy/code update"],
        cwd=str(workspace_dir),
        check=True,
    )
    subprocess.run(["git", "push", "origin", branch_name], cwd=str(workspace_dir), check=True)

    body = (
        "Automated researcher update.\n\n"
        f"- executor_action_events_last_24h: {summary.get('executor_action_events_last_24h')}\n"
        f"- generated_at: {summary.get('generated_at')}\n\n"
        "Claude notes:\n"
        f"{claude_notes[:4000]}"
    )
    return _open_pull_request(
        repo_full_name=repo_full_name,
        token=github_token,
        branch_name=branch_name,
        base_branch=base_branch,
        body=body,
    )


def _execute_research_cycle(
    summary_path: str,
    prior_state: dict,
    workspace_dir: Path,
) -> RunOutcome:
    backtest_rc = _run_backtest(workspace_dir=workspace_dir)
    if backtest_rc != 0:
        LOGGER.error("backtest_failed rc=%s", backtest_rc)
    else:
        LOGGER.info("backtest_succeeded")

    try:
        claude_rc, claude_notes = _run_claude_if_enabled(
            summary_path=summary_path,
            prior_state=prior_state,
            workspace_dir=workspace_dir,
        )
    except Exception:
        LOGGER.exception("claude_run_failed")
        claude_rc = 1
        claude_notes = "Claude run raised an exception."

    pr_url = None
    if backtest_rc == 0 and claude_rc == 0:
        try:
            pr_url = _maybe_commit_and_pr(
                workspace_dir=workspace_dir,
                summary=json.loads(Path(summary_path).read_text(encoding="utf-8")),
                claude_notes=claude_notes,
            )
        except Exception:
            LOGGER.exception("pr_creation_failed")

    return RunOutcome(
        backtest_rc=backtest_rc,
        claude_rc=claude_rc,
        pr_url=pr_url,
        claude_notes=claude_notes,
    )


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

    workspace_dir, _branch_name, _base_branch = _prepare_workspace()
    outcome = _execute_research_cycle(
        summary_path=output_path,
        prior_state=prior_state,
        workspace_dir=workspace_dir,
    )

    next_state = {
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "last_action_event_count": len(events),
        "last_backtest_rc": outcome.backtest_rc,
        "last_claude_rc": outcome.claude_rc,
        "last_pr_url": outcome.pr_url,
        "claude_notes": outcome.claude_notes[:2000],
    }
    _save_state(next_state, state_bucket=state_bucket, state_key=state_key)

    if outcome.backtest_rc == 0 and outcome.claude_rc == 0:
        msg = (
            f"Researcher run OK. Actions(24h)={len(events)}. "
            f"PR={outcome.pr_url or 'none'}"
        )
        _send_telegram_message(msg)
    else:
        _send_telegram_message(
            f"Researcher run FAILED. backtest_rc={outcome.backtest_rc}, claude_rc={outcome.claude_rc}."
        )

    if outcome.backtest_rc != 0 or outcome.claude_rc != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

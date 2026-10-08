from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from polyautomate.portfolio import write_data_api_report
from polyautomate.runtime.longshot_executor import run_once

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger("lambda_handlers")


def _load_secret_env() -> dict[str, str]:
    secret_arn = os.getenv("EXECUTOR_SECRET_ARN", "").strip()
    if not secret_arn:
        return {}
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"))
    payload = client.get_secret_value(SecretId=secret_arn).get("SecretString") or "{}"
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError(f"secret payload must be a JSON object: {secret_arn}")
    values = {str(k): "" if v is None else str(v) for k, v in data.items()}
    for key, value in values.items():
        if value and value not in {"REPLACE_ME", "null"}:
            os.environ[key] = value
    os.environ.setdefault("POLYMARKET_SIGNATURE_TYPE", values.get("POLYMARKET_SIGNATURE_TYPE", "1") or "1")
    return values


def _lock_client():
    return boto3.client("s3", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"))


def _acquire_executor_lock(request_id: str | None) -> tuple[str, str] | None:
    bucket = os.getenv("LONGSHOT_STATE_BUCKET", "").strip()
    if not bucket:
        LOGGER.info("executor_lock_disabled reason=missing_state_bucket")
        return "", ""
    key = os.getenv("LONGSHOT_LOCK_KEY", "executor/longshot-state.lock").strip()
    client = _lock_client()
    body = json.dumps({"request_id": request_id, "pid": os.getpid()}).encode("utf-8")
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            CacheControl="no-store",
            IfNoneMatch="*",
        )
        LOGGER.info("executor_lock_acquired bucket=%s key=%s", bucket, key)
        return bucket, key
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"PreconditionFailed", "ConditionalRequestConflict"}:
            LOGGER.warning("executor_lock_busy bucket=%s key=%s", bucket, key)
            return None
        raise


def _release_executor_lock(lock: tuple[str, str] | None) -> None:
    if not lock:
        return
    bucket, key = lock
    if not bucket:
        return
    try:
        _lock_client().delete_object(Bucket=bucket, Key=key)
        LOGGER.info("executor_lock_released bucket=%s key=%s", bucket, key)
    except Exception:
        LOGGER.exception("executor_lock_release_failed bucket=%s key=%s", bucket, key)


def executor_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    _load_secret_env()
    lock = _acquire_executor_lock(getattr(context, "aws_request_id", None))
    if lock is None:
        return {"ok": True, "skipped": "lock_busy", "actions": 0, "dry_run": os.getenv("DRY_RUN", "")}
    LOGGER.info(
        "lambda_executor_start dry_run=%s state_bucket=%s state_key=%s schedule_event=%s",
        os.getenv("DRY_RUN"),
        os.getenv("LONGSHOT_STATE_BUCKET"),
        os.getenv("LONGSHOT_STATE_KEY"),
        bool(event),
    )
    try:
        actions = int(run_once())
        LOGGER.info("lambda_executor_complete actions=%s dry_run=%s", actions, os.getenv("DRY_RUN"))
        return {"ok": True, "actions": actions, "dry_run": os.getenv("DRY_RUN", "")}
    finally:
        _release_executor_lock(lock)


def portfolio_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    secret_values = _load_secret_env()
    user = os.getenv("POLYMARKET_ADDRESS") or secret_values.get("POLYMARKET_ADDRESS", "")
    bucket = os.environ["PORTFOLIO_BUCKET"]
    key = os.getenv("PORTFOLIO_KEY", "index.html")
    out_path = Path("/tmp/polyautomate-portfolio.html")
    if not user:
        raise RuntimeError("missing POLYMARKET_ADDRESS for portfolio publisher")

    write_data_api_report(user, out_path, include_clob_balance=os.getenv("PORTFOLIO_INCLUDE_CLOB_BALANCE", "1") == "1")
    boto3.client("s3", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")).put_object(
        Bucket=bucket,
        Key=key,
        Body=out_path.read_bytes(),
        ContentType="text/html; charset=utf-8",
        CacheControl="no-store",
    )
    LOGGER.info("lambda_portfolio_published bucket=%s key=%s user=%s", bucket, key, user)
    return {"ok": True, "bucket": bucket, "key": key}

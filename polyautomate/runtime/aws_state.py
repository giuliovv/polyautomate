from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def _s3_client():
    import boto3

    return boto3.client("s3", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"))


def load_json_state(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    bucket = os.getenv("LONGSHOT_STATE_BUCKET", "").strip()
    key = os.getenv("LONGSHOT_STATE_KEY", "longshot-state.json").strip()
    if bucket:
        client = _s3_client()
        try:
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            data = json.loads(body.decode("utf-8"))
            if isinstance(data, dict):
                return data
            LOGGER.warning("s3_state_not_object bucket=%s key=%s", bucket, key)
        except client.exceptions.NoSuchKey:
            LOGGER.info("s3_state_missing bucket=%s key=%s", bucket, key)
        except Exception:
            LOGGER.exception("s3_state_load_failed bucket=%s key=%s", bucket, key)
        return dict(fallback)

    if not path.exists():
        return dict(fallback)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(fallback)
    except Exception:
        LOGGER.exception("state_load_failed path=%s", path)
        return dict(fallback)


def save_json_state(path: Path, state: dict[str, Any]) -> None:
    payload = json.dumps(state, indent=2, sort_keys=True).encode("utf-8")
    bucket = os.getenv("LONGSHOT_STATE_BUCKET", "").strip()
    key = os.getenv("LONGSHOT_STATE_KEY", "longshot-state.json").strip()
    if bucket:
        _s3_client().put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType="application/json; charset=utf-8",
            CacheControl="no-store",
        )
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp_path.write_bytes(payload)
    tmp_path.replace(path)

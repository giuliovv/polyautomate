from __future__ import annotations

import importlib
import json
import logging
import os
import time
from contextlib import contextmanager
from typing import Callable


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger("executor")


def _load_runner(path: str) -> Callable[[], int]:
    module_name, func_name = path.split(":", maxsplit=1)
    module = importlib.import_module(module_name)
    fn = getattr(module, func_name)
    if not callable(fn):
        raise TypeError(f"Runner {path} is not callable")
    return fn


@contextmanager
def _temporary_env(overrides: dict[str, str]):
    original: dict[str, str | None] = {}
    try:
        for key, value in overrides.items():
            original[key] = os.environ.get(key)
            os.environ[key] = value
        yield
    finally:
        for key, old in original.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def _load_shadow_overrides() -> dict[str, str]:
    raw = os.getenv("SHADOW_ENV_OVERRIDES_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.warning("invalid_shadow_env_overrides_json")
        return {}
    if not isinstance(payload, dict):
        LOGGER.warning("shadow_env_overrides_not_dict")
        return {}
    return {str(k): str(v) for k, v in payload.items()}


def main() -> None:
    runner_path = os.getenv("STRATEGY_RUNNER", "polyautomate.runtime.example_strategy:run_once")
    shadow_runner_path = os.getenv("SHADOW_STRATEGY_RUNNER", "").strip()
    poll_seconds = int(os.getenv("POLL_SECONDS", "30"))
    dry_run = os.getenv("DRY_RUN", "1") == "1"
    shadow_dry_run = os.getenv("SHADOW_DRY_RUN", "1") == "1"
    shadow_overrides = _load_shadow_overrides()

    run_once = _load_runner(runner_path)
    run_shadow_once = _load_runner(shadow_runner_path) if shadow_runner_path else None
    LOGGER.info("executor started runner=%s dry_run=%s", runner_path, dry_run)
    if run_shadow_once:
        LOGGER.info("shadow started runner=%s dry_run=%s", shadow_runner_path, shadow_dry_run)

    while True:
        try:
            action_count = int(run_once())
            if action_count > 0:
                LOGGER.info("ACTION_EXECUTED count=%s dry_run=%s", action_count, dry_run)
            else:
                LOGGER.info("cycle_complete count=0")
        except Exception:
            LOGGER.exception("executor_cycle_failed")

        if run_shadow_once:
            try:
                env = {"DRY_RUN": "1" if shadow_dry_run else "0"}
                env.update(shadow_overrides)
                with _temporary_env(env):
                    shadow_count = int(run_shadow_once())
                LOGGER.info("shadow_cycle_complete count=%s dry_run=%s", shadow_count, shadow_dry_run)
            except Exception:
                LOGGER.exception("shadow_cycle_failed")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()

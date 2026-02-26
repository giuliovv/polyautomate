from __future__ import annotations

import importlib
import logging
import os
import time
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


def main() -> None:
    runner_path = os.getenv("STRATEGY_RUNNER", "polyautomate.runtime.example_strategy:run_once")
    poll_seconds = int(os.getenv("POLL_SECONDS", "30"))
    dry_run = os.getenv("DRY_RUN", "1") == "1"

    run_once = _load_runner(runner_path)
    LOGGER.info("executor started runner=%s dry_run=%s", runner_path, dry_run)

    while True:
        try:
            action_count = int(run_once())
            if action_count > 0:
                LOGGER.info("ACTION_EXECUTED count=%s dry_run=%s", action_count, dry_run)
            else:
                LOGGER.info("cycle_complete count=0")
        except Exception:
            LOGGER.exception("executor_cycle_failed")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()

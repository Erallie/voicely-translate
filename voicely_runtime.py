"""Runtime utilities shared by the Voicely bot components."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any


def configure_logging() -> None:
    """Configure concise, timestamped application logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


class BackgroundTasks:
    """Own background tasks so they can be observed and cancelled cleanly."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._tasks: set[asyncio.Task[Any]] = set()

    def create(self, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._logger.error(
                "Background task failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def cancel_all(self) -> None:
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

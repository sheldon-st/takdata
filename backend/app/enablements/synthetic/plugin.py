"""Synthetic CoT harness enablement — load-test takserver."""

import asyncio
from typing import Optional

from app.enablements.base import EnablementPlugin, EnablementStats
from app.enablements.registry import register
from app.enablements.synthetic.worker import SyntheticWorker


@register
class SyntheticEnablement(EnablementPlugin):
    TYPE_ID = "synthetic"
    DISPLAY_NAME = "Synthetic CoT Harness"
    DESCRIPTION = (
        "Emits fabricated CoT events at a configurable rate for load-testing "
        "the TAK server and downstream consumers."
    )

    def __init__(self, enablement_id: int, config: dict, tx_queue: asyncio.Queue) -> None:
        super().__init__(enablement_id, config, tx_queue)
        self._worker: Optional[SyntheticWorker] = None

    async def start(self) -> None:
        self._worker = SyntheticWorker(
            enablement_id=self.enablement_id,
            tx_queue=self.tx_queue,
            config=self.config,
        )
        task = asyncio.ensure_future(self._worker.run())
        self._tasks.append(task)
        self._running = True
        self.log.info(
            "Started synthetic harness: %d entities @ %.1f Hz",
            self._worker.entity_count,
            self._worker.target_rate_hz,
        )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._running = False
        self.log.info("Stopped")

    def get_stats(self) -> EnablementStats:
        if self._worker:
            return self._worker.get_stats()
        return EnablementStats()

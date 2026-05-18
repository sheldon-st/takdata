"""
AIS Maritime Tracking enablement plugin.
Registers itself with the plugin registry via @register.
"""

import asyncio
import logging
from typing import Optional

from app.enablements.base import EnablementPlugin, EnablementStats
from app.enablements.registry import register
from app.enablements.ais.worker import AisWorker

log = logging.getLogger(__name__)

# Pre-configured source shown to users in the UI
KNOWN_SOURCES = [
    {
        "id": "aisstream_io",
        "name": "aisstream.io",
        "base_url": "wss://stream.aisstream.io/v0/stream",
        "endpoint": "",  # API key — obtain a free key at https://aisstream.io
        "description": (
            "Real-time global AIS vessel tracking via aisstream.io WebSocket. "
            "Free API key required. Set lat/lon/distance on this source to define "
            "the area of interest."
        ),
        "requires_location": True,
    },
]


@register
class AisEnablement(EnablementPlugin):
    TYPE_ID = "ais"
    DISPLAY_NAME = "AIS Maritime Tracking"
    DESCRIPTION = (
        "Subscribes to the aisstream.io WebSocket feed and converts vessel "
        "positions to CoT events for display on TAK clients."
    )

    def __init__(self, enablement_id: int, config: dict, tx_queue: asyncio.Queue) -> None:
        super().__init__(enablement_id, config, tx_queue)
        self._worker: Optional[AisWorker] = None

    async def start(self) -> None:
        sources = self.config.get("sources", [])
        self._worker = AisWorker(
            tx_queue=self.tx_queue,
            config=self.config,
            sources=sources,
        )
        task = asyncio.ensure_future(self._worker.run())
        self._tasks.append(task)
        self._running = True
        self.log.info("Started with %d source(s)", len(sources))

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

    @classmethod
    def get_known_sources(cls) -> list[dict]:
        """Return pre-configured source templates for the UI."""
        return KNOWN_SOURCES

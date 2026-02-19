"""
ADS-B enablement plugin.
Registers itself with the plugin registry via @register.
"""

import asyncio
import logging
from typing import Optional

from app.enablements.base import EnablementPlugin, EnablementStats
from app.enablements.registry import register
from app.enablements.adsb.worker import AdsbWorker

log = logging.getLogger(__name__)

# Pre-configured sources shown to users in the UI
KNOWN_SOURCES = [
    {
        "id": "adsb_fi_mil",
        "name": "ADS-B.fi — Military",
        "base_url": "https://opendata.adsb.fi/api/v2",
        "endpoint": "mil",
        "description": "Military aircraft tracked worldwide",
        "requires_location": False,
    },
    {
        "id": "adsb_fi_geo",
        "name": "ADS-B.fi — Geographic",
        "base_url": "https://opendata.adsb.fi/api/v2",
        "endpoint": "geo",
        "description": "All aircraft within a radius of a location",
        "requires_location": True,
    },
    {
        "id": "adsb_lol_point",
        "name": "ADSB.lol — Point",
        "base_url": "https://api.adsb.lol/v2",
        "endpoint": "point",
        "description": "Point-based query via ADSB.lol",
        "requires_location": True,
    },
    {
        "id": "adsb_lol_mil",
        "name": "ADSB.lol — Military",
        "base_url": "https://api.adsb.lol/v2",
        "endpoint": "mil",
        "description": "Military aircraft via ADSB.lol",
        "requires_location": False,
    },
]


@register
class AdsbEnablement(EnablementPlugin):
    TYPE_ID = "adsb"
    DISPLAY_NAME = "ADS-B Aircraft Tracking"
    DESCRIPTION = (
        "Polls public ADS-B APIs and converts aircraft positions to CoT events "
        "for display on TAK clients."
    )

    def __init__(self, enablement_id: int, config: dict, tx_queue: asyncio.Queue) -> None:
        super().__init__(enablement_id, config, tx_queue)
        self._worker: Optional[AdsbWorker] = None

    async def start(self) -> None:
        sources = self.config.get("sources", [])
        self._worker = AdsbWorker(
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

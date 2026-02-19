"""
AIS Maritime Tracking enablement — stub for future implementation.

To implement:
  1. Add an AisWorker in worker.py that polls an AIS API (e.g. aisstream.io,
     MarineTraffic, or a self-hosted receiver) and converts vessel data to CoT.
  2. Add a converter.py that produces CoT XML from AIS vessel dicts.
  3. Fill in start() / stop() / get_stats() below.
  4. The @register decorator and the import in ais/__init__.py handle
     registration automatically — no other files need to change.
"""

import asyncio

from app.enablements.base import EnablementPlugin, EnablementStats
from app.enablements.registry import register


@register
class AisEnablement(EnablementPlugin):
    TYPE_ID = "ais"
    DISPLAY_NAME = "AIS Maritime Tracking"
    DESCRIPTION = "Polls AIS data feeds and converts vessel positions to CoT events (coming soon)."

    async def start(self) -> None:
        self.log.warning("AIS enablement is not yet implemented")
        self._running = False

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._running = False

    def get_stats(self) -> EnablementStats:
        return EnablementStats()

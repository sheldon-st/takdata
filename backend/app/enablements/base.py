"""
Abstract base class for all TAK data enablements.

A new enablement type (e.g. AIS, MLAT, ATC) requires:
  1. A package under app/enablements/<type_id>/
  2. A class that extends EnablementPlugin, decorated with @register
  3. An import of that class in app/enablements/__init__.py

No changes to routes, RuntimeManager, or DB schema are needed.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Optional


@dataclass
class EnablementStats:
    """Live metrics exposed via GET /status and WS /ws/status."""
    events_sent: int = 0
    last_poll_time: Optional[datetime] = None
    last_error: Optional[str] = None
    active_items: int = 0  # aircraft count, vessel count, etc.
    source_stats: dict = field(default_factory=dict)  # per-source breakdown


class EnablementPlugin(ABC):
    """
    Contract all enablement plugins must implement.

    Lifecycle managed by RuntimeManager:
      1. Instantiate: plugin = PluginClass(enablement_id, config, tx_queue)
      2. Start:       await plugin.start()
      3. Stop:        await plugin.stop()
      4. Stats:       plugin.get_stats()          (polled by WebSocket broadcaster)
      5. Hot-reload:  await plugin.on_config_updated(new_config)

    All CoT bytes are pushed to self.tx_queue:
      await self.tx_queue.put(cot_bytes)
    """

    TYPE_ID: ClassVar[str] = ""
    DISPLAY_NAME: ClassVar[str] = ""
    DESCRIPTION: ClassVar[str] = ""

    def __init__(
        self,
        enablement_id: int,
        config: dict,
        tx_queue: asyncio.Queue,
    ):
        self.enablement_id = enablement_id
        self.config = config
        self.tx_queue = tx_queue
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self.log = logging.getLogger(f"enablement.{self.TYPE_ID}.{enablement_id}")

    @property
    def is_running(self) -> bool:
        return self._running and any(not t.done() for t in self._tasks)

    @abstractmethod
    async def start(self) -> None:
        """
        Begin processing. Called from within the running event loop.
        Implementors must create asyncio Tasks and store them in self._tasks.

        Example:
            task = asyncio.ensure_future(self._poll_loop())
            self._tasks.append(task)
            self._running = True
        """

    @abstractmethod
    async def stop(self) -> None:
        """
        Gracefully stop all tasks.

        Example:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
            self._running = False
        """

    @abstractmethod
    def get_stats(self) -> EnablementStats:
        """Return current live stats."""

    async def on_config_updated(self, new_config: dict) -> None:
        """Called when config is updated via API. Default: stop and restart."""
        await self.stop()
        self.config = new_config
        await self.start()

"""
RuntimeManager — central coordinator for the TAK connection and all enablement workers.

Design notes:
  - We do NOT call clitool.run() because it uses asyncio.wait(FIRST_COMPLETED) and
    returns the moment any task finishes. Instead:
      1. clitool.setup()      — creates TXWorker + RXWorker, stores in clitool.tasks
      2. clitool.run_tasks()  — schedules them via asyncio.ensure_future()
      3. Enablement plugins receive clitool.tx_queue directly and push CoT bytes to it
      4. disconnect_tak() cancels all running_tasks explicitly
  - Module-level singleton `runtime_manager` is imported by FastAPI routes and lifespan.
"""

import asyncio
import logging
from configparser import ConfigParser
from datetime import datetime
from typing import Optional

import pytak

from app.enablements.base import EnablementPlugin
from app.enablements.registry import get_plugin_class

log = logging.getLogger(__name__)


class RuntimeManager:
    def __init__(self) -> None:
        self._clitool: Optional[pytak.CLITool] = None
        self._tx_queue: Optional[asyncio.Queue] = None
        self._connected: bool = False
        self._tak_config: dict = {}
        self._connect_error: Optional[str] = None

        # enablement_id (DB row id) -> plugin instance
        self._active_enablements: dict[int, EnablementPlugin] = {}

    # ------------------------------------------------------------------
    # TAK connection lifecycle
    # ------------------------------------------------------------------

    async def connect_tak(self, tak_config: dict) -> None:
        """
        Establish pytak TLS connection to the TAK server.

        tak_config keys (all strings/bool/int):
          cot_url, cert_path, cert_password, cot_host_id,
          dont_check_hostname, dont_verify, max_out_queue, max_in_queue
        """
        if self._connected:
            await self.disconnect_tak()

        cp = ConfigParser()
        cp["tak"] = {
            "COT_URL": tak_config.get("cot_url", "tls://localhost:8089"),
            "PYTAK_TLS_CLIENT_CERT": tak_config.get("cert_path") or "",
            "PYTAK_TLS_CLIENT_PASSWORD": tak_config.get("cert_password") or "",
            "PYTAK_TLS_DONT_CHECK_HOSTNAME": str(int(tak_config.get("dont_check_hostname", 1))),
            "PYTAK_TLS_DONT_VERIFY": str(int(tak_config.get("dont_verify", 1))),
            "MAX_OUT_QUEUE": str(tak_config.get("max_out_queue", 1000)),
            "MAX_IN_QUEUE": str(tak_config.get("max_in_queue", 1000)),
            "COT_HOST_ID": tak_config.get("cot_host_id", "tak-manager"),
        }

        try:
            self._clitool = pytak.CLITool(cp["tak"])
            await self._clitool.setup()
            self._clitool.run_tasks()  # schedules TX + RX workers as asyncio futures
            self._tx_queue = self._clitool.tx_queue
            self._connected = True
            self._connect_error = None
            self._tak_config = tak_config
            log.info("Connected to TAK server: %s", tak_config.get("cot_url"))
        except Exception as exc:
            self._connect_error = str(exc)
            self._connected = False
            self._clitool = None
            self._tx_queue = None
            log.error("Failed to connect to TAK server: %s", exc)
            raise

    async def disconnect_tak(self) -> None:
        """Stop all enablements and close the TAK connection."""
        # Stop workers first so they don't try to enqueue after queue is gone
        for eid in list(self._active_enablements.keys()):
            await self.stop_enablement(eid)

        if self._clitool:
            for task in list(getattr(self._clitool, "running_tasks", [])):
                task.cancel()
            running = list(getattr(self._clitool, "running_tasks", []))
            if running:
                await asyncio.gather(*running, return_exceptions=True)

        self._clitool = None
        self._tx_queue = None
        self._connected = False
        log.info("Disconnected from TAK server")

    # ------------------------------------------------------------------
    # Enablement lifecycle
    # ------------------------------------------------------------------

    async def start_enablement(
        self, enablement_id: int, type_id: str, config: dict
    ) -> None:
        """
        Instantiate and start an enablement plugin.

        config dict should contain the DB row fields plus a 'sources' list.
        Raises RuntimeError if not connected to TAK server.
        """
        if not self._connected or self._tx_queue is None:
            raise RuntimeError("Not connected to TAK server. Connect first.")

        if enablement_id in self._active_enablements:
            log.warning("Enablement %d already running, restarting", enablement_id)
            await self.stop_enablement(enablement_id)

        plugin_cls = get_plugin_class(type_id)
        plugin = plugin_cls(
            enablement_id=enablement_id,
            config=config,
            tx_queue=self._tx_queue,
        )
        await plugin.start()
        self._active_enablements[enablement_id] = plugin
        log.info("Started enablement %d (%s: %s)", enablement_id, type_id, config.get("name"))

    async def stop_enablement(self, enablement_id: int) -> None:
        """Stop and remove a running enablement plugin."""
        plugin = self._active_enablements.pop(enablement_id, None)
        if plugin:
            await plugin.stop()
            log.info("Stopped enablement %d", enablement_id)

    async def restart_enablement(self, enablement_id: int, new_config: dict) -> None:
        """Update config and restart an active enablement."""
        plugin = self._active_enablements.get(enablement_id)
        if plugin:
            await plugin.on_config_updated(new_config)
        else:
            log.debug("restart_enablement: %d not running, ignoring", enablement_id)

    def is_enablement_running(self, enablement_id: int) -> bool:
        plugin = self._active_enablements.get(enablement_id)
        return plugin.is_running if plugin else False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Full status snapshot for HTTP GET /status and WebSocket broadcast."""
        enablements_status = []
        for eid, plugin in self._active_enablements.items():
            stats = plugin.get_stats()
            enablements_status.append(
                {
                    "id": eid,
                    "name": plugin.config.get("name", ""),
                    "type_id": plugin.TYPE_ID,
                    "running": plugin.is_running,
                    "events_sent": stats.events_sent,
                    "last_poll_time": stats.last_poll_time.isoformat() if stats.last_poll_time else None,
                    "last_error": stats.last_error,
                    "active_items": stats.active_items,
                    "source_stats": stats.source_stats,
                }
            )

        return {
            "tak_connected": self._connected,
            "tak_url": self._tak_config.get("cot_url", ""),
            "tx_queue_size": self._tx_queue.qsize() if self._tx_queue else 0,
            "connect_error": self._connect_error,
            "enablements": enablements_status,
            "server_time": datetime.utcnow().isoformat(),
        }

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tx_queue(self) -> Optional[asyncio.Queue]:
        return self._tx_queue


# Module-level singleton — imported by routes and lifespan
runtime_manager = RuntimeManager()

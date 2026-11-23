"""
RuntimeManager — central coordinator for the TAK connection and all enablement workers.

Design notes:
  - We do NOT call clitool.run() because it uses asyncio.wait(FIRST_COMPLETED) and
    returns the moment any task finishes. Instead:
      1. clitool.setup()      — creates TXWorker + RXWorker, stores in clitool.tasks
      2. clitool.run_tasks()  — schedules them via asyncio.ensure_future()
      3. Enablement plugins receive clitool.tx_queue directly and push CoT bytes to it
      4. disconnect_tak() cancels all running_tasks explicitly
  - Because pytak never observes its own worker futures, a dead TX worker (SSL alert,
    dropped socket, rejected client cert) is silent: the tx_queue fills and stays full.
    _supervise() watches those futures, flips the connection state, and reconnects.
  - Module-level singleton `runtime_manager` is imported by FastAPI routes and lifespan.
"""

import asyncio
import logging
from configparser import ConfigParser
from datetime import UTC, datetime

import pytak

from app.enablements.base import EnablementPlugin
from app.enablements.registry import get_plugin_class

log = logging.getLogger(__name__)

# Reconnect backoff in seconds; the last value repeats for as long as it takes.
RECONNECT_BACKOFF = (5, 10, 20, 40, 60)


class RuntimeManager:
    def __init__(self) -> None:
        self._clitool: pytak.CLITool | None = None
        self._tx_queue: asyncio.Queue | None = None
        self._connected: bool = False
        self._tak_config: dict = {}
        self._connect_error: str | None = None

        # enablement_id (DB row id) -> plugin instance
        self._active_enablements: dict[int, EnablementPlugin] = {}
        # enablement_id -> (type_id, config), kept so a reconnect can rebuild
        # every plugin against the new tx_queue
        self._active_configs: dict[int, tuple[str, dict]] = {}

        self._supervisor: asyncio.Task | None = None
        self._shutting_down: bool = False

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
        if self._connected or self._supervisor:
            await self.disconnect_tak()

        self._shutting_down = False
        await self._open_connection(tak_config)
        self._supervisor = asyncio.ensure_future(self._supervise())

    async def _open_connection(self, tak_config: dict) -> None:
        """Build the pytak CLITool and schedule its TX/RX workers."""
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
            clitool = pytak.CLITool(cp["tak"])
            await clitool.setup()
            clitool.run_tasks()  # schedules TX + RX workers as asyncio futures
        except Exception as exc:
            self._connect_error = str(exc)
            self._connected = False
            self._clitool = None
            self._tx_queue = None
            log.error("Failed to connect to TAK server: %s", exc)
            raise

        self._clitool = clitool
        self._tx_queue = clitool.tx_queue
        self._connected = True
        self._connect_error = None
        self._tak_config = tak_config
        log.info("Connected to TAK server: %s", tak_config.get("cot_url"))

    async def disconnect_tak(self) -> None:
        """Stop all enablements and close the TAK connection."""
        self._shutting_down = True

        if self._supervisor:
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
            self._supervisor = None

        # Stop workers first so they don't try to enqueue after queue is gone
        for eid in list(self._active_enablements.keys()):
            await self.stop_enablement(eid)

        await self._teardown_clitool()
        self._connected = False
        log.info("Disconnected from TAK server")

    async def _teardown_clitool(self) -> None:
        """Cancel pytak's TX/RX futures and drop the connection objects."""
        if self._clitool:
            running = list(getattr(self._clitool, "running_tasks", []))
            for task in running:
                task.cancel()
            if running:
                await asyncio.gather(*running, return_exceptions=True)

        self._clitool = None
        self._tx_queue = None

    # ------------------------------------------------------------------
    # Worker supervision + reconnect
    # ------------------------------------------------------------------

    async def _supervise(self) -> None:
        """Watch pytak's TX/RX futures; a dead worker means CoT stops flowing.

        pytak schedules its workers with ensure_future and never awaits them, so a
        failure (rejected client cert, TLS alert, dropped socket) leaves the future
        holding an unobserved exception while `tak_connected` still reads true and
        the tx_queue silently fills.
        """
        while not self._shutting_down:
            tasks = list(getattr(self._clitool, "running_tasks", []))
            if not tasks:
                await asyncio.sleep(1.0)
                continue

            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if self._shutting_down:
                return

            reason = self._describe_failure(done)
            log.error("TAK connection lost — %s", reason)
            self._connected = False
            self._connect_error = reason
            await self._teardown_clitool()

            if not await self._reconnect():
                return

    @staticmethod
    def _describe_failure(done: set) -> str:
        """Turn finished worker futures into a message worth showing an operator."""
        parts = []
        for task in done:
            worker = getattr(task, "_pytak_worker", None)
            name = worker.__class__.__name__ if worker is not None else "worker"
            if task.cancelled():
                parts.append(f"{name} cancelled")
                continue
            exc = task.exception()
            parts.append(f"{name} failed: {type(exc).__name__}: {exc}" if exc else f"{name} exited")
        return "; ".join(parts) or "TAK worker exited"

    async def _reconnect(self) -> bool:
        """Reconnect with backoff, then rebuild every running enablement.

        Returns False only when shutting down.
        """
        attempt = 0
        while not self._shutting_down:
            delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            await asyncio.sleep(delay)
            if self._shutting_down:
                return False
            try:
                await self._open_connection(self._tak_config)
            except Exception as exc:
                log.warning("Reconnect attempt %d failed: %s", attempt, exc)
                continue
            log.info("Reconnected to TAK server after %d attempt(s)", attempt)
            await self._restart_enablements()
            return True
        return False

    async def _restart_enablements(self) -> None:
        """Re-point every running plugin at the new tx_queue."""
        for eid, (type_id, config) in list(self._active_configs.items()):
            plugin = self._active_enablements.pop(eid, None)
            if plugin:
                await plugin.stop()
            try:
                await self.start_enablement(eid, type_id, config)
            except Exception as exc:
                log.error("Reconnect: failed to restart enablement %d: %s", eid, exc)

    # ------------------------------------------------------------------
    # Enablement lifecycle
    # ------------------------------------------------------------------

    async def start_enablement(self, enablement_id: int, type_id: str, config: dict) -> None:
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
        # Converters stamp COT_HOST_ID into every event; default it from the
        # TAK config so the operator's setting actually reaches the wire.
        config = {
            "COT_HOST_ID": self._tak_config.get("cot_host_id") or pytak.DEFAULT_HOST_ID,
            **config,
        }
        plugin = plugin_cls(
            enablement_id=enablement_id,
            config=config,
            tx_queue=self._tx_queue,
        )
        await plugin.start()
        self._active_enablements[enablement_id] = plugin
        self._active_configs[enablement_id] = (type_id, config)
        log.info("Started enablement %d (%s: %s)", enablement_id, type_id, config.get("name"))

    async def stop_enablement(self, enablement_id: int) -> None:
        """Stop and remove a running enablement plugin."""
        plugin = self._active_enablements.pop(enablement_id, None)
        self._active_configs.pop(enablement_id, None)
        if plugin:
            await plugin.stop()
            log.info("Stopped enablement %d", enablement_id)

    async def restart_enablement(self, enablement_id: int, new_config: dict) -> None:
        """Update config and restart an active enablement."""
        plugin = self._active_enablements.get(enablement_id)
        if plugin:
            await plugin.on_config_updated(new_config)
            type_id, _ = self._active_configs.get(enablement_id, (plugin.TYPE_ID, {}))
            self._active_configs[enablement_id] = (type_id, new_config)
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
                    "events_dropped": stats.events_dropped,
                    "last_poll_time": stats.last_poll_time.isoformat()
                    if stats.last_poll_time
                    else None,
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
            "server_time": datetime.now(UTC).isoformat(),
        }

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tx_queue(self) -> asyncio.Queue | None:
        return self._tx_queue


# Module-level singleton — imported by routes and lifespan
runtime_manager = RuntimeManager()

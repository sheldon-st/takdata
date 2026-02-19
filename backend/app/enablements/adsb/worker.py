"""
ADS-B polling worker.
Adapted from send.py:MySerializer.

Key changes from send.py:
  - Accepts list of source dicts (from DB) instead of DataSource objects
  - Pushes directly to the shared asyncio.Queue (not via pytak.QueueWorker)
  - Tracks EnablementStats for status API
  - Does not manage its own aiohttp session (session provided by plugin)
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import aiohttp

from app.enablements.base import EnablementStats
from app.enablements.adsb.converter import adsb_to_cot
from app.enablements.adsb.fetcher import fetch_adsb_aircraft

log = logging.getLogger(__name__)


class AdsbWorker:
    """
    Polls one or more ADS-B sources, deduplicates aircraft, converts to CoT,
    and enqueues CoT bytes onto the shared TAK TX queue.
    """

    def __init__(
        self,
        tx_queue: asyncio.Queue,
        config: dict,
        sources: list[dict],
    ) -> None:
        self.tx_queue = tx_queue
        self.config = config
        self.sources = sources  # list of source dicts from DB
        self._cache_ttl = 60
        self._seen_aircraft: dict[str, tuple[float, dict]] = {}
        self._api_semaphore = asyncio.Semaphore(10)
        self._stats = EnablementStats()
        self._source_stats: dict[str, dict] = {
            s["name"]: {"last_poll": None, "aircraft_count": 0}
            for s in sources
        }

    def get_stats(self) -> EnablementStats:
        self._stats.source_stats = self._source_stats
        return self._stats

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start independent polling loops for each source."""
        if not self.sources:
            log.warning("AdsbWorker started with no sources configured")
            return

        default_interval = float(self.config.get("SLEEP_INTERVAL", 5))

        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            tasks = [
                self._poll_source_loop(session, source, default_interval)
                for source in self.sources
                if source.get("enabled", True)
            ]
            if not tasks:
                log.warning("AdsbWorker: all sources are disabled")
                return
            await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    # Per-source polling
    # ------------------------------------------------------------------

    async def _poll_source_loop(
        self,
        session: aiohttp.ClientSession,
        source: dict,
        default_interval: float,
    ) -> None:
        interval = source.get("sleep_interval") or default_interval
        name = source.get("name", "unknown")
        log.info("[%s] Polling every %ss", name, interval)

        while True:
            try:
                async with self._api_semaphore:
                    await self._fetch_and_process(session, source)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("[%s] Poll error: %s", name, exc)
                self._stats.last_error = str(exc)
            await asyncio.sleep(interval)

    async def _fetch_and_process(
        self,
        session: aiohttp.ClientSession,
        source: dict,
    ) -> None:
        name = source.get("name", "unknown")
        aircraft_data = await fetch_adsb_aircraft(session, source)

        # Filter to aircraft with position data
        with_location = []
        for ac in aircraft_data:
            last_pos = ac.get("lastPosition")
            if last_pos:
                ac = {**ac, **last_pos}
            if ac.get("lat") is not None and ac.get("lon") is not None:
                with_location.append(ac)

        # Update source-level stats
        self._source_stats.setdefault(name, {})
        self._source_stats[name]["last_poll"] = datetime.utcnow().isoformat()
        self._source_stats[name]["aircraft_count"] = len(with_location)
        self._stats.last_poll_time = datetime.utcnow()

        # Deduplicate and process
        to_process = self._deduplicate(with_location, name)
        log.info("[%s] %d/%d aircraft new/updated", name, len(to_process), len(with_location))

        await self._batch_to_cot(to_process, name)

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _deduplicate(self, aircraft_list: list[dict], source_name: str) -> list[dict]:
        """Return aircraft that are new or have updated data."""
        now = time.time()
        to_process: list[dict] = []

        # Periodic cleanup of stale cache entries
        if len(self._seen_aircraft) > 1000:
            cutoff = now - self._cache_ttl
            self._seen_aircraft = {
                k: v for k, v in self._seen_aircraft.items() if v[0] > cutoff
            }

        for ac in aircraft_list:
            icao = str(ac.get("hex") or ac.get("icao", "")).strip().upper()
            if not icao:
                continue

            cached = self._seen_aircraft.get(icao)
            if cached:
                _, old_data = cached
                if (ac.get("messages", 0) > old_data.get("messages", 0)
                        or ac.get("lat") != old_data.get("lat")):
                    self._seen_aircraft[icao] = (now, ac)
                    to_process.append(ac)
            else:
                self._seen_aircraft[icao] = (now, ac)
                to_process.append(ac)

        # Keep active_items updated (total unique aircraft seen recently)
        self._stats.active_items = len(self._seen_aircraft)
        return to_process

    # ------------------------------------------------------------------
    # CoT conversion + queue push
    # ------------------------------------------------------------------

    async def _batch_to_cot(self, aircraft_list: list[dict], source_name: str) -> None:
        if not aircraft_list:
            return

        cot_config = {
            **self.config,
            "FEED_URL": source_name,
        }

        async def _process_one(ac: dict) -> None:
            try:
                cot_bytes = adsb_to_cot(ac, cot_config)
                if cot_bytes:
                    await self.tx_queue.put(cot_bytes)
                    self._stats.events_sent += 1
            except asyncio.QueueFull:
                log.warning("TX queue full — dropping CoT event for %s", ac.get("hex"))
            except Exception as exc:
                log.error("[%s] CoT conversion error for %s: %s",
                          source_name, ac.get("hex", "?"), exc)

        batch_size = 50
        for i in range(0, len(aircraft_list), batch_size):
            batch = aircraft_list[i : i + batch_size]
            await asyncio.gather(*[_process_one(a) for a in batch], return_exceptions=True)

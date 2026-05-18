"""Synthetic CoT worker — emits fabricated events at a target rate."""

import asyncio
import logging
import random
from datetime import datetime, timezone

from app.enablements.base import EnablementStats
from app.enablements.synthetic.generator import synthetic_to_cot

log = logging.getLogger(__name__)

# Default spawn bbox when none configured (continental US-ish).
DEFAULT_BBOX = (24.0, 49.0, -125.0, -67.0)  # min_lat, max_lat, min_lon, max_lon

JITTER_DEG = 0.0005  # ~50m per tick


class SyntheticWorker:
    def __init__(self, enablement_id: int, tx_queue: asyncio.Queue, config: dict):
        self.enablement_id = enablement_id
        self.tx_queue = tx_queue
        self.config = config
        self.stats = EnablementStats()

        self.entity_count = max(1, int(config.get("entity_count") or 100))
        self.target_rate_hz = max(0.1, float(config.get("target_rate_hz") or 10.0))

        bbox = self._resolve_bbox(config)
        rng = random.Random(f"synthetic-{enablement_id}")
        self.entities = [self._spawn(i, bbox, rng) for i in range(self.entity_count)]
        self.stats.active_items = self.entity_count

    @staticmethod
    def _resolve_bbox(config: dict) -> tuple[float, float, float, float]:
        min_lat = config.get("geo_filter_min_lat")
        max_lat = config.get("geo_filter_max_lat")
        min_lon = config.get("geo_filter_min_lon")
        max_lon = config.get("geo_filter_max_lon")
        if None in (min_lat, max_lat, min_lon, max_lon):
            return DEFAULT_BBOX
        return (float(min_lat), float(max_lat), float(min_lon), float(max_lon))

    def _spawn(self, index: int, bbox: tuple[float, float, float, float], rng: random.Random) -> dict:
        min_lat, max_lat, min_lon, max_lon = bbox
        return {
            "uid": f"SYN-{self.enablement_id}-{index:06d}",
            "callsign": f"SYN{index:05d}",
            "lat": rng.uniform(min_lat, max_lat),
            "lon": rng.uniform(min_lon, max_lon),
            "course": rng.uniform(0, 360),
            "speed": rng.uniform(0, 30),
            "cot_type": "a-f-G",
        }

    def get_stats(self) -> EnablementStats:
        return self.stats

    async def run(self) -> None:
        interval = 1.0 / self.target_rate_hz
        # Batch sleeps when rate is high to avoid asyncio.sleep overhead per event.
        batch = max(1, int(self.target_rate_hz // 50)) if self.target_rate_hz > 50 else 1
        sleep_per_batch = interval * batch
        rng = random.Random(f"synthetic-tick-{self.enablement_id}")
        i = 0
        try:
            while True:
                for _ in range(batch):
                    entity = self.entities[i % self.entity_count]
                    entity["lat"] += rng.uniform(-JITTER_DEG, JITTER_DEG)
                    entity["lon"] += rng.uniform(-JITTER_DEG, JITTER_DEG)
                    try:
                        cot_bytes = synthetic_to_cot(entity, self.config)
                        await self.tx_queue.put(cot_bytes)
                        self.stats.events_sent += 1
                    except Exception as exc:
                        self.stats.last_error = str(exc)
                        log.exception("synthetic emit failed")
                    i += 1
                self.stats.last_poll_time = datetime.now(timezone.utc)
                await asyncio.sleep(sleep_per_batch)
        except asyncio.CancelledError:
            raise

"""
Synthetic CoT worker — emits fabricated events at a configurable workload.

Workload model (three orthogonal knobs):
  N = feature_count          — population of unique UIDs
  U = updates_per_second     — tick rate in Hz
  K = features_per_update    — features touched per tick
  strategy                   — round_robin | random | zipf

Derived:
  aggregate event rate = U * K events/sec
  per-feature refresh  = N / (U * K) sec  (under round_robin; mean under random)
"""

import asyncio
import logging
import math
import random
from datetime import datetime, timezone

from app.enablements.base import EnablementStats
from app.enablements.synthetic.generator import synthetic_to_cot

log = logging.getLogger(__name__)

DEFAULT_BBOX = (24.0, 49.0, -125.0, -67.0)  # CONUS
JITTER_DEG = 0.0005
ZIPF_EXPONENT = 1.0


class SyntheticWorker:
    def __init__(self, enablement_id: int, tx_queue: asyncio.Queue, config: dict):
        self.enablement_id = enablement_id
        self.tx_queue = tx_queue
        self.config = config
        self.stats = EnablementStats()

        self.N = max(1, int(config.get("feature_count") or 100))
        self.U = max(0.01, float(config.get("updates_per_second") or 10.0))
        self.K = max(1, int(config.get("features_per_update") or 1))
        # Clamp K to N — emitting same UID twice in a tick is wasted work.
        self.K = min(self.K, self.N)
        self.strategy = (config.get("selection_strategy") or "round_robin").lower()
        if self.strategy not in {"round_robin", "random", "zipf"}:
            log.warning("Unknown selection_strategy=%r, defaulting to round_robin", self.strategy)
            self.strategy = "round_robin"

        bbox = self._resolve_bbox(config)
        self.rng = random.Random(f"synthetic-{enablement_id}")
        self.features = [self._spawn(i, bbox, self.rng) for i in range(self.N)]
        self.stats.active_items = self.N

        # Precompute Zipf weights once (sum(1/i^s) for i=1..N)
        self._zipf_weights: list[float] = []
        if self.strategy == "zipf":
            self._zipf_weights = [1.0 / math.pow(i + 1, ZIPF_EXPONENT) for i in range(self.N)]

        self._cursor = 0  # round-robin position

    @staticmethod
    def _resolve_bbox(config: dict) -> tuple[float, float, float, float]:
        min_lat = config.get("geo_filter_min_lat")
        max_lat = config.get("geo_filter_max_lat")
        min_lon = config.get("geo_filter_min_lon")
        max_lon = config.get("geo_filter_max_lon")
        if None in (min_lat, max_lat, min_lon, max_lon):
            return DEFAULT_BBOX
        return (float(min_lat), float(max_lat), float(min_lon), float(max_lon))

    def _spawn(self, index: int, bbox, rng: random.Random) -> dict:
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

    def _pick_indices(self) -> list[int]:
        if self.strategy == "round_robin":
            idx = [(self._cursor + j) % self.N for j in range(self.K)]
            self._cursor = (self._cursor + self.K) % self.N
            return idx
        if self.strategy == "random":
            # sample without replacement within a tick
            return self.rng.sample(range(self.N), self.K)
        # zipf — weighted choices (with replacement; population-skew is the point)
        return self.rng.choices(range(self.N), weights=self._zipf_weights, k=self.K)

    def get_stats(self) -> EnablementStats:
        return self.stats

    async def run(self) -> None:
        interval = 1.0 / self.U
        log.info(
            "Synthetic harness: N=%d U=%.2fHz K=%d strategy=%s "
            "→ %.1f events/s, refresh ~%.2fs",
            self.N, self.U, self.K, self.strategy,
            self.U * self.K, self.N / (self.U * self.K),
        )
        try:
            while True:
                tick_start = asyncio.get_event_loop().time()
                for i in self._pick_indices():
                    feature = self.features[i]
                    feature["lat"] += self.rng.uniform(-JITTER_DEG, JITTER_DEG)
                    feature["lon"] += self.rng.uniform(-JITTER_DEG, JITTER_DEG)
                    try:
                        cot_bytes = synthetic_to_cot(feature, self.config)
                        await self.tx_queue.put(cot_bytes)
                        self.stats.events_sent += 1
                    except Exception as exc:
                        self.stats.last_error = str(exc)
                        log.exception("synthetic emit failed")
                self.stats.last_poll_time = datetime.now(timezone.utc)
                # Sleep remainder of the tick to hold cadence even when K is large.
                elapsed = asyncio.get_event_loop().time() - tick_start
                await asyncio.sleep(max(0.0, interval - elapsed))
        except asyncio.CancelledError:
            raise

"""
AIS WebSocket worker for aisstream.io.

Maintains one persistent WebSocket connection per source.  Each source is
identified by its API key (stored in the `endpoint` field) and geographic
bounding boxes derived from lat/lon/distance or the enablement geo filter.

Message flow:
  aisstream.io WS → _handle_message → _emit_position → ais_to_cot → tx_queue
  ShipStaticData messages are cached by MMSI and merged into position events.
"""

import asyncio
import json
import logging
import math
import time
from datetime import datetime

import websockets

from app.enablements.base import EnablementStats
from app.enablements.ais.converter import ais_to_cot

log = logging.getLogger(__name__)

_POSITION_MESSAGE_TYPES = frozenset(
    {
        "PositionReport",
        "StandardClassBPositionReport",
        "ExtendedClassBPositionReport",
        "LongRangeAisBroadcastMessage",
    }
)


def _bbox_from_center(lat: float, lon: float, distance_km: float) -> list:
    """
    Convert a center point + radius to a bounding box.
    Returns [[min_lat, min_lon], [max_lat, max_lon]].
    """
    lat_delta = distance_km / 111.0
    lon_delta = distance_km / (111.0 * math.cos(math.radians(lat)))
    return [
        [lat - lat_delta, lon - lon_delta],
        [lat + lat_delta, lon + lon_delta],
    ]


class AisWorker:
    """
    Subscribes to aisstream.io WebSocket, processes AIS messages, converts
    vessel positions to CoT, and enqueues them onto the shared TAK TX queue.
    """

    _RECONNECT_BASE = 5.0
    _RECONNECT_MAX = 60.0
    # How often (seconds) to re-emit a CoT for the same vessel.
    # Ships send position reports every 2-10 s; throttle here to avoid
    # flooding TAK with redundant events.
    _DEFAULT_EMIT_INTERVAL = 30.0

    def __init__(
        self,
        tx_queue: asyncio.Queue,
        config: dict,
        sources: list[dict],
    ) -> None:
        self.tx_queue = tx_queue
        self.config = config
        self.sources = sources

        self._stats = EnablementStats()
        self._source_stats: dict[str, dict] = {
            s["name"]: {"last_message": None, "vessel_count": 0} for s in sources
        }
        # MMSI → merged static data dict (name, callsign, type, …)
        self._static_data: dict[str, dict] = {}
        # MMSI → monotonic timestamp of last emitted CoT
        self._last_sent: dict[str, float] = {}
        # MMSI → last seen timestamp (for active_items count)
        self._active_vessels: dict[str, float] = {}

    def get_stats(self) -> EnablementStats:
        now = time.time()
        cutoff = now - self._DEFAULT_EMIT_INTERVAL * 10
        self._active_vessels = {
            k: v for k, v in self._active_vessels.items() if v > cutoff
        }
        self._stats.active_items = len(self._active_vessels)
        self._stats.source_stats = self._source_stats
        return self._stats

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start one connection loop per enabled source."""
        enabled = [s for s in self.sources if s.get("enabled", True)]
        if not enabled:
            log.warning("AisWorker: no enabled sources")
            return
        await asyncio.gather(*[self._connect_loop(s) for s in enabled])

    # ------------------------------------------------------------------
    # Per-source connection loop (reconnects with exponential back-off)
    # ------------------------------------------------------------------

    async def _connect_loop(self, source: dict) -> None:
        name = source.get("name", "unknown")
        delay = self._RECONNECT_BASE

        while True:
            try:
                await self._stream_source(source)
                log.warning(
                    "[%s] Stream ended cleanly, reconnecting in %.0fs", name, delay
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("[%s] Connection error: %s", name, exc)
                self._stats.last_error = str(exc)
                self._source_stats.setdefault(name, {})["last_error"] = str(exc)
                self._source_stats[name]["connected"] = False

            await asyncio.sleep(delay)
            delay = min(delay * 2, self._RECONNECT_MAX)

    # ------------------------------------------------------------------
    # WebSocket connection (one per source)
    # ------------------------------------------------------------------

    async def _stream_source(self, source: dict) -> None:
        name = source.get("name", "unknown")
        ws_url = source.get("base_url") or "wss://stream.aisstream.io/v0/stream"
        api_key = "f199a8a73fc54f221e6af34d45d9129b58c26594"  # (source.get("endpoint") or "").strip()

        if not api_key:
            log.error("[%s] No API key — set it in the source 'endpoint' field", name)
            await asyncio.sleep(30)
            return

        bboxes = self._build_bounding_boxes(source)
        if not bboxes:
            log.error(
                "[%s] No bounding boxes — configure lat/lon/distance on the source "
                "or a geo filter on the enablement",
                name,
            )
            await asyncio.sleep(30)
            return

        subscribe_msg = {
            "APIKey": api_key,
            "BoundingBoxes": bboxes,
            "FilterMessageTypes": sorted(_POSITION_MESSAGE_TYPES | {"ShipStaticData"}),
        }

        log.info("[%s] Connecting to %s with %d bbox(es)", name, ws_url, len(bboxes))

        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=10,
            max_size=2**20,  # 1 MB — aisstream frames are small, but be safe
        ) as ws:
            await ws.send(json.dumps(subscribe_msg))
            log.info("[%s] Subscribed to aisstream.io", name)
            self._source_stats.setdefault(name, {})["connected"] = True

            async for raw in ws:
                await self._handle_message(raw, source, name)

    # ------------------------------------------------------------------
    # Bounding box helpers
    # ------------------------------------------------------------------

    def _build_bounding_boxes(self, source: dict) -> list:
        """
        Priority: source lat/lon/distance → enablement geo_filter.
        Returns a list of [[min_lat, min_lon], [max_lat, max_lon]] boxes.
        """
        lat = source.get("lat")
        lon = source.get("lon")
        distance = source.get("distance")

        if lat is not None and lon is not None and distance:
            return [_bbox_from_center(float(lat), float(lon), float(distance))]

        mn_lat = self.config.get("geo_filter_min_lat")
        mx_lat = self.config.get("geo_filter_max_lat")
        mn_lon = self.config.get("geo_filter_min_lon")
        mx_lon = self.config.get("geo_filter_max_lon")

        if all(v is not None for v in (mn_lat, mx_lat, mn_lon, mx_lon)):
            return [
                [
                    [float(mn_lat), float(mn_lon)],
                    [float(mx_lat), float(mx_lon)],
                ]
            ]

        return []

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _handle_message(self, data: str, source: dict, source_name: str) -> None:
        try:
            msg = json.loads(data)
        except json.JSONDecodeError as exc:
            log.debug("[%s] JSON parse error: %s", source_name, exc)
            return

        message_type: str = msg.get("MessageType", "")
        message: dict = msg.get("Message", {})
        meta: dict = msg.get("MetaData", {})

        log.debug("[%s] %s MMSI=%s", source_name, message_type, meta.get("MMSI"))

        mmsi = str(meta.get("MMSI", "")).strip()
        if not mmsi or mmsi == "0":
            return

        self._active_vessels[mmsi] = time.time()

        if message_type == "ShipStaticData":
            self._cache_static_data(mmsi, message.get("ShipStaticData", {}), meta)
        elif message_type in _POSITION_MESSAGE_TYPES:
            await self._emit_position(
                mmsi,
                message.get(message_type, {}),
                meta,
                source,
                source_name,
            )

    def _cache_static_data(self, mmsi: str, static: dict, meta: dict) -> None:
        """Store vessel static data for later merging into position events."""
        self._static_data[mmsi] = {
            "ShipName": static.get("Name", meta.get("ShipName", "")).strip(),
            "CallSign": static.get("CallSign", "").strip(),
            "ShipType": int(static.get("Type", 0) or 0),
            "Destination": static.get("Destination", "").strip(),
            "_cached_at": time.time(),
        }
        log.debug(
            "Cached static data for MMSI %s: %s",
            mmsi,
            self._static_data[mmsi].get("ShipName"),
        )

    async def _emit_position(
        self,
        mmsi: str,
        position: dict,
        meta: dict,
        source: dict,
        source_name: str,
    ) -> None:
        """Throttle, build vessel dict, convert to CoT, and enqueue."""
        now = time.time()
        emit_interval = float(
            source.get("sleep_interval") or self._DEFAULT_EMIT_INTERVAL
        )

        if now - self._last_sent.get(mmsi, 0) < emit_interval:
            return

        lat = (
            position.get("Latitude")
            if position.get("Latitude") is not None
            else meta.get("Latitude")
        )
        lon = (
            position.get("Longitude")
            if position.get("Longitude") is not None
            else meta.get("Longitude")
        )
        if lat is None or lon is None:
            return

        static = self._static_data.get(mmsi, {})
        vessel = {
            "MMSI": mmsi,
            "Latitude": lat,
            "Longitude": lon,
            "Sog": position.get("Sog", 0.0),
            "Cog": position.get("Cog", 0.0),
            "TrueHeading": position.get("TrueHeading", 511),
            "NavigationalStatus": position.get("NavigationalStatus", 15),
            "ShipName": static.get("ShipName") or meta.get("ShipName", ""),
            "CallSign": static.get("CallSign", ""),
            "ShipType": static.get("ShipType", 0),
            "Destination": static.get("Destination", ""),
        }

        cot_config = {**self.config, "FEED_URL": source_name}

        try:
            cot_bytes = ais_to_cot(vessel, cot_config)
            if cot_bytes:
                await self.tx_queue.put(cot_bytes)
                self._stats.events_sent += 1
                self._last_sent[mmsi] = now
                self._stats.last_poll_time = datetime.utcnow()

                src = self._source_stats.setdefault(source_name, {})
                src["last_message"] = datetime.utcnow().isoformat()
                src["vessel_count"] = len(self._active_vessels)

        except asyncio.QueueFull:
            log.warning("TX queue full — dropping CoT for MMSI %s", mmsi)
        except Exception as exc:
            log.error("[%s] CoT error for MMSI %s: %s", source_name, mmsi, exc)
            self._stats.last_error = str(exc)

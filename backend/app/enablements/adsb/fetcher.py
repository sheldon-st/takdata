"""
ADS-B data fetching logic.
Adapted from send.py:fetch_adsb_data_from_source().
"""

import logging
import random
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-GPC": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def _build_url(source: dict) -> str:
    """Build the request URL from a source config dict."""
    base_url = source["base_url"].rstrip("/")
    endpoint = source.get("endpoint", "geo").lower()

    if endpoint == "mil":
        return f"{base_url}/mil"

    lat = source.get("lat", "40.7128")
    lon = source.get("lon", "-74.0060")
    dist = source.get("distance", "25")

    if endpoint == "point":
        return f"{base_url}/point/{lat}/{lon}/{dist}"

    # geo (default)
    return f"{base_url}/lat/{lat}/lon/{lon}/dist/{dist}"


async def fetch_adsb_aircraft(
    session: aiohttp.ClientSession,
    source: dict,
) -> list[dict]:
    """
    Fetch aircraft list from one ADS-B source.

    source is a plain dict with keys: name, base_url, endpoint,
    lat, lon, distance (and optionally others).

    Returns list of aircraft dicts (may be empty on error).
    Supports both opendata.adsb.fi ('aircraft') and api.adsb.lol ('ac') formats.
    """
    name = source.get("name", "unknown")
    url = _build_url(source)

    headers = {**_HEADERS, "User-Agent": random.choice(USER_AGENTS)}

    try:
        log.debug("[%s] GET %s", name, url)
        async with session.get(url, headers=headers) as resp:
            log.debug("[%s] Status %d", name, resp.status)
            if resp.status == 200:
                data = await resp.json()
                aircraft = data.get("aircraft") or data.get("ac", [])
                log.info("[%s] Fetched %d aircraft", name, len(aircraft))
                return aircraft
            else:
                body = await resp.text()
                log.warning("[%s] HTTP %d — %s", name, resp.status, body[:200])
                return []
    except Exception as exc:
        log.error("[%s] Fetch error: %s", name, exc)
        return []

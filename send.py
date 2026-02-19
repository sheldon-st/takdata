#!/usr/bin/env python3

import asyncio
import xml.etree.ElementTree as ET
import os
import logging
import random
from typing import Optional, Union

from configparser import ConfigParser, SectionProxy

import pytak
import aiohttp
import aircot

# Set up logging
Logger = logging.getLogger(__name__)
Debug = bool(os.getenv("DEBUG", "False").lower() in ["true", "1", "yes"])

# List of realistic browser user agents to rotate through
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
]

class DataSource:
    """Represents a single ADS-B data source configuration."""
    def __init__(self, name, base_url, endpoint, sleep_interval=None, **kwargs):
        self.name = name
        self.base_url = base_url
        self.endpoint = endpoint
        self.sleep_interval = sleep_interval  # Per-source polling interval in seconds
        self.params = kwargs
        self.last_poll_time = 0  # Track when this source was last polled

    def __repr__(self):
        interval_str = f", interval={self.sleep_interval}s" if self.sleep_interval else ""
        return f"DataSource({self.name}, {self.base_url}, {self.endpoint}{interval_str})"


class MySerializer(pytak.QueueWorker):
    """
    Defines how you process or generate your Cursor on Target Events.
    From there it adds the CoT Events to a queue for TX to a COT_URL.
    Supports multiple concurrent data sources with deduplication.
    """

    def __init__(self, queue, config, data_sources=None):
        super().__init__(queue, config)
        self.config = config
        self.data_sources = data_sources or []
        self.seen_aircraft = {}  # Cache for deduplication: {icao_hex: (timestamp, aircraft_data)}
        self.cache_ttl = 60  # seconds to keep aircraft in cache
        # Semaphore to limit concurrent API requests (prevents overwhelming the API)
        self.api_semaphore = asyncio.Semaphore(10)  # Max 10 concurrent API requests

    async def handle_data(self, data):
        """Handle pre-CoT data, serialize to CoT Event, then puts on queue."""
        event = data
        await self.put_queue(event)

    def _deduplicate_aircraft(self, aircraft_list, source_name):
        """
        Deduplicate aircraft across multiple sources.
        Returns list of aircraft to process (new or updated).
        Optimized for performance with batch operations.
        """
        import time
        current_time = time.time()
        new_or_updated = []

        # Batch cleanup: remove expired entries (done once per call instead of per-aircraft)
        if len(self.seen_aircraft) > 1000:  # Only cleanup if cache is getting large
            expired_threshold = current_time - self.cache_ttl
            self.seen_aircraft = {
                k: v for k, v in self.seen_aircraft.items()
                if v[0] > expired_threshold
            }

        # Pre-extract identifiers to avoid repeated dict lookups
        for aircraft in aircraft_list:
            # Get aircraft identifier - optimized with single lookup
            icao_hex = str(aircraft.get('hex') or aircraft.get('icao', '')).strip().upper()
            if not icao_hex:
                continue

            # Check if we've seen this aircraft recently
            cached = self.seen_aircraft.get(icao_hex)
            if cached:
                _, old_data = cached
                # Update if this data is newer (has more messages or different position)
                old_msgs = old_data.get('messages', 0)
                new_msgs = aircraft.get('messages', 0)
                old_lat = old_data.get('lat')
                new_lat = aircraft.get('lat')

                # Only update if truly changed (avoid unnecessary processing)
                if new_msgs > old_msgs or new_lat != old_lat:
                    Logger.debug("Updating %s from %s (msgs: %d -> %d)",
                               icao_hex, source_name, old_msgs, new_msgs)
                    self.seen_aircraft[icao_hex] = (current_time, aircraft)
                    new_or_updated.append(aircraft)
            else:
                Logger.debug("New aircraft %s from %s", icao_hex, source_name)
                self.seen_aircraft[icao_hex] = (current_time, aircraft)
                new_or_updated.append(aircraft)

        return new_or_updated

    async def _batch_process_aircraft(self, aircraft_list, source_name):
        """
        Batch process aircraft to CoT events for improved performance.
        Processes multiple aircraft concurrently using asyncio.
        """
        if not aircraft_list:
            return

        async def process_single_aircraft(aircraft):
            """Process a single aircraft to CoT event."""
            try:
                # Add source info to config for this aircraft
                aircraft_config = dict(self.config)
                aircraft_config['FEED_URL'] = f"{source_name}"

                cot_event = aircraft_to_cot(aircraft, aircraft_config)
                if cot_event:
                    await self.handle_data(cot_event)
                else:
                    Logger.debug("[%s] Skipped aircraft: %s",
                               source_name, aircraft.get('hex', 'unknown'))
            except Exception as e:
                Logger.error("[%s] Error processing aircraft %s: %s",
                           source_name, aircraft.get('hex', 'unknown'), e)

        # Process aircraft in batches to avoid overwhelming the queue
        batch_size = 50  # Process 50 aircraft at a time
        for i in range(0, len(aircraft_list), batch_size):
            batch = aircraft_list[i:i + batch_size]
            # Process batch concurrently
            await asyncio.gather(*[process_single_aircraft(a) for a in batch], return_exceptions=True)

    async def fetch_from_source(self, session, source):
        """Fetch data from a single source with rate limiting."""
        # Use semaphore to limit concurrent API requests
        async with self.api_semaphore:
            try:
                aircraft_data = await fetch_adsb_data_from_source(session, source, self.config)
                if aircraft_data:
                    Logger.info("[%s] Fetched %d aircraft", source.name, len(aircraft_data))

                    # Filter out aircraft without location data BEFORE deduplication
                    aircraft_with_location = []
                    for aircraft in aircraft_data:
                        # Handle nested position data if present
                        lastPosition = aircraft.get("lastPosition")
                        if lastPosition:
                            aircraft.update(lastPosition)

                        lat = aircraft.get("lat", aircraft.get("Lat"))
                        lon = aircraft.get("lon", aircraft.get("Lon", aircraft.get("Lng")))

                        if lat is not None and lon is not None:
                            aircraft_with_location.append(aircraft)

                    Logger.info("[%s] %d aircraft have location data", source.name, len(aircraft_with_location))

                    # Deduplicate and process only aircraft with location
                    to_process = self._deduplicate_aircraft(aircraft_with_location, source.name)
                    Logger.info("[%s] Processing %d new/updated aircraft", source.name, len(to_process))

                    # Batch process CoT events for better performance
                    await self._batch_process_aircraft(to_process, source.name)
            except Exception as e:
                Logger.error("[%s] Error fetching/processing data: %s", source.name, e)
                if Debug:
                    import traceback
                    traceback.print_exc()

    async def poll_source_loop(self, session, source, default_interval):
        """Continuously poll a single data source at its configured interval."""
        interval = source.sleep_interval if source.sleep_interval is not None else default_interval
        Logger.info("[%s] Starting polling loop with %s second interval", source.name, interval)

        while True:
            try:
                await self.fetch_from_source(session, source)
            except Exception as e:
                Logger.error("[%s] Error in polling loop: %s", source.name, e)
                if Debug:
                    import traceback
                    traceback.print_exc()

            await asyncio.sleep(interval)

    async def run(self):
        """Run the loop for processing data from multiple sources concurrently with independent polling."""
        if not self.data_sources:
            Logger.error("No data sources configured!")
            return

        default_interval = float(self.config.get("SLEEP_INTERVAL", 3))

        # Optimize connection pooling for better performance
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection limit
            limit_per_host=30,  # Per-host connection limit
            ttl_dns_cache=300,  # Cache DNS for 5 minutes
            enable_cleanup_closed=True  # Clean up closed connections
        )

        # Configure timeout to prevent hanging requests
        timeout = aiohttp.ClientTimeout(
            total=30,  # Total timeout including connection and read
            connect=10,  # Connection timeout
            sock_read=20  # Socket read timeout
        )

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create independent polling tasks for each source
            tasks = [
                self.poll_source_loop(session, source, default_interval)
                for source in self.data_sources
            ]

            # Run all polling loops concurrently
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                Logger.error("Error in main loop: %s", e)
                if Debug:
                    import traceback
                    traceback.print_exc()


async def fetch_adsb_data_from_source(session, source, config=None):
    """Fetch ADS-B data from a specific DataSource."""
    if config is None:
        config = {}

    # Build URL based on endpoint type
    if source.endpoint.lower() == "mil":
        # Military endpoint - no args needed
        url = f"{source.base_url}/mil"
    elif source.endpoint.lower() == "point":
        # Point endpoint for detailed coverage
        lat = source.params.get("lat", "40.7128")
        lon = source.params.get("lon", "-74.0060")
        distance = source.params.get("distance", "15")
        url = f"{source.base_url}/point/{lat}/{lon}/{distance}"
    else:
        # Geographic endpoint - requires lat/lon/distance
        lat = source.params.get("lat", "40.7128")
        lon = source.params.get("lon", "-74.0060")
        distance = source.params.get("distance", "15")
        url = f"{source.base_url}/lat/{lat}/lon/{lon}/dist/{distance}"

    try:
        # Use realistic browser headers to avoid rate limiting
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-GPC': '1',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }

        Logger.info("[%s] Making ADS-B API request to: %s", source.name, url)
        async with session.get(url, headers=headers) as response:
            Logger.info("[%s] Received response - Status: %d", source.name, response.status)

            if response.status == 200:
                data = await response.json()
                # Support both 'aircraft' (opendata.adsb.fi) and 'ac' (api.adsb.lol) formats
                aircraft = data.get('aircraft') or data.get('ac', [])
                Logger.info("[%s] Successfully fetched %d aircraft", source.name, len(aircraft))
                return aircraft
            else:
                response_text = await response.text()
                Logger.warning("[%s] HTTP error %d", source.name, response.status)
                Logger.warning("[%s] Response body: %s", source.name, response_text[:200])
                return []
    except Exception as e:
        Logger.error("[%s] Error fetching ADS-B data: %s", source.name, e)
        if Debug:
            import traceback
            traceback.print_exc()
        return []


async def fetch_adsb_data(session, config=None):
    """Legacy function - fetch ADS-B data from single source configured via config."""
    if config is None:
        config = {}

    base_url = config.get("ADSB_API_URL", "https://opendata.adsb.fi/api/v2")
    endpoint = config.get("ADSB_ENDPOINT", "geo")  # 'geo' or 'mil'

    # Build URL based on endpoint type
    if endpoint.lower() == "mil":
        # Military endpoint - no args needed
        url = f"{base_url}/mil"
    else:
        # Geographic endpoint - requires lat/lon/distance
        lat = config.get("ADSB_LAT", "40.7128")
        lon = config.get("ADSB_LON", "-74.0060")
        distance = config.get("ADSB_DISTANCE", "15")
        url = f"{base_url}/lat/{lat}/lon/{lon}/dist/{distance}"

    try:
        # Use realistic browser headers to avoid rate limiting
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-GPC': '1',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }

        Logger.info("Making ADS-B API request to: %s", url)
        async with session.get(url, headers=headers) as response:
            Logger.info("Received response from %s - Status: %d", url, response.status)

            if response.status == 200:
                data = await response.json()
                # Support both 'aircraft' (opendata.adsb.fi) and 'ac' (api.adsb.lol) formats
                aircraft = data.get('aircraft') or data.get('ac', [])
                Logger.info("Successfully fetched %d aircraft from ADS-B API", len(aircraft))
                return aircraft
            else:
                response_text = await response.text()
                Logger.warning("HTTP error %d fetching ADS-B data from %s", response.status, url)
                Logger.warning("Response body: %s", response_text[:200])  # Log first 200 chars of response
                return []
    except Exception as e:
        Logger.error("Error fetching ADS-B data from %s: %s", url, e)
        if Debug:
            import traceback
            traceback.print_exc()
        return []



def adsb_to_cot_xml(
    craft: dict,
    config: Union[SectionProxy, dict, None] = None,
    known_craft: Optional[dict] = None,
) -> Optional[ET.Element]:
    """
    Serialize ADS-B data as Cursor on Target using aircot best practices.

    Parameters
    ----------
    craft : dict
        Key/Value data struct of decoded ADS-B aircraft data.
    config : configparser.SectionProxy or dict
        Configuration options and values.
    known_craft : dict
        Optional list of known craft to transform CoT data.

    Returns
    -------
    xml.etree.ElementTree.Element
        Cursor-On-Target XML ElementTree object.
    """
    # Handle nested position data if present
    lastPosition = craft.get("lastPosition")
    if lastPosition:
        craft.update(lastPosition)

    # Extract coordinates
    lat = craft.get("lat", craft.get("Lat"))
    lon = craft.get("lon", craft.get("Lon", craft.get("Lng")))

    if lat is None or lon is None:
        Logger.warning("No position data: lat=%s lon=%s", lat, lon)
        return None

    # Initialize defaults
    remarks_fields = []
    known_craft = known_craft or {}
    config = config or {}
    category = None
    tisb: bool = False

    # Configuration defaults
    uid_key: str = config.get("UID_KEY", "ICAO")
    cot_stale: int = int(config.get("COT_STALE", pytak.DEFAULT_COT_STALE))
    cot_host_id: str = config.get("COT_HOST_ID", pytak.DEFAULT_HOST_ID)

    # Create ADS-B metadata element
    __adsb = ET.Element("__adsb")
    __adsb.set("cot_host_id", cot_host_id)

    # Parse aircraft identifiers
    icao_addr: str = aircot.icao_int_to_hex(
        craft.get("icao_addr", craft.get("Icao_addr", 0))
    )
    icao_hex: str = str(craft.get("hex", craft.get("icao", icao_addr))).strip().upper()

    _flight = craft.get("flight", craft.get("Tail", ""))
    flight: str = str(_flight).strip().upper()

    _reg = craft.get("reg", craft.get("r", craft.get("Reg", "")))
    reg: str = str(_reg).strip().upper()

    _cat = craft.get("cat", craft.get("Category", craft.get("category", "")))
    cat: str = str(_cat).strip().upper()

    _squawk = craft.get("squawk", craft.get("Squawk", ""))
    squawk: str = str(_squawk).strip().upper()

    _type = craft.get("t", craft.get("TargetType", 0))
    craft_type: str = str(_type).strip().upper()

    _desc = craft.get("desc", craft.get("Description", ""))
    desc: str = str(_desc).strip()

    _emergency = craft.get("emergency", "")
    emergency: str = str(_emergency).strip().lower()

    _messages = craft.get("messages", 0)
    messages: int = int(_messages) if _messages else 0

    _dbFlags = craft.get("dbFlags", 0)
    dbFlags: int = int(_dbFlags) if _dbFlags else 0

    # Handle altitude filtering with proper type conversion
    try:
        alt_upper: int = int(config.get("ALT_UPPER", "0"))
        alt_lower: int = int(config.get("ALT_LOWER", "0"))
    except (ValueError, TypeError):
        alt_upper = 0
        alt_lower = 0
    
    alt_geom_raw = craft.get("alt_geom") or craft.get("alt_baro")
    
    if alt_geom_raw is not None and alt_geom_raw != "ground":
        try:
            alt_geom = float(alt_geom_raw)
            if alt_upper and alt_upper != 0 and alt_geom > alt_upper:
                Logger.warning("Altitude %s exceeds upper limit %s", alt_geom, alt_upper)
                return None
            if alt_lower and alt_lower != 0 and alt_geom < alt_lower:
                Logger.warning("Altitude %s below lower limit %s", alt_geom, alt_lower)
                return None
        except (ValueError, TypeError):
            Logger.debug("Invalid altitude value for filtering: %s", alt_geom_raw)

    # Set ADS-B metadata
    __adsb.set("alt_geom", str(craft.get("alt_geom", "")))
    __adsb.set("alt_baro", str(craft.get("alt_baro", "")))
    __adsb.set("feed_url", config.get("FEED_URL", ""))

    # Build remarks and metadata
    if flight:
        remarks_fields.append(flight)
        __adsb.set("flight", flight)

    if reg:
        remarks_fields.append(reg)
        __adsb.set("reg", reg)

    if squawk:
        remarks_fields.append(f"Squawk: {squawk}")
        __adsb.set("squawk", squawk)

    if icao_hex:
        remarks_fields.append(icao_hex)
        __adsb.set("icao", icao_hex)

    if cat:
        category = aircot.set_category(cat, known_craft)
        remarks_fields.append(f"Cat.: {cat}")
        __adsb.set("cat", cat)

    if desc:
        __adsb.set("desc", desc)
        remarks_fields.append(f"Desc: {desc}")

    if emergency and emergency != "none":
        __adsb.set("emergency", emergency)
        remarks_fields.append(f"EMERGENCY: {emergency.upper()}")

    if messages > 0:
        __adsb.set("messages", str(messages))

    if dbFlags > 0:
        __adsb.set("dbFlags", str(dbFlags))

    if craft_type:
        __adsb.set("craft_type", str(craft_type))
        remarks_fields.append(f"Type:{craft_type}")

        # Determine craft type name
        craft_type_name: Union[str, None] = None
        craft_type_int = int(craft_type) if craft_type.isdigit() else 0
        
        if craft_type_int == 0:
            craft_type_name = "Mode S"
        elif craft_type_int == 1:
            craft_type_name = "ADS-B"
        elif craft_type_int == 2:
            craft_type_name = "ADS-R"
        elif craft_type_int == 3:
            craft_type_name = "TIS-B S"
            tisb = True
        elif craft_type_int == 4:
            craft_type_name = "TIS-B"
            tisb = True
            
        if craft_type_name:
            remarks_fields.append(f"ADS-B Type: {craft_type_name}")

    # Generate UID
    cot_uid: str = ""
    if "REG" in uid_key and reg:
        cot_uid = f"REG-{reg}"
    elif "ICAO" in uid_key and icao_hex:
        cot_uid = f"ICAO-{icao_hex}"
    elif "FLIGHT" in uid_key and flight:
        cot_uid = f"FLIGHT-{flight}"
    elif icao_hex:
        cot_uid = f"ICAO-{icao_hex}"
    elif flight:
        cot_uid = f"FLIGHT-{flight}"
    else:
        Logger.warning("Could not generate UID for craft: %s", craft)
        return None

    # Determine callsign
    if flight:
        callsign = flight
    elif reg:
        callsign = reg
    else:
        callsign = icao_hex

    # Set name and callsign using aircot
    _, callsign = aircot.set_name_callsign(
        icao_hex, reg, craft_type, flight, known_craft
    )

    # Set CoT type
    if tisb:
        cot_type = "a-u-A"
    else:
        cot_type = aircot.set_cot_type(icao_hex, category, flight, known_craft)

    # Calculate accuracy values with proper type conversion
    try:
        nac_p_val = craft.get("NACp", craft.get("nac_p", 0.0))
        nac_p = float(nac_p_val) if nac_p_val is not None else 0.0
    except (ValueError, TypeError):
        nac_p = 0.0
        
    try:
        nac_v_val = craft.get("NACv", craft.get("nac_v", nac_p))
        nac_v = float(nac_v_val) if nac_v_val is not None else nac_p
    except (ValueError, TypeError):
        nac_v = nac_p

    # Handle altitude with proper type conversion
    if craft.get("OnGround") or craft.get("on_ground"):
        ground_const = 51.56
        hae = pytak.DEFAULT_COT_VAL
    else:
        ground_const = 56.57
        # Get altitude and ensure it's numeric
        alt_value = craft.get("Alt", craft.get("alt_geom", craft.get("alt_baro")))
        if alt_value is not None and alt_value != "ground":
            try:
                alt_numeric = float(alt_value)
                hae = aircot.functions.get_hae(alt_numeric)
            except (ValueError, TypeError):
                Logger.debug("Invalid altitude value: %s", alt_value)
                hae = pytak.DEFAULT_COT_VAL
        else:
            hae = pytak.DEFAULT_COT_VAL

    ce = str(float(nac_p) + ground_const)
    le = str(float(nac_v) + 12.5)

    # Create contact element
    contact: ET.Element = ET.Element("contact")
    contact.set("callsign", callsign)

    # Create track element
    track: ET.Element = ET.Element("track")

    course = craft.get(
        "trk", craft.get("track", craft.get("Track", pytak.DEFAULT_COT_VAL))
    )
    track.set("course", str(course))

    # Handle speed with proper type conversion
    _speed = craft.get("gs", craft.get("Speed", 0.0))
    try:
        if _speed is not None:
            speed_numeric = float(_speed)
            speed = aircot.functions.get_speed(speed_numeric)
        else:
            speed = 0.0
    except (ValueError, TypeError):
        Logger.debug("Invalid speed value: %s", _speed)
        speed = 0.0
    track.set("speed", str(speed))

    track.set("slope", str(craft.get("Vvel", pytak.DEFAULT_COT_VAL)))

    # Create radio element
    _radio = ET.Element("_radio")
    _signal = craft.get("SignalLevel", craft.get("rssi"))
    if _signal:
        __adsb.set("signalLevel", str(_signal))
        _radio.set("signal", str(_signal))

    # Create remarks
    remarks_fields.append(f"FEED: {config.get('FEED_URL', 'opendata.adsb.fi')}")
    remarks_fields.append(f"{cot_host_id}")
    
    remarks = ET.Element("remarks")
    _remarks = " ".join(list(filter(None, remarks_fields)))
    remarks.text = _remarks

    # Build detail element
    detail = ET.Element("detail")
    detail.append(track)
    detail.append(contact)
    detail.append(remarks)
    detail.append(__adsb)
    detail.append(_radio)

    # Add icon if available
    icon = known_craft.get("ICON")
    if icon:
        usericon = ET.Element("usericon")
        usericon.set("iconsetpath", icon)
        detail.append(usericon)

    # Generate CoT XML
    cot_d = {
        "lat": str(lat),
        "lon": str(lon),
        "ce": str(ce),
        "le": str(le),
        "hae": str(hae),
        "uid": cot_uid,
        "cot_type": cot_type,
        "stale": cot_stale,
    }
    
    cot = pytak.gen_cot_xml(**cot_d)
    cot.set("access", config.get("COT_ACCESS", pytak.DEFAULT_COT_ACCESS))
    cot.set("qos", "1-r-c")

    # Replace detail element
    _detail = cot.findall("detail")[0]
    flowtags = _detail.findall("_flow-tags_")
    detail.extend(flowtags)
    cot.remove(_detail)
    cot.append(detail)

    return cot


def adsb_to_cot(
    craft: dict,
    config: Union[SectionProxy, dict, None] = None,
    known_craft: Optional[dict] = None,
) -> Optional[bytes]:
    """Return CoT XML object as an XML string."""
    cot: Optional[ET.Element] = adsb_to_cot_xml(craft, config, known_craft)
    return (
        b"\n".join([pytak.DEFAULT_XML_DECLARATION, ET.tostring(cot)]) if cot else None
    )

def aircraft_to_cot(aircraft, config=None):
    """Convert ADS-B aircraft data to CoT Event using improved aircot methods."""
    if config is None:
        # Create a basic config for the conversion
        config = {
            "UID_KEY": "ICAO",
            "COT_STALE": 300,  # 5 minutes
            "COT_HOST_ID": "adsb-feeder",
            "FEED_URL": "opendata.adsb.fi",
            "COT_ACCESS": pytak.DEFAULT_COT_ACCESS
        }
    
    # Use the improved adsb_to_cot function
    return adsb_to_cot(aircraft, config)


def tak_pong():
    """Generate a simple takPong CoT Event."""
    root = ET.Element("event")
    root.set("version", "2.0")
    root.set("type", "t-x-d-d-y")
    root.set("uid", "takPongasdasdasd")
    root.set("how", "m-g")
    root.set("callsign", "takPong-ashbdashdbah")
    root.set("time", pytak.cot_time())
    root.set("start", pytak.cot_time())
    root.set("stale", pytak.cot_time(3600))
    
    return ET.tostring(root)


def parse_data_sources_from_env():
    """
    Parse data sources from environment variables.

    Supports two modes:
    1. Multiple sources via ADSB_SOURCES_JSON (JSON array)
    2. Legacy single source via individual env vars

    Example ADSB_SOURCES_JSON:
    [
      {"name": "adsb.fi-mil", "base_url": "https://opendata.adsb.fi/api/v2", "endpoint": "mil", "sleep_interval": 10},
      {"name": "adsb.lol-nyc", "base_url": "https://api.adsb.lol/v2", "endpoint": "point", "lat": "40.7128", "lon": "-74.0060", "distance": "25", "sleep_interval": 3}
    ]
    """
    import json

    sources = []

    # Check for multi-source JSON configuration
    sources_json = os.getenv("ADSB_SOURCES_JSON")
    if sources_json:
        try:
            sources_data = json.loads(sources_json)
            for src in sources_data:
                name = src.get("name", "unknown")
                base_url = src.get("base_url", "https://opendata.adsb.fi/api/v2")
                endpoint = src.get("endpoint", "geo")
                sleep_interval = src.get("sleep_interval")  # Optional per-source interval

                # Convert to float if provided
                if sleep_interval is not None:
                    try:
                        sleep_interval = float(sleep_interval)
                    except (ValueError, TypeError):
                        Logger.warning("[%s] Invalid sleep_interval value, ignoring: %s", name, sleep_interval)
                        sleep_interval = None

                # Extract other params (lat, lon, distance, etc.)
                params = {k: v for k, v in src.items()
                         if k not in ["name", "base_url", "endpoint", "sleep_interval"]}

                sources.append(DataSource(name, base_url, endpoint, sleep_interval, **params))
            Logger.info("Loaded %d data sources from ADSB_SOURCES_JSON", len(sources))
            return sources
        except json.JSONDecodeError as e:
            Logger.error("Failed to parse ADSB_SOURCES_JSON: %s", e)
            Logger.error("Falling back to legacy single source configuration")

    # Legacy single source configuration
    base_url = os.getenv("ADSB_API_URL", "https://opendata.adsb.fi/api/v2")
    endpoint = os.getenv("ADSB_ENDPOINT", "geo")
    params = {
        "lat": os.getenv("ADSB_LAT", "40.7128"),
        "lon": os.getenv("ADSB_LON", "-74.0060"),
        "distance": os.getenv("ADSB_DISTANCE", "15")
    }
    name = f"{endpoint}@{base_url.split('//')[1].split('/')[0]}"
    sources.append(DataSource(name, base_url, endpoint, sleep_interval=None, **params))
    Logger.info("Using legacy single source configuration: %s", name)

    return sources


async def main():
    """Main definition of your program, sets config params and
    adds your serializer to the asyncio task list.
    """
    # Set up logging
    if Debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    config = ConfigParser()

    # Use environment variables for Docker compatibility
    # Default to localhost for better cross-platform compatibility
    cot_url = os.getenv("COT_URL", "tls://localhost:8089")
    tls_password = os.getenv("PYTAK_TLS_CLIENT_PASSWORD", "atakatak")
    tls_cert = os.getenv("PYTAK_TLS_CLIENT_CERT", "certs/funuser3.p12")

    # Check if certificate file exists
    if not os.path.exists(tls_cert):
        Logger.warning("Client certificate not found at %s", tls_cert)
        if os.getenv("PYTAK_TLS_DISABLE_CERT", "false").lower() in ["true", "1", "yes"]:
            Logger.warning("Client certificate disabled - using anonymous connection")
            tls_cert = None
        else:
            Logger.error("Client certificate required but not found. Set PYTAK_TLS_DISABLE_CERT=true to disable (testing only)")
            Logger.error("Or provide a valid certificate file at %s", tls_cert)

    # Enhanced configuration with aircot-specific settings
    config["mycottool"] = {
        # PyTAK settings
        "COT_URL": cot_url,
        "PYTAK_TLS_CLIENT_PASSWORD": tls_password,
        "PYTAK_TLS_DONT_CHECK_HOSTNAME": "1",
        "PYTAK_TLS_DONT_VERIFY": "1",
        "PYTAK_TLS_CLIENT_CERT": tls_cert if tls_cert else "",

        # Queue size configuration - increase these to prevent "Queue full" warnings
        "MAX_OUT_QUEUE": os.getenv("MAX_OUT_QUEUE", "1000"),
        "MAX_IN_QUEUE": os.getenv("MAX_IN_QUEUE", "1000"),

        # Aircot-specific settings
        "UID_KEY": os.getenv("UID_KEY", "ICAO"),
        "COT_STALE": os.getenv("COT_STALE", "300"),  # 5 minutes
        "COT_HOST_ID": os.getenv("COT_HOST_ID", "adsb-feeder"),
        "FEED_URL": os.getenv("FEED_URL", "multi-source"),
        "COT_ACCESS": os.getenv("COT_ACCESS", pytak.DEFAULT_COT_ACCESS),

        # ADS-B Data Source Configuration (legacy - for backward compatibility)
        "ADSB_ENDPOINT": os.getenv("ADSB_ENDPOINT", "geo"),
        "ADSB_LAT": os.getenv("ADSB_LAT", "40.7128"),
        "ADSB_LON": os.getenv("ADSB_LON", "-74.0060"),
        "ADSB_DISTANCE": os.getenv("ADSB_DISTANCE", "15"),
        "ADSB_API_URL": os.getenv("ADSB_API_URL", "https://opendata.adsb.fi/api/v2"),
        "SLEEP_INTERVAL": os.getenv("SLEEP_INTERVAL", "3"),

        # Altitude filtering (optional)
        "ALT_UPPER": os.getenv("ALT_UPPER", "0"),
        "ALT_LOWER": os.getenv("ALT_LOWER", "0"),
    }

    config = config["mycottool"]

    # Parse data sources
    data_sources = parse_data_sources_from_env()

    Logger.info("Starting ADS-B to CoT converter with multi-source support")
    Logger.info("COT URL: %s", config.get('COT_URL'))
    Logger.info("Host ID: %s", config.get('COT_HOST_ID'))
    Logger.info("UID Key: %s", config.get('UID_KEY'))
    Logger.info("Data Sources: %d configured", len(data_sources))

    for source in data_sources:
        Logger.info("  - %s: %s/%s", source.name, source.base_url, source.endpoint)
        if source.endpoint.lower() not in ["mil"]:
            Logger.info("    Location: %s, %s (radius: %s)",
                       source.params.get('lat'), source.params.get('lon'),
                       source.params.get('distance'))

    Logger.info("Poll Interval: %s seconds", config.get('SLEEP_INTERVAL'))

    # Initializes worker queues and tasks.
    clitool = pytak.CLITool(config)
    try:
        await clitool.setup()
    except Exception as e:
        Logger.error("Failed to connect to TAK server at %s: %s", config.get('COT_URL'), e)
        Logger.error("This might be a DNS resolution issue. Try setting COT_URL environment variable to the correct server address.")
        raise

    # Add your serializer to the asyncio task list with data sources
    clitool.add_tasks(set([MySerializer(clitool.tx_queue, config, data_sources)]))

    # Start all tasks.
    await clitool.run()


if __name__ == "__main__":
    asyncio.run(main())
    
    
    
    
# export PYTAK_TLS_CLIENT_PASSWORD=atakatak
# export PYTAK_TLS_DONT_CHECK_HOSTNAME=1
# export PYTAK_TLS_DONT_VERIFY=1    
# export PYTAK_TLS_CLIENT_CERT=/certs/user1.p12
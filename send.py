#!/usr/bin/env python3

import asyncio
import xml.etree.ElementTree as ET
import os
import logging
from typing import Optional, Union

from configparser import ConfigParser, SectionProxy

import pytak
import aiohttp
import aircot

# Set up logging
Logger = logging.getLogger(__name__)
Debug = bool(os.getenv("DEBUG", "False").lower() in ["true", "1", "yes"])

class MySerializer(pytak.QueueWorker):
    """
    Defines how you process or generate your Cursor on Target Events.
    From there it adds the CoT Events to a queue for TX to a COT_URL.
    """

    def __init__(self, queue, config):
        super().__init__(queue, config)
        self.config = config

    async def handle_data(self, data):
        """Handle pre-CoT data, serialize to CoT Event, then puts on queue."""
        event = data
        await self.put_queue(event)

    async def run(self):
        """Run the loop for processing or generating pre-CoT data."""
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    aircraft_data = await fetch_adsb_data(session, self.config)
                    if aircraft_data:
                        Logger.info("Processing %d aircraft", len(aircraft_data))
                        for aircraft in aircraft_data:
                            cot_event = aircraft_to_cot(aircraft, self.config)
                            if cot_event:
                                await self.handle_data(cot_event)
                            else:
                                Logger.debug("Skipped aircraft: %s", aircraft.get('hex', 'unknown'))
                except Exception as e:
                    Logger.error("Error fetching/processing ADS-B data: %s", e)
                    if Debug:
                        import traceback
                        traceback.print_exc()
                
                sleep_interval = float(self.config.get("SLEEP_INTERVAL", 3))
                await asyncio.sleep(sleep_interval)


async def fetch_adsb_data(session, config=None):
    """Fetch ADS-B data from opendata.adsb.fi API for configurable area."""
    if config is None:
        config = {}
    
    # Default to NYC coordinates: 40.7128, -74.0060, 15 mile radius
    lat = config.get("ADSB_LAT", "40.7128")
    lon = config.get("ADSB_LON", "-74.0060") 
    distance = config.get("ADSB_DISTANCE", "15")
    base_url = config.get("ADSB_API_URL", "https://opendata.adsb.fi/api/v2")
    
    url = f"{base_url}/lat/{lat}/lon/{lon}/dist/{distance}"
    
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('aircraft', [])
            else:
                Logger.warning("HTTP error %d fetching ADS-B data", response.status)
                return []
    except Exception as e:
        Logger.error("Error fetching ADS-B data: %s", e)
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
    tls_cert = os.getenv("PYTAK_TLS_CLIENT_CERT", "certs/user1.p12")
    
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
        
        # Aircot-specific settings
        "UID_KEY": os.getenv("UID_KEY", "ICAO"),
        "COT_STALE": os.getenv("COT_STALE", "300"),  # 5 minutes
        "COT_HOST_ID": os.getenv("COT_HOST_ID", "adsb-feeder"),
        "FEED_URL": os.getenv("FEED_URL", "opendata.adsb.fi/NYC"),
        "COT_ACCESS": os.getenv("COT_ACCESS", pytak.DEFAULT_COT_ACCESS),
        
        # ADS-B Data Source Configuration
        "ADSB_LAT": os.getenv("ADSB_LAT", "40.7128"),  # Default: NYC latitude
        "ADSB_LON": os.getenv("ADSB_LON", "-74.0060"),  # Default: NYC longitude
        "ADSB_DISTANCE": os.getenv("ADSB_DISTANCE", "15"),  # Default: 15 mile radius
        "ADSB_API_URL": os.getenv("ADSB_API_URL", "https://opendata.adsb.fi/api/v2"),
        "SLEEP_INTERVAL": os.getenv("SLEEP_INTERVAL", "3"),  # Default: 3 seconds between polls
        
        # Altitude filtering (optional)
        "ALT_UPPER": os.getenv("ALT_UPPER", "0"),  # 0 = no upper limit
        "ALT_LOWER": os.getenv("ALT_LOWER", "0"),  # 0 = no lower limit
    }
    
    config = config["mycottool"]

    Logger.info("Starting ADS-B to CoT converter")
    Logger.info("COT URL: %s", config.get('COT_URL'))
    Logger.info("Host ID: %s", config.get('COT_HOST_ID'))
    Logger.info("UID Key: %s", config.get('UID_KEY'))
    Logger.info("ADS-B Location: %s, %s (radius: %s miles)", 
                config.get('ADSB_LAT'), config.get('ADSB_LON'), config.get('ADSB_DISTANCE'))
    Logger.info("ADS-B API: %s", config.get('ADSB_API_URL'))
    Logger.info("Poll Interval: %s seconds", config.get('SLEEP_INTERVAL'))

    # Initializes worker queues and tasks.
    clitool = pytak.CLITool(config)
    try:
        await clitool.setup()
    except Exception as e:
        Logger.error("Failed to connect to TAK server at %s: %s", config.get('COT_URL'), e)
        Logger.error("This might be a DNS resolution issue. Try setting COT_URL environment variable to the correct server address.")
        raise

    # Add your serializer to the asyncio task list.
    clitool.add_tasks(set([MySerializer(clitool.tx_queue, config)]))

    # Start all tasks.
    await clitool.run()


if __name__ == "__main__":
    asyncio.run(main())
    
    
    
    
# export PYTAK_TLS_CLIENT_PASSWORD=atakatak
# export PYTAK_TLS_DONT_CHECK_HOSTNAME=1
# export PYTAK_TLS_DONT_VERIFY=1    
# export PYTAK_TLS_CLIENT_CERT=/certs/user1.p12
"""
ADS-B → Cursor on Target (CoT) XML conversion.
Adapted from send.py:adsb_to_cot_xml() and adsb_to_cot().
"""

import logging
import xml.etree.ElementTree as ET
from configparser import SectionProxy
from typing import Optional, Union

import aircot
import pytak

log = logging.getLogger(__name__)


def adsb_to_cot_xml(
    craft: dict,
    config: Union[SectionProxy, dict, None] = None,
    known_craft: Optional[dict] = None,
) -> Optional[ET.Element]:
    """
    Serialize ADS-B aircraft data as a CoT XML Element.

    Parameters
    ----------
    craft       Key/value ADS-B aircraft data.
    config      Configuration dict (COT_STALE, COT_HOST_ID, UID_KEY, etc.).
    known_craft Optional overrides for specific aircraft.

    Returns None if the aircraft should be skipped (no position, filtered by
    altitude, or missing a usable identifier).
    """
    # Handle nested position data (some APIs use lastPosition sub-object)
    last_pos = craft.get("lastPosition")
    if last_pos:
        craft = {**craft, **last_pos}

    lat = craft.get("lat", craft.get("Lat"))
    lon = craft.get("lon", craft.get("Lon", craft.get("Lng")))
    if lat is None or lon is None:
        log.debug("Skipping aircraft — no position (lat=%s lon=%s)", lat, lon)
        return None

    remarks_fields: list[str] = []
    known_craft = known_craft or {}
    config = config or {}
    tisb: bool = False
    category = None

    uid_key: str = config.get("UID_KEY", "ICAO")
    cot_stale: int = int(config.get("COT_STALE", pytak.DEFAULT_COT_STALE))
    cot_host_id: str = config.get("COT_HOST_ID", pytak.DEFAULT_HOST_ID)

    # --- ADS-B metadata element ---
    __adsb = ET.Element("__adsb")
    __adsb.set("cot_host_id", cot_host_id)

    # --- Identifiers ---
    icao_addr: str = aircot.icao_int_to_hex(
        craft.get("icao_addr", craft.get("Icao_addr", 0))
    )
    icao_hex: str = str(craft.get("hex", craft.get("icao", icao_addr))).strip().upper()

    flight: str = str(craft.get("flight", craft.get("Tail", ""))).strip().upper()
    reg: str = str(craft.get("reg", craft.get("r", craft.get("Reg", "")))).strip().upper()
    cat: str = str(craft.get("cat", craft.get("Category", craft.get("category", "")))).strip().upper()
    squawk: str = str(craft.get("squawk", craft.get("Squawk", ""))).strip().upper()
    craft_type: str = str(craft.get("t", craft.get("TargetType", 0))).strip().upper()
    desc: str = str(craft.get("desc", craft.get("Description", ""))).strip()
    emergency: str = str(craft.get("emergency", "")).strip().lower()
    messages: int = int(craft.get("messages", 0) or 0)
    db_flags: int = int(craft.get("dbFlags", 0) or 0)

    # --- Altitude filtering ---
    try:
        alt_upper = int(config.get("ALT_UPPER", 0) or 0)
        alt_lower = int(config.get("ALT_LOWER", 0) or 0)
    except (ValueError, TypeError):
        alt_upper = alt_lower = 0

    alt_raw = craft.get("alt_geom") or craft.get("alt_baro")
    if alt_raw is not None and alt_raw != "ground":
        try:
            alt_f = float(alt_raw)
            if alt_upper and alt_f > alt_upper:
                log.debug("Skipping %s — alt %s > upper %s", icao_hex, alt_f, alt_upper)
                return None
            if alt_lower and alt_f < alt_lower:
                log.debug("Skipping %s — alt %s < lower %s", icao_hex, alt_f, alt_lower)
                return None
        except (ValueError, TypeError):
            pass

    # --- Populate __adsb element and remarks ---
    __adsb.set("alt_geom", str(craft.get("alt_geom", "")))
    __adsb.set("alt_baro", str(craft.get("alt_baro", "")))
    __adsb.set("feed_url", config.get("FEED_URL", ""))

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
    if messages:
        __adsb.set("messages", str(messages))
    if db_flags:
        __adsb.set("dbFlags", str(db_flags))

    if craft_type:
        __adsb.set("craft_type", craft_type)
        remarks_fields.append(f"Type:{craft_type}")
        craft_type_int = int(craft_type) if craft_type.isdigit() else 0
        type_names = {0: "Mode S", 1: "ADS-B", 2: "ADS-R", 3: "TIS-B S", 4: "TIS-B"}
        if craft_type_int in type_names:
            remarks_fields.append(f"ADS-B Type: {type_names[craft_type_int]}")
        if craft_type_int in (3, 4):
            tisb = True

    # --- UID ---
    cot_uid = ""
    if "REG" in uid_key and reg:
        cot_uid = f"REG-{reg}"
    elif "FLIGHT" in uid_key and flight:
        cot_uid = f"FLIGHT-{flight}"
    elif icao_hex:
        cot_uid = f"ICAO-{icao_hex}"
    elif flight:
        cot_uid = f"FLIGHT-{flight}"
    else:
        log.debug("Cannot generate UID for craft: %s", craft)
        return None

    # --- Callsign ---
    _, callsign = aircot.set_name_callsign(icao_hex, reg, craft_type, flight, known_craft)

    # --- CoT type ---
    cot_type = "a-u-A" if tisb else aircot.set_cot_type(icao_hex, category, flight, known_craft)

    # --- Accuracy ---
    try:
        nac_p = float(craft.get("NACp", craft.get("nac_p", 0.0)) or 0.0)
    except (ValueError, TypeError):
        nac_p = 0.0
    try:
        nac_v = float(craft.get("NACv", craft.get("nac_v", nac_p)) or nac_p)
    except (ValueError, TypeError):
        nac_v = nac_p

    # --- Altitude / HAE ---
    if craft.get("OnGround") or craft.get("on_ground"):
        ground_const = 51.56
        hae = pytak.DEFAULT_COT_VAL
    else:
        ground_const = 56.57
        alt_val = craft.get("Alt", craft.get("alt_geom", craft.get("alt_baro")))
        if alt_val is not None and alt_val != "ground":
            try:
                hae = aircot.functions.get_hae(float(alt_val))
            except (ValueError, TypeError):
                hae = pytak.DEFAULT_COT_VAL
        else:
            hae = pytak.DEFAULT_COT_VAL

    ce = str(float(nac_p) + ground_const)
    le = str(float(nac_v) + 12.5)

    # --- Sub-elements ---
    contact = ET.Element("contact")
    contact.set("callsign", callsign)

    track = ET.Element("track")
    course = craft.get("trk", craft.get("track", craft.get("Track", pytak.DEFAULT_COT_VAL)))
    track.set("course", str(course))

    _speed_raw = craft.get("gs", craft.get("Speed", 0.0))
    try:
        speed = aircot.functions.get_speed(float(_speed_raw)) if _speed_raw is not None else 0.0
    except (ValueError, TypeError):
        speed = 0.0
    track.set("speed", str(speed))
    track.set("slope", str(craft.get("Vvel", pytak.DEFAULT_COT_VAL)))

    _radio = ET.Element("_radio")
    signal = craft.get("SignalLevel", craft.get("rssi"))
    if signal:
        __adsb.set("signalLevel", str(signal))
        _radio.set("signal", str(signal))

    remarks_fields.append(f"FEED: {config.get('FEED_URL', 'unknown')}")
    remarks_fields.append(str(cot_host_id))
    remarks = ET.Element("remarks")
    remarks.text = " ".join(filter(None, remarks_fields))

    detail = ET.Element("detail")
    detail.extend([track, contact, remarks, __adsb, _radio])

    icon = known_craft.get("ICON")
    if icon:
        usericon = ET.Element("usericon")
        usericon.set("iconsetpath", icon)
        detail.append(usericon)

    # --- Assemble CoT event ---
    cot = pytak.gen_cot_xml(
        lat=str(lat),
        lon=str(lon),
        ce=ce,
        le=le,
        hae=str(hae),
        uid=cot_uid,
        cot_type=cot_type,
        stale=cot_stale,
    )
    cot.set("access", config.get("COT_ACCESS", pytak.DEFAULT_COT_ACCESS))
    cot.set("qos", "1-r-c")

    _detail = cot.findall("detail")[0]
    detail.extend(_detail.findall("_flow-tags_"))
    cot.remove(_detail)
    cot.append(detail)

    return cot


def adsb_to_cot(
    craft: dict,
    config: Union[SectionProxy, dict, None] = None,
    known_craft: Optional[dict] = None,
) -> Optional[bytes]:
    """Convert an ADS-B aircraft dict to CoT XML bytes. Returns None if skipped."""
    cot = adsb_to_cot_xml(craft, config, known_craft)
    if cot is None:
        return None
    return b"\n".join([pytak.DEFAULT_XML_DECLARATION, ET.tostring(cot)])

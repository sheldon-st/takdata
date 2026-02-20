"""
AIS → Cursor on Target (CoT) XML conversion.
"""

import logging
import xml.etree.ElementTree as ET
from configparser import SectionProxy
from typing import Optional, Union

import pytak

log = logging.getLogger(__name__)

# AIS navigational status codes
NAV_STATUS = {
    0: "Under way using engine",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by her draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way sailing",
    15: "Not defined",
}


def _ship_type_to_cot(ship_type: int) -> str:
    """Map AIS ship type code to a CoT type string."""
    if ship_type == 35:
        return "a-f-S-X-M"        # Military ops
    if ship_type in (51,):
        return "a-f-S-X-L-O-R"    # Search and rescue
    if 30 <= ship_type <= 34:
        return "a-n-S-X-L"        # Fishing / towing / dredging
    if 50 <= ship_type <= 59:
        return "a-f-S-X-L"        # Port, pilot, tender
    if 60 <= ship_type <= 69:
        return "a-n-S-X-L-O-V"    # Passenger
    if 70 <= ship_type <= 79:
        return "a-n-S-X-L-O-V"    # Cargo
    if 80 <= ship_type <= 89:
        return "a-n-S-X-L-O-W-T"  # Tanker
    return "a-n-S-X-L"            # Default surface vessel


def ais_to_cot_xml(
    vessel: dict,
    config: Union[SectionProxy, dict, None] = None,
) -> Optional[ET.Element]:
    """
    Serialize AIS vessel data as a CoT XML Element.

    Parameters
    ----------
    vessel  Flattened vessel dict with keys from aisstream.io MetaData + Message.
    config  Configuration dict (COT_STALE, COT_HOST_ID, etc.).

    Returns None if the vessel should be skipped (missing MMSI or position).
    """
    config = config or {}

    mmsi = vessel.get("MMSI") or vessel.get("UserID")
    if not mmsi:
        return None
    mmsi = str(mmsi).strip()

    lat = vessel.get("Latitude")
    lon = vessel.get("Longitude")
    if lat is None or lon is None:
        log.debug("Skipping vessel %s — no position", mmsi)
        return None

    cot_stale = int(config.get("COT_STALE", pytak.DEFAULT_COT_STALE))
    cot_host_id = config.get("COT_HOST_ID", pytak.DEFAULT_HOST_ID)

    ship_name = str(vessel.get("ShipName", vessel.get("Name", ""))).strip()
    callsign = str(vessel.get("CallSign", vessel.get("call_sign", ""))).strip()
    ship_type = int(vessel.get("ShipType", vessel.get("Type", 0)) or 0)
    destination = str(vessel.get("Destination", "")).strip()
    nav_status = int(vessel.get("NavigationalStatus", 15) or 15)

    sog = float(vessel.get("Sog", 0.0) or 0.0)          # knots
    cog = float(vessel.get("Cog", 0.0) or 0.0)          # degrees
    true_heading = int(vessel.get("TrueHeading", 511) or 511)  # 511 = not available

    course = cog if true_heading == 511 else float(true_heading)
    speed_ms = sog * 0.514444  # knots → m/s

    cot_type = _ship_type_to_cot(ship_type)
    cot_uid = f"MMSI-{mmsi}"

    display_name = ship_name if ship_name else f"MMSI-{mmsi}"

    # --- Remarks ---
    remarks_fields: list[str] = []
    if ship_name:
        remarks_fields.append(f"Vessel: {ship_name}")
    if callsign:
        remarks_fields.append(f"Call: {callsign}")
    remarks_fields.append(f"MMSI: {mmsi}")
    if destination:
        remarks_fields.append(f"Dest: {destination}")
    remarks_fields.append(NAV_STATUS.get(nav_status, f"Status: {nav_status}"))
    remarks_fields.append(f"Speed: {sog:.1f}kts")
    feed_url = config.get("FEED_URL", "aisstream")
    remarks_fields.append(f"FEED: {feed_url}")
    remarks_fields.append(str(cot_host_id))

    # --- __ais detail element ---
    __ais = ET.Element("__ais")
    __ais.set("cot_host_id", str(cot_host_id))
    __ais.set("mmsi", mmsi)
    if ship_name:
        __ais.set("ship_name", ship_name)
    if callsign:
        __ais.set("callsign", callsign)
    __ais.set("ship_type", str(ship_type))
    __ais.set("nav_status", str(nav_status))
    if destination:
        __ais.set("destination", destination)
    __ais.set("sog", str(sog))
    __ais.set("cog", str(cog))
    __ais.set("feed_url", feed_url)

    contact = ET.Element("contact")
    contact.set("callsign", display_name)

    track = ET.Element("track")
    track.set("course", str(course))
    track.set("speed", str(speed_ms))

    remarks = ET.Element("remarks")
    remarks.text = " | ".join(filter(None, remarks_fields))

    detail = ET.Element("detail")
    detail.extend([track, contact, remarks, __ais])

    # --- Assemble CoT event ---
    cot = pytak.gen_cot_xml(
        lat=str(lat),
        lon=str(lon),
        ce=str(pytak.DEFAULT_COT_VAL),
        le=str(pytak.DEFAULT_COT_VAL),
        hae=str(pytak.DEFAULT_COT_VAL),
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


def ais_to_cot(
    vessel: dict,
    config: Union[SectionProxy, dict, None] = None,
) -> Optional[bytes]:
    """Convert an AIS vessel dict to CoT XML bytes. Returns None if skipped."""
    cot = ais_to_cot_xml(vessel, config)
    if cot is None:
        return None
    return b"\n".join([pytak.DEFAULT_XML_DECLARATION, ET.tostring(cot)])

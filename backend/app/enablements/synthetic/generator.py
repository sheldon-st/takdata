"""Synthetic entity → CoT XML bytes."""

import xml.etree.ElementTree as ET

import pytak


def synthetic_to_cot(entity: dict, config: dict) -> bytes:
    """Convert a synthetic entity dict to CoT XML bytes."""
    cot_stale = int(config.get("COT_STALE", 300))
    cot_host_id = config.get("COT_HOST_ID", pytak.DEFAULT_HOST_ID)

    cot = pytak.gen_cot_xml(
        lat=str(entity["lat"]),
        lon=str(entity["lon"]),
        ce=str(entity.get("ce", 10.0)),
        le=str(entity.get("le", 10.0)),
        hae=str(entity.get("hae", 0.0)),
        uid=entity["uid"],
        cot_type=entity.get("cot_type", "a-f-G"),
        stale=cot_stale,
    )
    cot.set("access", config.get("COT_ACCESS", pytak.DEFAULT_COT_ACCESS))
    cot.set("qos", "1-r-c")

    contact = ET.Element("contact")
    contact.set("callsign", entity["callsign"])

    track = ET.Element("track")
    track.set("course", str(entity.get("course", 0.0)))
    track.set("speed", str(entity.get("speed", 0.0)))

    remarks = ET.Element("remarks")
    remarks.text = f"synthetic harness {cot_host_id}"

    __syn = ET.Element("__synthetic")
    __syn.set("cot_host_id", cot_host_id)

    detail = ET.Element("detail")
    detail.extend([track, contact, remarks, __syn])

    _existing = cot.findall("detail")
    if _existing:
        detail.extend(_existing[0].findall("_flow-tags_"))
        cot.remove(_existing[0])
    cot.append(detail)

    return b"\n".join([pytak.DEFAULT_XML_DECLARATION, ET.tostring(cot)])

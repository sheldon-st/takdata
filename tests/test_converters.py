import xml.etree.ElementTree as ET

from app.enablements.adsb.converter import adsb_to_cot
from app.enablements.ais.converter import ais_to_cot
from app.enablements.synthetic.generator import synthetic_to_cot

CONFIG = {"COT_STALE": "120", "COT_HOST_ID": "test-host", "UID_KEY": "ICAO"}


def _parse(data: bytes) -> ET.Element:
    return ET.fromstring(data.split(b"\n", 1)[1])


def test_adsb_aircraft_becomes_cot_event():
    cot = adsb_to_cot({"hex": "ae1234", "lat": 40.7, "lon": -74.0, "flight": "RCH123"}, CONFIG)
    event = _parse(cot)
    assert event.tag == "event"
    assert event.get("uid") == "ICAO-AE1234"
    assert event.find("point").get("lat") == "40.7"


def test_adsb_without_position_is_skipped():
    assert adsb_to_cot({"hex": "ae1234"}, CONFIG) is None


def test_ais_vessel_becomes_cot_event():
    vessel = {"MMSI": "366999999", "Latitude": 37.8, "Longitude": -122.4, "ShipName": "TEST"}
    event = _parse(ais_to_cot(vessel, CONFIG))
    assert event.get("uid") == "MMSI-366999999"
    assert event.find("detail/contact").get("callsign") == "TEST"


def test_synthetic_entity_carries_host_id():
    entity = {"uid": "SYN-1-000001", "callsign": "SYN00001", "lat": 1.0, "lon": 2.0}
    event = _parse(synthetic_to_cot(entity, CONFIG))
    assert event.get("uid") == "SYN-1-000001"
    assert event.find("detail/__synthetic").get("cot_host_id") == "test-host"

import asyncio

import pytest

from app.core.config import settings
from app.enablements.ais.worker import AisWorker, _resolve_api_key


def test_api_key_prefers_source_then_legacy_then_setting(monkeypatch):
    monkeypatch.setattr(settings, "aisstream_api_key", "from-env")

    assert _resolve_api_key({"api_key": " own ", "endpoint": "legacy"}) == "own"
    assert _resolve_api_key({"endpoint": "legacy-key"}) == "legacy-key"
    assert _resolve_api_key({"endpoint": "geo"}) == "from-env"


def test_no_key_anywhere_is_empty(monkeypatch):
    monkeypatch.setattr(settings, "aisstream_api_key", None)
    assert _resolve_api_key({"endpoint": "mil"}) == ""


@pytest.fixture
def worker():
    return AisWorker(asyncio.Queue(), {}, [])


def test_radius_is_nautical_miles(worker):
    [[[min_lat, _], [max_lat, _]]] = worker._build_bounding_boxes(
        {"endpoint": "geo", "lat": 0.0, "lon": 0.0, "distance": 60.0}
    )
    # 60 nm ≈ 1° of latitude
    assert max_lat - min_lat == pytest.approx(2.0, rel=0.01)


def test_global_mode_subscribes_to_whole_world(worker):
    assert worker._build_bounding_boxes({"endpoint": "mil"}) == [[[-90.0, -180.0], [90.0, 180.0]]]


def test_global_mode_respects_geo_filter():
    w = AisWorker(
        asyncio.Queue(),
        {
            "geo_filter_min_lat": 1,
            "geo_filter_max_lat": 2,
            "geo_filter_min_lon": 3,
            "geo_filter_max_lon": 4,
        },
        [],
    )
    assert w._build_bounding_boxes({"endpoint": "mil"}) == [[[1.0, 3.0], [2.0, 4.0]]]


def test_no_location_and_no_filter_has_no_boxes(worker):
    assert worker._build_bounding_boxes({"endpoint": "geo"}) == []

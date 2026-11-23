"""
Pydantic request/response models for all API routes.
"""

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# TAK Server Config
# ---------------------------------------------------------------------------


class TakConfigUpdate(BaseModel):
    cot_url: str = Field("tls://localhost:8089", description="TAK server CoT URL")
    cert_path: str | None = Field(None, description="Path to .p12 cert under data/certs/")
    cert_password: str | None = Field(None, description="Password for the .p12 certificate")
    cot_host_id: str = Field("tak-manager", description="Host ID embedded in CoT events")
    dont_check_hostname: bool = Field(True, description="Skip TLS hostname verification")
    dont_verify: bool = Field(True, description="Skip TLS certificate verification")
    max_out_queue: int = Field(1000, description="Max outbound CoT queue size")
    max_in_queue: int = Field(1000, description="Max inbound CoT queue size")


class TakConfigResponse(BaseModel):
    id: int
    cot_url: str
    cert_path: str | None
    cot_host_id: str
    dont_check_hostname: bool
    dont_verify: bool
    max_out_queue: int
    max_in_queue: int
    updated_at: str | None
    # cert_password intentionally omitted from response


class TakStatusResponse(BaseModel):
    connected: bool
    url: str
    queue_size: int


# ---------------------------------------------------------------------------
# Cert management
# ---------------------------------------------------------------------------


class CertInfo(BaseModel):
    cert_id: str
    filename: str


# ---------------------------------------------------------------------------
# Data packages
# ---------------------------------------------------------------------------


class PackageInfo(BaseModel):
    package_id: str
    filename: str
    size: int = Field(..., description="Size in bytes")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class SourceCreate(BaseModel):
    name: str = Field(..., description="Friendly label, e.g. 'adsb.fi-military'")
    base_url: str = Field(..., description="Base API URL")
    endpoint: Literal["geo", "point", "mil"] = Field("geo")
    sleep_interval: float = Field(5.0, description="Polling interval in seconds")
    lat: float | None = Field(None, description="Latitude for geo/point queries")
    lon: float | None = Field(None, description="Longitude for geo/point queries")
    distance: float | None = Field(25.0, description="Radius in nautical miles")
    api_key: str | None = Field(
        None,
        description="Credential for sources that need one (e.g. aisstream.io). Write-only.",
    )
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    endpoint: Literal["geo", "point", "mil"] | None = None
    sleep_interval: float | None = None
    lat: float | None = None
    lon: float | None = None
    distance: float | None = None
    api_key: str | None = Field(None, description="Write-only. Send an empty string to clear.")
    enabled: bool | None = None


class SourceResponse(BaseModel):
    id: int
    enablement_id: int
    name: str
    base_url: str
    endpoint: str
    sleep_interval: float
    lat: float | None
    lon: float | None
    distance: float | None
    has_api_key: bool = False
    enabled: bool
    created_at: str
    # api_key intentionally omitted from response


# ---------------------------------------------------------------------------
# Enablements
# ---------------------------------------------------------------------------


class EnablementCreate(BaseModel):
    type_id: str = Field(..., description="Plugin type, e.g. 'adsb' or 'ais'")
    name: str = Field(..., description="User-friendly label")
    enabled: bool = True
    cot_stale: int = Field(300, description="CoT stale time in seconds")
    alt_upper: int = Field(0, description="Upper altitude filter in feet (0 = disabled)")
    alt_lower: int = Field(0, description="Lower altitude filter in feet (0 = disabled)")
    uid_key: str = Field("ICAO", description="UID key: ICAO, REG, or FLIGHT")
    geo_filter_min_lat: float | None = Field(
        None,
        description="Bounding box south latitude (-90 to 90); all four required to enable filter",
    )
    geo_filter_max_lat: float | None = Field(
        None, description="Bounding box north latitude (-90 to 90)"
    )
    geo_filter_min_lon: float | None = Field(
        None, description="Bounding box west longitude (-180 to 180)"
    )
    geo_filter_max_lon: float | None = Field(
        None, description="Bounding box east longitude (-180 to 180)"
    )
    feature_count: int | None = Field(
        None, description="Synthetic harness: population of unique features (N)"
    )
    updates_per_second: float | None = Field(
        None, description="Synthetic harness: tick rate in Hz (U)"
    )
    features_per_update: int | None = Field(
        None, description="Synthetic harness: features touched per tick (K). Aggregate rate = U*K"
    )
    selection_strategy: Literal["round_robin", "random", "zipf"] | None = Field(
        None, description="Synthetic harness: how to pick K features each tick"
    )
    seed_initial: bool | None = Field(
        False,
        description="Synthetic harness: emit all N features once at startup, then steady-state",
    )


class EnablementUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    cot_stale: int | None = None
    alt_upper: int | None = None
    alt_lower: int | None = None
    uid_key: str | None = None
    geo_filter_min_lat: float | None = None
    geo_filter_max_lat: float | None = None
    geo_filter_min_lon: float | None = None
    geo_filter_max_lon: float | None = None
    feature_count: int | None = None
    updates_per_second: float | None = None
    features_per_update: int | None = None
    selection_strategy: Literal["round_robin", "random", "zipf"] | None = None
    seed_initial: bool | None = None


class EnablementResponse(BaseModel):
    id: int
    type_id: str
    name: str
    enabled: bool
    cot_stale: int
    alt_upper: int
    alt_lower: int
    uid_key: str
    geo_filter_min_lat: float | None
    geo_filter_max_lat: float | None
    geo_filter_min_lon: float | None
    geo_filter_max_lon: float | None
    feature_count: int | None = None
    updates_per_second: float | None = None
    features_per_update: int | None = None
    selection_strategy: str | None = None
    seed_initial: bool = False
    running: bool
    created_at: str
    updated_at: str
    sources: list[SourceResponse] = []


# ---------------------------------------------------------------------------
# Enablement type metadata (from plugin registry)
# ---------------------------------------------------------------------------


class EnablementTypeInfo(BaseModel):
    type_id: str
    display_name: str
    description: str


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class SourceStatsItem(BaseModel):
    name: str
    last_poll: str | None
    aircraft_count: int


class EnablementStatusItem(BaseModel):
    id: int
    name: str
    type_id: str
    running: bool
    events_sent: int
    events_dropped: int = 0
    last_poll_time: str | None
    last_error: str | None
    active_items: int
    source_stats: dict


class StatusResponse(BaseModel):
    tak_connected: bool
    tak_url: str
    tx_queue_size: int
    connect_error: str | None = None
    enablements: list[EnablementStatusItem]
    server_time: str

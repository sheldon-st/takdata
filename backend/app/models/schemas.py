"""
Pydantic request/response models for all API routes.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# TAK Server Config
# ---------------------------------------------------------------------------

class TakConfigUpdate(BaseModel):
    cot_url: str = Field("tls://localhost:8089", description="TAK server CoT URL")
    cert_path: Optional[str] = Field(None, description="Path to .p12 cert under data/certs/")
    cert_password: Optional[str] = Field(None, description="Password for the .p12 certificate")
    cot_host_id: str = Field("tak-manager", description="Host ID embedded in CoT events")
    dont_check_hostname: bool = Field(True, description="Skip TLS hostname verification")
    dont_verify: bool = Field(True, description="Skip TLS certificate verification")
    max_out_queue: int = Field(1000, description="Max outbound CoT queue size")
    max_in_queue: int = Field(1000, description="Max inbound CoT queue size")


class TakConfigResponse(BaseModel):
    id: int
    cot_url: str
    cert_path: Optional[str]
    cot_host_id: str
    dont_check_hostname: bool
    dont_verify: bool
    max_out_queue: int
    max_in_queue: int
    updated_at: Optional[str]
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
# Sources
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    name: str = Field(..., description="Friendly label, e.g. 'adsb.fi-military'")
    base_url: str = Field(..., description="Base API URL")
    endpoint: Literal["geo", "point", "mil"] = Field("geo")
    sleep_interval: float = Field(5.0, description="Polling interval in seconds")
    lat: Optional[float] = Field(None, description="Latitude for geo/point queries")
    lon: Optional[float] = Field(None, description="Longitude for geo/point queries")
    distance: Optional[float] = Field(25.0, description="Radius in nautical miles")
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    endpoint: Optional[Literal["geo", "point", "mil"]] = None
    sleep_interval: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    distance: Optional[float] = None
    enabled: Optional[bool] = None


class SourceResponse(BaseModel):
    id: int
    enablement_id: int
    name: str
    base_url: str
    endpoint: str
    sleep_interval: float
    lat: Optional[float]
    lon: Optional[float]
    distance: Optional[float]
    enabled: bool
    created_at: str


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


class EnablementUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    cot_stale: Optional[int] = None
    alt_upper: Optional[int] = None
    alt_lower: Optional[int] = None
    uid_key: Optional[str] = None


class EnablementResponse(BaseModel):
    id: int
    type_id: str
    name: str
    enabled: bool
    cot_stale: int
    alt_upper: int
    alt_lower: int
    uid_key: str
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
    last_poll: Optional[str]
    aircraft_count: int


class EnablementStatusItem(BaseModel):
    id: int
    name: str
    type_id: str
    running: bool
    events_sent: int
    last_poll_time: Optional[str]
    last_error: Optional[str]
    active_items: int
    source_stats: dict


class StatusResponse(BaseModel):
    tak_connected: bool
    tak_url: str
    tx_queue_size: int
    enablements: list[EnablementStatusItem]
    server_time: str

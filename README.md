# TAK Manager — API

[![CI](https://github.com/sheldon-st/takdata/actions/workflows/ci.yml/badge.svg)](https://github.com/sheldon-st/takdata/actions/workflows/ci.yml)
[![Image](https://github.com/sheldon-st/takdata/actions/workflows/docker-image.yml/badge.svg)](https://github.com/sheldon-st/takdata/pkgs/container/takdata)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-3776AB)

A web-based control plane for streaming live geospatial data into a [TAK Server](https://tak.gov/) as [Cursor on Target (CoT)](https://www.mitre.org/sites/default/files/pdf/09_4937.pdf) events. Operators configure data feeds (aircraft, vessels, synthetic test streams) through a browser UI; the backend manages the TAK connection, runs each feed as an async worker, and broadcasts CoT over TLS.

> **Primary README** — covers the full system. The UI lives in
> [**takdata-frontend**](https://github.com/sheldon-st/takdata-frontend), which has
> its own frontend-specific notes.

## System architecture

```
   Browser
      │  HTTPS + WebSocket
      ▼
┌───────────────────┐         ┌─────────────────────────────┐
│  takdata-frontend │  REST   │         takdata             │
│   (Next.js UI)    │ ──────▶ │   FastAPI + asyncio         │
│                   │  /api   │                             │
│                   │ ◀────── │   ┌─────────────────────┐   │
│                   │   WS    │   │ Plugin workers      │   │
│                   │ /api/ws │   │  ADS-B, AIS, synth  │   │
└───────────────────┘         │   └──────────┬──────────┘   │
                              │              │ CoT/TLS      │
                              │              ▼              │
                              │       ┌──────────────┐      │
                              │       │  TAK Server  │      │
                              │       └──────────────┘      │
                              └─────────────────────────────┘
                                       │ SQLite + .p12 certs
                                       ▼
                                     data/
```

### How the two services talk

- **REST** — frontend calls `/api/v1/*` for config (TAK server, certs, enablements, sources, packages) and lifecycle actions (`start`/`stop`).
- **WebSocket** — frontend subscribes to `/api/v1/ws/status` for live per-enablement stats, TAK connection state, and per-source poll metrics.
- **Auth** — the frontend assumes a forward-auth session cookie set by [Authentik](https://goauthentik.io/) at the reverse proxy. Backend reads `x-authentik-username` / `x-authentik-groups` headers injected by the proxy. Auth can be **disabled** for private LAN deploys via `AUTH_ENABLED=false` (see [Auth modes](#auth-modes)).

---

## Capabilities

| Area               | Description                                                                                             |
| ------------------ | ------------------------------------------------------------------------------------------------------- |
| **Data sources**   | Plugin architecture — each enablement type (ADS-B, AIS, synthetic) is a self-contained worker module    |
| **TAK connection** | Persistent TLS connection with `.p12` cert management; auto-reconnect with backoff if the link drops    |
| **Live status**    | WebSocket pushes connection state, queue depth, per-source poll counts, and per-enablement event totals |
| **Geo filters**    | Bounding-box and altitude filters per enablement; sources can be radius-scoped                          |
| **Packages**       | Upload/serve TAK data packages (`.zip`) for distribution to clients                                     |
| **REST API**       | Full OpenAPI 3 spec at `/docs`                                                                          |
| **Auth modes**     | Authentik forward-auth (default) or fully open for trusted LANs                                         |

---

## Enablement types & data sources

An **enablement** is a configured, runnable feed of one kind of data. Each
enablement type is a plugin under [`app/enablements/`](app/enablements/) that
implements the `EnablementPlugin` contract from [`base.py`](app/enablements/base.py).
A plugin owns its upstream protocol (REST poll, WebSocket subscribe, synthetic
generator) and converts whatever it receives into CoT events pushed onto the
shared TAK transmit queue.

Some plugins also publish a list of **known sources** — pre-filled URL/endpoint
templates the UI offers when you add a source — surfaced via
`GET /enablements/{id}/known-sources`.

### `adsb` — ADS-B Aircraft Tracking _(stable)_

Polls public ADS-B aggregator APIs on a per-source `sleep_interval`, deduplicates
aircraft by `uid_key` (ICAO / REG / FLIGHT), applies geo + altitude filters, and
emits one CoT track per aircraft per poll.

Known sources ([`app/enablements/adsb/plugin.py`](app/enablements/adsb/plugin.py)):

| Source                | Endpoint | Scope                                 | Needs lat/lon |
| --------------------- | -------- | ------------------------------------- | ------------- |
| ADS-B.fi — Military   | `mil`    | Worldwide military aircraft           | No            |
| ADS-B.fi — Geographic | `geo`    | All aircraft within radius of a point | Yes           |
| ADSB.lol — Point      | `point`  | Point-based query                     | Yes           |
| ADSB.lol — Military   | `mil`    | Worldwide military via ADSB.lol       | No            |

Run multiple sources under one enablement to fan out coverage (e.g. one
`geo` per region of interest plus a worldwide `mil`).

> **Future** — the current adsb.fi / adsb.lol set is the starting list, not
> the cap. Planned additions include OpenSky Network, airplanes.live,
> FlightAware Firehose (for users with credentials), and self-hosted readsb /
> tar1090 feeds. Adding one is just another entry in `KNOWN_SOURCES` plus any
> auth/header tweaks in the fetcher — no schema or UI changes needed.

### `ais` — AIS Maritime Tracking _(in development)_

Subscribes to the [aisstream.io](https://aisstream.io) WebSocket and converts
vessel position reports to CoT. Each source authenticates with its own
write-only `api_key`, falling back to the `AISSTREAM_API_KEY` environment
variable. Source modes:

| Mode (`endpoint`)               | Subscription area                                           |
| ------------------------------- | ----------------------------------------------------------- |
| Area / Radius (`geo` / `point`) | Box around source `lat`/`lon` ± `distance` (nautical miles) |
| Global (`mil`)                  | Enablement geo filter if set, otherwise the whole world     |

Known source: `aisstream.io` (WebSocket, requires a free API key).

### `synthetic` — Synthetic CoT Harness _(stable)_

Generates fabricated CoT at a precise rate to load-test a TAK server and any
downstream consumers. No upstream API — sources are not used. Workload model:

| Field                     | Meaning                                                                   |
| ------------------------- | ------------------------------------------------------------------------- |
| `feature_count` (N)       | Population of unique synthetic features                                   |
| `updates_per_second` (U)  | Tick rate in Hz                                                           |
| `features_per_update` (K) | Features touched per tick                                                 |
| `selection_strategy`      | How K features are chosen each tick: `round_robin`, `random`, `zipf`      |
| `seed_initial`            | If true, emit all N features once at startup before the steady-state loop |

Aggregate output rate = U × K events/sec.

### Assumptions about incoming source data

Sources are public third-party feeds — we don't control their schemas and the
converters are written to **tolerate variation, skip what we can't use, and
never abort the whole poll on one bad record**.

#### ADS-B (`app/enablements/adsb/`)

| Assumption                 | Detail                                                                                                                                                                                        |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Response envelope**      | JSON object with the aircraft list under either `aircraft` (adsb.fi) or `ac` (adsb.lol). Anything else → empty list, source logged as 0 aircraft.                                             |
| **Position fields**        | `lat`/`lon` (lowercase), `Lat`/`Lon`/`Lng` (capitalized), or nested under `lastPosition`. Missing position → record skipped silently.                                                         |
| **Identifier fields**      | ICAO from `hex` / `icao` / `icao_addr` / `Icao_addr`; flight from `flight` / `Tail`; reg from `reg` / `r` / `Reg`. At least one must yield a usable value — otherwise the record is skipped.  |
| **Altitude**               | `alt_geom` preferred, `alt_baro` fallback. The literal string `"ground"` is treated as on-ground (no altitude filter applied). Non-numeric values are tolerated and skip the altitude filter. |
| **Ground state**           | `OnGround` or `on_ground` (truthy) → HAE set to `pytak.DEFAULT_COT_VAL`, accuracy constants shift.                                                                                            |
| **Track / speed**          | `trk` / `track` / `Track` for course; `gs` / `Speed` for ground speed. Missing or non-numeric → default CoT values; never raises.                                                             |
| **Accuracy**               | `NACp` / `nac_p` and `NACv` / `nac_v`. Missing → 0.0 (worst-case accuracy in CoT).                                                                                                            |
| **Rate limiting / blocks** | Requests rotate through 5 desktop browser `User-Agent` strings. Non-200 responses log a warning and return an empty list; we do not retry inside one poll.                                    |
| **Failure mode**           | Any exception in the fetch logs an error and yields `[]` for that source — the next `sleep_interval` retries cleanly.                                                                         |

We do **not** assume: a stable field name, that altitude is numeric, that every
aircraft has an ICAO, that the API returns within any specific time, or that
two consecutive polls return the same set of aircraft.

#### AIS (`app/enablements/ais/`)

| Assumption          | Detail                                                                                                                                                                               |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Transport**       | aisstream.io WebSocket; we subscribe with a bounding box derived from source `lat`/`lon`/`distance` (or the geo filter). The key comes from `source.api_key` or `AISSTREAM_API_KEY`. |
| **Message shape**   | Each frame is a flattened dict of aisstream's `MetaData` + `Message`.                                                                                                                |
| **Identifier**      | `MMSI` or `UserID` required — missing → skipped.                                                                                                                                     |
| **Position**        | `Latitude` / `Longitude` required — missing → skipped.                                                                                                                               |
| **Ship type**       | `ShipType` or `Type` integer mapped to CoT type via [`_ship_type_to_cot`](app/enablements/ais/converter.py); unknown codes fall back to generic surface vessel (`a-n-S-X-L`).        |
| **Optional fields** | `ShipName` / `Name`, `CallSign`, `Sog`, `Cog`, navigational status — all best-effort; absence does not skip the record.                                                              |

#### Synthetic (`app/enablements/synthetic/`)

No external data — assumptions are entirely internal: the workload params
(N, U, K, strategy) define what's generated. The harness assumes the TAK
transmit queue can keep up with U × K events/sec; if it can't, the queue
fills, the oldest events are dropped, and `events_dropped` climbs on the WS
status feed.

#### Cross-cutting

- **Per-source isolation** — one source failing (network, schema drift, rate
  limit) never blocks another source on the same enablement, and never tears
  down the worker. The next `sleep_interval` is a clean retry.
- **Per-record isolation** — a single malformed aircraft / vessel is dropped
  with a debug log; the rest of the batch is still converted and sent.
- **No deduplication across sources** — if two sources return the same aircraft,
  both produce CoT events (same UID, the TAK client treats the later one as an
  update). Pick non-overlapping sources if you want to avoid that.
- **No upstream rate-limit handling beyond UA rotation** — pick a
  `sleep_interval` polite enough for the free tier of whatever API you target.

---

## Local development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/sheldon-st/takdata.git
cd takdata

uv sync                    # creates .venv from uv.lock
cp .env.example .env       # set AUTH_ENABLED=false for solo dev
uv run uvicorn main:app --reload --port 8000
```

- API docs: <http://localhost:8000/docs>
- SQLite DB, certs, and packages land in `./data/` (gitignored).

Run the UI alongside it from
[takdata-frontend](https://github.com/sheldon-st/takdata-frontend) (`pnpm dev`
on port 3000, which the default `CORS_ORIGINS` already allows).

### Checks

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pytest                # tests
```

CI runs all three plus a container smoke test on every pull request.

---

## Docker

```bash
docker build -t takdata .
docker run -d \
  -p 8000:8000 \
  -v "$PWD/data:/app/data" \
  --env-file .env \
  takdata
```

The image runs as an unprivileged user (uid 1001), exposes a `/healthz`
probe, and fixes ownership of volumes written by older root-run images on
start.

CI publishes multi-arch (`amd64`/`arm64`) images to
`ghcr.io/sheldon-st/takdata`:

| Trigger        | Tags                          |
| -------------- | ----------------------------- |
| Push to `main` | `latest`, `sha-<short>`       |
| Tag `vX.Y.Z`   | `X.Y.Z`, `X.Y`, `sha-<short>` |

For the full deployment behind Traefik + Authentik (or without), see
[DEPLOY.md](DEPLOY.md).

---

## Environment variables

See [.env.example](.env.example):

| Variable            | Default                     | Purpose                                                          |
| ------------------- | --------------------------- | ---------------------------------------------------------------- |
| `LOG_LEVEL`         | `INFO`                      | `DEBUG` / `INFO` / `WARNING` / `ERROR`                           |
| `CORS_ORIGINS`      | `["http://localhost:3000"]` | JSON list of allowed browser origins (unneeded when same-origin) |
| `AUTH_ENABLED`      | `true`                      | Set `false` to bypass the Authentik header check                 |
| `DATA_DIR`          | `data`                      | Path for SQLite DB + uploaded certs/packages                     |
| `AISSTREAM_API_KEY` | —                           | Fallback key for AIS sources that don't set their own            |

---

## Auth modes

The backend supports two modes via `AUTH_ENABLED`:

**`AUTH_ENABLED=true` (default)** — production / multi-user

- Backend trusts `x-authentik-username` and `x-authentik-groups` headers injected by the reverse proxy.
- Group `tak-manager-admin` → admin (full read/write). `tak-manager-viewer` → read-only. Anything else → 403.
- Missing headers → 401.
- Frontend shows the Authentik sign-out link.

**`AUTH_ENABLED=false`** — single-operator / private LAN

- Backend returns `{username: "anonymous", role: "admin"}` for every request without checking headers.
- Frontend auto-detects via `/api/v1/me` and hides the sign-out link.
- No login required — **anyone with network reach has full admin**. Firewall/VPN/Tailscale required.

> **Security** — with auth enabled the backend trusts identity headers
> blindly. Never expose port 8000 directly; only the reverse proxy should
> reach it, and the proxy must overwrite (not pass through) any
> client-supplied `x-authentik-*` headers.

> **Future** — auth is currently hard-wired to the Authentik forward-auth
> header contract (`x-authentik-username`, `x-authentik-groups`,
> `tak-manager-admin` / `tak-manager-viewer`). The plan is to abstract this
> into a pluggable provider interface so operators can drop in alternatives
> (Cloudflare Access, oauth2-proxy, plain OIDC, mTLS, static API keys) by
> implementing a small adapter — without code changes to the routes or the
> `require_admin` / `require_viewer` deps. `AUTH_ENABLED=false` will remain
> as the explicit "no auth" provider.

---

## API surface

All routes under `/api/v1/`:

| Group             | Endpoints                                                                                                                  |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **Auth**          | `GET /me`                                                                                                                  |
| **TAK server**    | `GET/PUT /tak/config`, `POST /tak/connect`, `POST /tak/disconnect`, `GET /tak/status`                                      |
| **Certificates**  | `GET /tak/certs`, `POST /tak/certs`, `DELETE /tak/certs/{id}`                                                              |
| **Enablements**   | `GET/POST /enablements`, `GET/PUT/DELETE /enablements/{id}`, `POST /enablements/{id}/start\|stop`, `GET /enablement-types` |
| **Sources**       | `GET/POST /enablements/{id}/sources`, `PUT/DELETE /enablements/{id}/sources/{sid}`                                         |
| **Packages**      | `GET/POST /packages`, `GET/DELETE /packages/{id}`                                                                          |
| **Status**        | `GET /status`, `WS /ws/status`                                                                                             |
| **Known sources** | `GET /enablements/{id}/known-sources`                                                                                      |

Outside the prefix: `GET /healthz` (unauthenticated liveness probe). Full
spec at `/docs` when the backend is running.

---

## Data model & runtime

Three SQLite tables hold all configuration; live worker state is in memory.
Schema in [`app/models/db.py`](app/models/db.py), Pydantic shapes in
[`app/models/schemas.py`](app/models/schemas.py).

```
   tak_config (singleton)            enablements (1..N)            sources (0..N per enablement)
┌─────────────────────────┐       ┌──────────────────────┐       ┌──────────────────────┐
│ cot_url                 │       │ id                   │       │ id                   │
│ cert_path / password    │       │ type_id  ─── plugin  │       │ enablement_id  ──FK──┤
│ cot_host_id             │       │ name                 │       │ name                 │
│ dont_check_hostname     │       │ enabled              │       │ base_url             │
│ dont_verify             │       │ cot_stale            │       │ endpoint             │
│ max_out_queue / in      │       │ alt_upper / lower    │       │ sleep_interval       │
└─────────────────────────┘       │ uid_key              │       │ lat / lon / distance │
                                   │ geo_filter_min/max…  │       │ api_key (write-only) │
                                   │ feature_count        │       │ enabled              │
                                   │                      │       └──────────────────────┘
                                   │ updates_per_second   │
                                   │ features_per_update  │       ON DELETE CASCADE
                                   │ selection_strategy   │
                                   │ seed_initial         │
                                   └──────────────────────┘
```

### `tak_config` — TAK server connection (one row)

How the backend reaches the TAK server: CoT URL (`tls://host:port`), client
`.p12` cert path + password, the host ID stamped into outbound CoT, TLS
verification toggles, and inbound/outbound queue depths. Edited via
`PUT /tak/config`; applied on `POST /tak/connect`.

### `enablements` — one configured feed (1..N rows)

Each row is one runnable instance of a plugin (`type_id` picks which one).
Common fields apply to every type:

| Field                        | Purpose                                                            |
| ---------------------------- | ------------------------------------------------------------------ |
| `type_id`                    | Selects the plugin (`adsb`, `ais`, `synthetic`)                    |
| `name`                       | UI label                                                           |
| `enabled`                    | If true and restorable on startup, auto-starts after a restart     |
| `cot_stale`                  | Seconds before a TAK client treats the track as stale              |
| `alt_upper` / `alt_lower`    | Altitude band filter in feet (0 = disabled)                        |
| `uid_key`                    | Which upstream field becomes the CoT UID (`ICAO`, `REG`, `FLIGHT`) |
| `geo_filter_min/max_lat/lon` | Bounding-box filter; all four required to enable                   |

Synthetic-only fields (`feature_count`, `updates_per_second`, etc.) sit on the
same table for schema simplicity — they're null for non-synthetic rows.

### `sources` — where data comes from (0..N per enablement)

A source is one upstream endpoint a poll/subscribe task targets. Plugins like
`adsb` and `ais` use them; `synthetic` ignores them.

| Field                      | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `base_url` + `endpoint`    | Upstream API root + query mode (`geo`/`point`/`mil`) |
| `api_key`                  | Credential, never returned (`has_api_key` instead)   |
| `sleep_interval`           | Poll cadence in seconds (poll-based plugins)         |
| `lat` / `lon` / `distance` | Area-of-interest for geographic queries              |
| `enabled`                  | Lets you pause one source without deleting it        |

Cascading delete: removing an enablement removes its sources.

### Runtime — how a row becomes CoT

[`RuntimeManager`](app/core/runtime_manager.py) is the module-level singleton
that owns the TAK connection and the live plugin instances:

1. **Connect** — `POST /tak/connect` reads `tak_config` and opens a `pytak`
   TLS session. `RuntimeManager._tx_queue` is the shared outbound CoT queue.
2. **Start an enablement** — `POST /enablements/{id}/start` loads the row plus
   its sources, looks up the plugin class via `get_plugin_class(type_id)`,
   instantiates `PluginClass(enablement_id, config, tx_queue)`, and calls
   `await plugin.start()`. The plugin spawns its own asyncio tasks.
3. **Push CoT** — the plugin's worker fetches/generates data, applies the
   filters on the enablement row, builds CoT bytes, and hands them to
   `emit_cot()`. That never blocks: when the queue is full it drops the oldest
   event and counts it in `events_dropped`. `pytak`'s TX worker drains the
   queue to the TAK server.
4. **Stats** — `EnablementStats` (events_sent, events_dropped, last_poll_time, last_error,
   active_items, per-source breakdown) is sampled by the WebSocket broadcaster
   every ~2s and pushed to subscribed UI clients via `/api/v1/ws/status`.
5. **Stop** — `POST /enablements/{id}/stop` calls `plugin.stop()`, which
   cancels its tasks; the row stays in the DB.
6. **Edit while running** — updating an enablement triggers
   `plugin.on_config_updated(new_config)` (default: stop + restart).
7. **Restart recovery** — on app startup, [`restore_active_enablements`](app/services/enablement_service.py)
   re-starts every row with `enabled = 1`.
8. **Link supervision** — a supervisor task watches `pytak`'s TX/RX workers.
   If one dies (rejected cert, TLS alert, dropped socket) it marks the
   connection down, reports the reason as `connect_error`, reconnects with
   backoff (5 → 60 s), and rebuilds every running enablement on the new
   queue.

### Plugin contract (one-paragraph version)

A plugin sets `TYPE_ID`/`DISPLAY_NAME`/`DESCRIPTION` class vars, registers
itself with `@register`, and implements `start()`, `stop()`, and `get_stats()`.
It receives the enablement row (plus its sources) as `config` and the shared
`asyncio.Queue` for outbound CoT. Everything else — schema, routes, runtime
plumbing — is reused. See [Adding a new enablement plugin](#adding-a-new-enablement-plugin).

---

## Repo layout

```
takdata/
├── main.py                    FastAPI entrypoint (+ /healthz, /api/v1/me)
├── pyproject.toml / uv.lock   Dependencies, ruff + pytest config
├── Dockerfile                 Non-root runtime image
├── docker-entrypoint.sh       Volume ownership fix + privilege drop
├── .env.example
├── app/
│   ├── api/
│   │   ├── deps.py            Auth + DB dependencies
│   │   └── routes/            HTTP + WebSocket handlers
│   ├── core/
│   │   ├── config.py          Settings (env-driven)
│   │   └── runtime_manager.py TAK connection + worker lifecycle
│   ├── models/                SQLite schema + Pydantic models
│   ├── services/              Business logic + file storage
│   └── enablements/
│       ├── base.py            Plugin base class + emit_cot()
│       ├── registry.py        Plugin registry
│       ├── adsb/              ADS-B plugin
│       ├── ais/               AIS plugin
│       └── synthetic/         Synthetic load-test harness
├── tests/                     pytest suite
├── DEPLOY.md
└── data/                      Runtime — SQLite, certs, packages (gitignored)
```

---

## Adding a new enablement plugin

1. Create `app/enablements/<type>/`.
2. Implement the `EnablementPlugin` base class from [`app/enablements/base.py`](app/enablements/base.py).
3. Register with the `@register` decorator in [`app/enablements/registry.py`](app/enablements/registry.py).
4. Import the package in [`app/enablements/__init__.py`](app/enablements/__init__.py).
5. Push CoT with `await emit_cot(self.tx_queue, cot_bytes, stats)`.
6. Plugin appears automatically in `GET /enablement-types` and the UI.

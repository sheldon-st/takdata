# TAK Manager — Frontend Build Brief

> Provide this document alongside the OpenAPI spec (`GET /openapi.json`) to the AI building the frontend.

---

## What this app is

TAK Manager is a web UI for managing real-time data streams into a **TAK server** (Team Awareness Kit — a military/first-responder situational awareness platform). Users configure which data "enablements" are active (e.g. ADS-B aircraft tracking), where to pull data from, and monitor the live status of those streams.

The backend is a **FastAPI** app (`/api/v1/...`) with a **WebSocket** for live status. All config is persisted in SQLite. The app runs as a Docker container alongside a TAK server.

---

## Tech stack recommendation

- **React 18**
- **TypeScript**
- **TanStack Query** (server state, polling, mutations)
- **React Router v6** (SPA routing)
- **Tailwind CSS** + **shadcn/ui** components (or similar headless library)
- **Zod** for form validation (schemas mirror the OpenAPI models)
- Native browser **WebSocket** (or a small hook wrapper) for live status

---

## Core concepts (translate these to UI)

| Term | Meaning |
|------|---------|
| **TAK Server** | The destination server that receives CoT events. Has a URL (`tls://host:8089`) and a TLS client certificate (`.p12` file). |
| **Enablement** | A named, configured instance of a data stream type (e.g. "My ADS-B Feed"). Can be started/stopped independently. |
| **Enablement type** | A plugin registered in the backend (e.g. `adsb`, `ais`). The catalog is returned by `GET /enablement-types`. |
| **Source** | A specific API endpoint an enablement polls (e.g. opendata.adsb.fi military feed). One enablement can have multiple sources running in parallel. |
| **running** | Whether the enablement's worker is actively polling and sending data right now. Distinct from `enabled` (persisted DB flag). |
| **CoT** | Cursor on Target — the XML event format TAK uses. The backend handles all CoT conversion; the UI never deals with it. |

---

## Pages / views

### 1. Dashboard (default route `/`)

The landing page. Shows system health at a glance.

**Sections:**
- **TAK Connection status** — connected/disconnected badge, server URL, TX queue size. "Connect" / "Disconnect" buttons.
- **Enablements list** — card or table row per enablement showing: name, type badge, running state (green dot / grey dot), live item count (`active_items` — aircraft for ADS-B), events sent, last error if any.
- All data driven from the **WebSocket** (`WS /api/v1/ws/status`) which pushes updates every 2 seconds.

**Actions from dashboard:**
- Toggle start/stop on each enablement inline.
- Navigate to enablement detail.
- Navigate to TAK server settings.

---

### 2. TAK Server Settings (`/settings/tak`)

Configure the connection to the TAK server.

**Form fields:**

| Field | Input type | Notes |
|-------|-----------|-------|
| `cot_url` | Text | e.g. `tls://10.0.0.5:8089` |
| Certificate | Select from uploaded certs | Shows `cert_id` + `filename`. Empty = no cert. |
| `cert_password` | Password | Write-only — never returned by API |
| `cot_host_id` | Text | Identifier embedded in every CoT event |
| `dont_check_hostname` | Toggle | Default on for internal networks |
| `dont_verify` | Toggle | Default on for internal networks |
| `max_out_queue` | Number | Advanced — default 1000 |
| `max_in_queue` | Number | Advanced — default 1000 |

**Certificate sub-section:**
- List of uploaded `.p12` certs (from `GET /tak/certs`).
- Upload button → file picker filtered to `.p12` → `POST /tak/certs` (multipart).
- Delete button per cert.
- Selecting a cert from the list sets `cert_path` in the TAK config form.

**Save** → `PUT /tak/config`
**Connect / Reconnect** → `POST /tak/connect` (shown inline as a status action)

---

### 3. Enablements (`/enablements`)

List all configured enablement instances with management controls.

**Layout:** Card grid or table. Each card shows:
- Name + type badge (e.g. "ADS-B")
- Running indicator (animated pulse if running)
- `active_items` count (e.g. "42 aircraft")
- Start / Stop button
- Edit button → opens detail
- Delete button (with confirmation)

**"New Enablement" button** → opens a modal or drawer:
1. Select enablement type from `GET /enablement-types` (renders display_name + description)
2. Fill in name + config fields (see per-type fields below)
3. Submit → `POST /enablements`

---

### 4. Enablement Detail (`/enablements/:id`)

Full configuration for a single enablement.

**Tabs or sections:**

#### General settings
- Name (editable)
- `cot_stale` — CoT stale time in seconds (how long the track persists on a TAK client after the last update)
- `uid_key` — dropdown: `ICAO` / `REG` / `FLIGHT` (how aircraft are identified in CoT)
- `alt_upper` / `alt_lower` — altitude filter in feet, 0 = disabled. Show as a range input or two number fields. Label them clearly: "Only show aircraft below X ft" / "Only show aircraft above Y ft"

**`PUT /enablements/:id`** on save. If the enablement is running, the backend hot-reloads it automatically.

#### Sources
List of polling sources for this enablement. Each row shows:
- Name, URL, endpoint type badge (`mil` / `geo` / `point`), interval, lat/lon if set, enabled toggle.
- Edit inline or in a side panel.
- Delete (with confirmation).

**"Add Source" button** → two options:
1. **From template** — loads `GET /enablements/:id/known-sources` and renders a picker of pre-configured options (e.g. "ADS-B.fi — Military"). Selecting one pre-fills the form.
2. **Custom** — blank form.

Source form fields:

| Field | Input | Notes |
|-------|-------|-------|
| `name` | Text | Friendly label |
| `base_url` | Text | API base URL |
| `endpoint` | Select | `geo` / `point` / `mil` |
| `sleep_interval` | Number (seconds) | How often to poll |
| `lat` / `lon` | Number | Required if endpoint is `geo` or `point`. Show/hide based on endpoint selection. |
| `distance` | Number (nm) | Required if endpoint is `geo` or `point`. |
| `enabled` | Toggle | |

`POST /enablements/:id/sources` to add, `PUT /enablements/:id/sources/:sid` to update.

#### Live status panel
Pulled from the WebSocket. Shows for this specific enablement:
- Running status
- Total events sent
- Last poll time
- Last error (highlighted in red if present)
- Per-source stats table: source name | last poll | item count

---

## WebSocket — live status

Connect on app load. URL: `ws://<host>/api/v1/ws/status`

The server pushes a JSON message every **2 seconds**:

```json
{
  "tak_connected": true,
  "tak_url": "tls://10.0.0.5:8089",
  "tx_queue_size": 3,
  "connect_error": null,
  "enablements": [
    {
      "id": 1,
      "name": "My ADS-B Feed",
      "type_id": "adsb",
      "running": true,
      "events_sent": 4821,
      "last_poll_time": "2024-01-15T12:00:00",
      "last_error": null,
      "active_items": 42,
      "source_stats": {
        "adsb.fi-mil": { "last_poll": "2024-01-15T12:00:00", "aircraft_count": 15 },
        "adsb.lol-regional": { "last_poll": "2024-01-15T12:00:00", "aircraft_count": 27 }
      }
    }
  ],
  "server_time": "2024-01-15T12:00:01"
}
```

**Recommended approach:** A single global WebSocket connection held in a React context. Components subscribe to the pieces of state they need. On disconnect, attempt reconnect with exponential backoff.

The WebSocket data is **read-only live status**. All mutations (start, stop, configure) use REST endpoints.

---

## Key user flows

### First-time setup
1. Open app → Dashboard shows "Not connected" state.
2. Navigate to TAK Server Settings.
3. Upload `.p12` cert → select it from list → enter password → save.
4. Enter TAK server URL → Save → Connect.
5. Dashboard updates to "Connected".

### Add an ADS-B feed
1. Navigate to Enablements → "New Enablement".
2. Select "ADS-B Aircraft Tracking".
3. Name it (e.g. "Military + NYC Area"), configure stale time etc. → Create.
4. On the detail page → Sources tab → "Add Source" → pick "ADS-B.fi — Military" template → Save.
5. Add another source → pick "ADS-B.fi — Geographic" → enter lat/lon/distance → Save.
6. Click "Start" → Dashboard shows running indicator + aircraft count incrementing.

### Stop/reconfigure a running feed
1. Dashboard or Enablements list → Stop the enablement.
2. Go to detail → change polling interval or altitude filter → Save.
3. Backend hot-reloads if the enablement is running (no need to manually restart).
4. Start again.

---

## API base URL

Use an environment variable:   (default `http://localhost:8000`).

WebSocket URL: replace `http` → `ws` / `https` → `wss`.

All REST endpoints are prefixed `/api/v1/`.

Full interactive docs available at `GET /docs` (Swagger UI) during development.

---

## Error handling conventions

- **4xx** — show inline form errors or toast notifications. The API returns `{"detail": "..."}` on errors.
- **422 Unprocessable Entity** — Pydantic validation failure. Body contains `{"detail": [{"loc": [...], "msg": "..."}]}`. Map `loc` to field-level errors.
- **502** on `POST /tak/connect` — TAK server unreachable. Show the `detail` string (includes the raw connection error).
- **WebSocket disconnect** — show a "Reconnecting..." banner. Don't show stale data as live.

---

## State management notes

- **Server state** (enablements list, TAK config, certs): TanStack Query. Invalidate on mutations.
- **Live status** (running, item counts, errors): WebSocket context, updated in-place every 2s.
- **UI state** (modals, selected items): local component state or Zustand.
- The `running` field on `EnablementResponse` is a live snapshot merged at request time from RuntimeManager — treat it as potentially stale compared to the WebSocket feed.

---

## Enablement-specific UI notes

### ADS-B (`type_id: "adsb"`)
- `active_items` = number of unique aircraft currently tracked (deduplicated across all sources)
- `source_stats` key = source name, value = `{ last_poll, aircraft_count }`
- Altitude filter fields (`alt_upper`, `alt_lower`): show as "Max altitude (ft)" and "Min altitude (ft)" with helper text "0 = no filter"
- `uid_key` options: `ICAO` (hex address — most stable), `REG` (registration, e.g. N12345), `FLIGHT` (callsign — changes per flight)

### AIS (`type_id: "ais"`)
- Currently a stub — backend will log a warning if started. Show a "Coming soon" badge on this type in the UI. Allow creating/configuring but grey out the Start button.

---

## Repo structure context

```
adsb-to-cot/
├── backend/          ← FastAPI backend (Python)
│   ├── main.py
│   └── app/...
└── frontend/         ← React app goes here (to be created)
    ├── src/
    └── ...
```

Place the React app at `adsb-to-cot/frontend/`. The backend runs on port `8000` by default; the dev server can proxy `/api` to avoid CORS issues during development.

---

## What NOT to build (backend handles it)

- CoT XML generation — purely backend
- ADS-B API polling — purely backend
- TLS/certificate crypto — backend uses pytak
- Deduplication logic — backend
- Any direct connection to the TAK server

The frontend is a pure management UI: configure, start/stop, observe.

# TAK Manager

A web-based management platform for configuring and monitoring real-time data streams into a [TAK Server](https://tak.gov/). Designed for operators who need a simple interface to connect live feeds (aircraft tracking, maritime AIS, etc.) and broadcast them as [Cursor on Target (CoT)](https://www.mitre.org/sites/default/files/pdf/09_4937.pdf) events to TAK clients.

## Features

- **Plugin-based data sources** — Extensible architecture supporting multiple feed types (ADS-B, AIS, and more)
- **TAK Server integration** — Secure TLS connections with `.p12` certificate management
- **Live status streaming** — WebSocket-based real-time status updates every 2 seconds
- **REST API** — Full OpenAPI spec available at `/docs`
- **Docker-ready** — Multi-platform images (amd64/arm64) published to GHCR

## Supported Enablements

| Type | Description | Status |
|------|-------------|--------|
| **ADS-B** | Aircraft position tracking via adsb.fi / adsb.lol | Stable |
| **AIS** | Maritime vessel tracking via aisstream.io | In development |

## Architecture

```
                 ┌──────────────────────┐
                 │   React Frontend      │
                 │  (Tailwind + shadcn)  │
                 └──────────┬───────────┘
                            │ HTTP / WS
                 ┌──────────▼───────────┐
                 │   FastAPI Backend     │
                 │  (Python + asyncio)   │
                 │                       │
                 │  ┌─────────────────┐  │
                 │  │  Plugin Workers  │  │
                 │  │  (ADS-B / AIS)  │  │
                 │  └────────┬────────┘  │
                 └───────────┼───────────┘
                             │ CoT over TLS
                  ┌──────────▼───────────┐
                  │      TAK Server       │
                  └───────────────────────┘
```

## Getting Started

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for containerized deployment)

### Local Development

```bash
# Clone the repo
git clone https://github.com/<your-org>/takdata.git
cd takdata/backend

# Create and activate virtualenv
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the dev server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Docker (Local)

```bash
cd backend
docker compose up -d
```

### Environment Variables

Copy `.env.example` to `.env` and adjust as needed:

```env
LOG_LEVEL=INFO          # DEBUG | INFO | WARNING | ERROR
CORS_ORIGINS=["*"]      # Restrict in production
HOST_PORT=80            # Frontend listen port
```

## API Overview

All routes are prefixed with `/api/v1/`.

| Group | Endpoints |
|-------|-----------|
| **TAK Server** | `GET/PUT /tak/config`, `POST /tak/connect`, `POST /tak/disconnect` |
| **Certificates** | `GET/POST/DELETE /tak/certs/{cert_id}` |
| **Enablements** | `GET/POST /enablements`, `POST /enablements/{id}/start\|stop` |
| **Sources** | `POST/PUT/DELETE /enablements/{id}/sources/{sid}` |
| **Status** | `GET /status`, `WS /ws/status` |

See the full spec at `/docs` when the backend is running.

## Production Deployment

See [DEPLOY.md](DEPLOY.md) for a complete VPS deployment guide, including:

- Pulling pre-built images from GHCR
- Environment configuration
- Firewall setup
- Optional automatic HTTPS with Caddy
- Data persistence and backup

Quick start on a VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/<your-org>/takdata/main/docker-compose.yml -o docker-compose.yml
docker compose pull
docker compose up -d
```

## Project Structure

```
takdata/
├── backend/
│   ├── main.py                        # FastAPI entrypoint
│   ├── requirements.txt
│   ├── app/
│   │   ├── api/routes/                # HTTP + WebSocket endpoints
│   │   ├── core/
│   │   │   ├── config.py              # Settings
│   │   │   └── runtime_manager.py     # TAK connection + worker lifecycle
│   │   ├── models/                    # SQLite schema + Pydantic schemas
│   │   ├── services/                  # Business logic
│   │   └── enablements/
│   │       ├── base.py                # Plugin base class
│   │       ├── registry.py            # Plugin registry
│   │       ├── adsb/                  # ADS-B plugin
│   │       └── ais/                   # AIS plugin
│   └── data/                          # Runtime data (DB, certs) — gitignored
├── frontend/                          # React SPA (in progress)
├── docker-compose.yml                 # Production compose
├── DEPLOY.md                          # Deployment guide
└── frontend-build-brief.md            # Frontend spec
```

## Adding a New Enablement Plugin

1. Create a directory under `backend/app/enablements/<type>/`
2. Implement the `EnablementPlugin` base class from `enablements/base.py`
3. Register the plugin with the `@register` decorator in `enablements/registry.py`
4. The plugin will automatically appear in `GET /enablement-types` and the UI

## CI/CD

On push to `main`, GitHub Actions builds and publishes multi-platform Docker images (`linux/amd64`, `linux/arm64`) to the GitHub Container Registry (GHCR).

## License

See [LICENSE](LICENSE) for details.

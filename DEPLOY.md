# TAK Manager — VPS Deployment Guide

Deploy TAK Manager (backend API + frontend) on a VPS using pre-built Docker
images from GitHub Container Registry (GHCR), behind Traefik (Dokploy) with
single-host path routing.

---

## Architecture on the VPS

```
Internet :80 / :443
  │
  ▼
┌──────────────────────────────────────────────┐
│ Traefik (Dokploy)                            │
│ • TLS termination (Let's Encrypt)            │
│ • routes by Host + PathPrefix                │
└────────┬─────────────────────┬───────────────┘
         │ Host(data...)       │ Host(data...) && PathPrefix(/api)
         ▼                     ▼
┌──────────────────────┐ ┌──────────────────────┐
│ frontend (Next.js)   │ │ backend (FastAPI)    │
│ • SSR + static       │ │ • REST + WebSocket   │
└──────────────────────┘ │ • SQLite + certs     │
                         └──────────────────────┘
```

Both services are exposed behind `https://data.opengeo.space`. Traefik routes
`/api` requests to the backend and everything else to the frontend.

---

## Prerequisites

- VPS running Ubuntu 22.04+/Debian 12+ (AMD64 or ARM64 — images are multi-arch).
- DNS A record:
  - `data.opengeo.space` → VPS IP
- Dokploy + Traefik deployed and handling `web`/`websecure` entrypoints.
- Docker installed.

---

## Step 1 — Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker --version && docker compose version
```

---

## Step 2 — Make GHCR images accessible

Images are at `ghcr.io/sheldon-st/takdata` and `ghcr.io/sheldon-st/takdata-frontend`.
Either make the packages public (recommended) or `docker login ghcr.io` with a
PAT having `read:packages`.

---

## Step 3 — Configure Traefik routers (single host path split)

Create two routers in Dokploy:

- Frontend router:
  - Rule: `Host(\`data.opengeo.space\`)`
  - Service port: `3000`
  - Middleware: `authentik-fwd@docker`
- Backend router:
  - Rule: `Host(\`data.opengeo.space\`) && PathPrefix(\`/api\`)`
  - Service port: `8000`
  - Middleware: `authentik-fwd@docker`
  - Priority: higher than frontend (for example `100`)

Traefik's Let's Encrypt resolver on `websecure` handles certificates.

---

## Step 4 — Deploy the stack

```bash
mkdir -p ~/tak-manager && cd ~/tak-manager

curl -fsSL https://raw.githubusercontent.com/sheldon-st/takdata/main/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/sheldon-st/takdata/main/.env.example -o .env
nano .env
```

| Variable | Default | Notes |
|----------|---------|-------|
| `LOG_LEVEL` | `INFO` | `DEBUG` for troubleshooting |
| `CORS_ORIGINS` | `["https://data.opengeo.space"]` | Frontend origin |

Pull and start:

```bash
docker compose pull
docker compose up -d
docker compose ps
```

Backend listens on `:8000`; frontend on `:3000` in their containers. Traefik
proxies both under `data.opengeo.space` using path-based routing.

---

## Step 5 — Firewall

Already opened by `vps-infra/firewall/setup-ufw.sh` (ports 80, 443). No extra
ports needed — container ports are not exposed publicly.

---

## Updating

```bash
cd ~/tak-manager
docker compose pull
docker compose up -d
```

Only changed images restart. `tak-data` volume (SQLite + certs) is preserved.

---

## Logs

```bash
docker compose logs -f          # all
docker compose logs -f backend  # API
docker compose logs -f frontend # Next.js
```

---

## Data persistence

All state lives in the `tak-data` named volume:

- `config.db` — SQLite (config, enablements, sources)
- `certs/` — uploaded `.p12` client certs

Backup:

```bash
docker run --rm \
  -v tak-manager_tak-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/tak-data-backup.tar.gz /data
```

Restore:

```bash
docker run --rm \
  -v tak-manager_tak-data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/tak-data-backup.tar.gz -C /
```

---

## CI/CD

```
git push main
  └── GitHub Actions builds:
       ├── ghcr.io/sheldon-st/takdata:latest
       └── ghcr.io/sheldon-st/takdata-frontend:latest
            └── on VPS: docker compose pull && docker compose up -d
```

Tags: `:latest` and `:sha-<commit>`. Pin by editing `docker-compose.yml`.

---

## Troubleshooting

**Backend won't start** — `docker compose logs backend`. Usually volume perms or corrupt SQLite.

**Frontend blank / 404 on refresh** — Next standalone serves SPA fallback. Check `docker compose logs frontend`.

**WebSocket "Reconnecting..."** — confirm backend router uses
`Host(\`data.opengeo.space\`) && PathPrefix(\`/api\`)` and forwards WS upgrades.
Check backend logs.

**502 from nginx** — container not running or not bound to `127.0.0.1:<port>`. `docker compose ps` + `ss -tlnp | grep -E '3000|8000'`.

**Cert error** — re-run certbot (Step 3). Auto-renew: `sudo systemctl status certbot.timer`.

**Cannot pull image (403)** — package private. Make public or `docker login ghcr.io`.

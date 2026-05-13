# TAK Manager — VPS Deployment Guide

Deploy TAK Manager (backend API + frontend) on a VPS using pre-built Docker
images from GitHub Container Registry (GHCR), behind the host nginx managed
by [`vps-infra`](../vps-infra).

---

## Architecture on the VPS

```
Internet :80 / :443
  │
  ▼
┌──────────────────────────────────────────────┐
│ host nginx  (managed by vps-infra)           │
│ • TLS termination (Let's Encrypt / certbot)  │
│ • routes by Host header                      │
└────────┬─────────────────────┬───────────────┘
         │ 127.0.0.1:3000      │ 127.0.0.1:8000
         ▼                     ▼
  data.opengeo.space     api.data.opengeo.space
┌──────────────────────┐ ┌──────────────────────┐
│ frontend (Next.js)   │ │ backend (FastAPI)    │
│ • SSR + static       │ │ • REST + WebSocket   │
└──────────────────────┘ │ • SQLite + certs     │
                         └──────────────────────┘
```

Containers bind only to `127.0.0.1`. Nginx fronts them and handles TLS.
The SPA calls the backend cross-origin at `api.data.opengeo.space`; CORS
on the backend allows `https://data.opengeo.space`.

---

## Prerequisites

- VPS running Ubuntu 22.04+/Debian 12+ (AMD64 or ARM64 — images are multi-arch).
- DNS A records:
  - `data.opengeo.space` → VPS IP
  - `api.data.opengeo.space` → VPS IP
- `vps-infra` deployed (nginx, firewall, systemd). See `../vps-infra/README.md`.
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

## Step 3 — Issue TLS certificates

Nginx config in `vps-infra/nginx/nginx.conf` expects certs at:

- `/etc/letsencrypt/live/data.opengeo.space/`
- `/etc/letsencrypt/live/api.data.opengeo.space/`

Issue them with certbot (the nginx `:80` server blocks serve the
`/.well-known/acme-challenge/` path from `/var/www/certbot`):

```bash
sudo apt install -y certbot
sudo mkdir -p /var/www/certbot

sudo certbot certonly --webroot -w /var/www/certbot \
  -d data.opengeo.space \
  -d api.data.opengeo.space
```

Then reload nginx:

```bash
sudo systemctl reload nginx
```

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

Backend listens on `127.0.0.1:8000`; frontend on `127.0.0.1:3000`. Host nginx
proxies the public domains to them.

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

**WebSocket "Reconnecting..."** — confirm nginx WS upgrade headers in `vps-infra/nginx/nginx.conf` `api.data.opengeo.space` block (`Upgrade`/`Connection`). Check backend logs.

**502 from nginx** — container not running or not bound to `127.0.0.1:<port>`. `docker compose ps` + `ss -tlnp | grep -E '3000|8000'`.

**Cert error** — re-run certbot (Step 3). Auto-renew: `sudo systemctl status certbot.timer`.

**Cannot pull image (403)** — package private. Make public or `docker login ghcr.io`.

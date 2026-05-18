# TAK Manager — VPS Deployment Guide

Deploy the TAK Manager backend on a VPS using the prebuilt image from GHCR. Frontend is deployed separately from the [`takdata-frontend`](../takdata-frontend) repo.

---

## Architecture

```
Internet :443
  │
  ▼
┌─────────────────────────────────────────┐
│ Traefik / nginx / Caddy                 │
│ • TLS termination                       │
│ • routes Host + PathPrefix              │
│ • (optional) Authentik forward-auth     │
└────────┬────────────────────┬───────────┘
         │ Host(data...)      │ Host(data...) && PathPrefix(/api)
         ▼                    ▼
┌──────────────────┐  ┌──────────────────┐
│  takdata-frontend │  │  takdata backend │
│  (Next.js :3000)  │  │  (FastAPI :8000) │
└──────────────────┘  └────────┬─────────┘
                                │
                                ▼
                          tak-data volume
                          (SQLite + certs)
```

`data.opengeo.space/api/*` → backend; everything else → frontend.

---

## Prerequisites

- VPS with Docker (Ubuntu 22.04+ / Debian 12+; amd64 or arm64 — image is multi-arch).
- DNS `A` record for your public hostname.
- A reverse proxy of your choice (Traefik/Dokploy, nginx, Caddy) handling TLS.
- (Optional) Authentik for SSO — see [Auth modes](#auth-modes).

---

## 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

---

## 2. Pull and run the backend

```bash
mkdir -p ~/tak-manager && cd ~/tak-manager
curl -fsSL https://raw.githubusercontent.com/sheldon-st/takdata/main/.env.example -o .env
nano .env

docker pull ghcr.io/sheldon-st/takdata:latest
docker run -d \
  --name takdata \
  --restart unless-stopped \
  -p 127.0.0.1:8001:8000 \
  -v tak-data:/app/data \
  --env-file .env \
  ghcr.io/sheldon-st/takdata:latest
```

| Variable | Default | Notes |
|----------|---------|-------|
| `LOG_LEVEL` | `INFO` | `DEBUG` for troubleshooting |
| `CORS_ORIGINS` | `["https://data.opengeo.space"]` | Frontend origin |
| `AUTH_ENABLED` | `true` | Set `false` to skip Authentik header check |

Bind to `127.0.0.1:8001` so only the reverse proxy can reach it.

---

## 3. Front it with a reverse proxy

### Traefik / Dokploy

Two routers on the same host:

| Router | Rule | Service port | Middleware |
|--------|------|--------------|------------|
| frontend | `Host(\`data.opengeo.space\`)` | `3000` (frontend container) | `authentik-fwd@docker` (optional) |
| backend | `Host(\`data.opengeo.space\`) && PathPrefix(\`/api\`)` (priority 100) | `8000` (backend container) | `authentik-fwd@docker` (optional) |

Let's Encrypt resolver on `websecure` handles certs.

### nginx (minimal)

```nginx
server {
  listen 443 ssl http2;
  server_name data.opengeo.space;

  location /api/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
  }

  location / {
    proxy_pass http://127.0.0.1:3001;   # frontend
    proxy_set_header Host $host;
  }
}
```

---

## Auth modes

### Authentik forward-auth (default)

Attach `authentik-fwd@docker` (or your equivalent forward-auth middleware) to both routers. Authentik injects `x-authentik-username` and `x-authentik-groups` headers; the backend reads them. Group `tak-manager-admin` → admin, `tak-manager-viewer` → read-only.

### No auth — private LAN

For trusted single-operator deploys, set `AUTH_ENABLED=false` in `.env` and skip the forward-auth middleware. Backend treats every caller as admin.

> ⚠️ **No auth = full admin to anyone with network reach.** Only run this behind a firewall, VPN, or Tailscale — never on a public address.

The frontend auto-detects this mode via `GET /api/v1/me` (response includes `auth_enabled: false`) and hides the Authentik sign-out link.

---

## Updating

```bash
docker pull ghcr.io/sheldon-st/takdata:latest
docker rm -f takdata
# re-run the `docker run` from step 2 — the `tak-data` volume is preserved
```

---

## Logs

```bash
docker logs -f takdata
```

---

## Data persistence

All state lives in the `tak-data` named volume:

- `config.db` — SQLite (config, enablements, sources)
- `certs/` — uploaded `.p12` client certs
- `packages/` — uploaded TAK data packages

**Backup**

```bash
docker run --rm \
  -v tak-data:/data \
  -v "$PWD":/backup \
  alpine tar czf /backup/tak-data-backup.tar.gz /data
```

**Restore**

```bash
docker run --rm \
  -v tak-data:/data \
  -v "$PWD":/backup \
  alpine tar xzf /backup/tak-data-backup.tar.gz -C /
```

---

## CI/CD

`git push main` → GitHub Actions builds and publishes `ghcr.io/sheldon-st/takdata:latest` and `:sha-<commit>` (linux/amd64 + linux/arm64). Pin a specific tag in production by swapping `:latest` for `:sha-<commit>` in the `docker run` command.

---

## Troubleshooting

**Backend won't start** — `docker logs takdata`. Usually volume perms or corrupt SQLite under `data/`.

**401 on every request** — `AUTH_ENABLED=true` but forward-auth middleware not attached to the backend router. Either fix the middleware wiring or set `AUTH_ENABLED=false` (LAN only).

**WebSocket "Reconnecting…"** — reverse proxy not forwarding upgrade headers on `/api/v1/ws/*`. Confirm `Upgrade` / `Connection` headers pass through and that the backend router matches the WS path.

**502 from proxy** — container not running or not bound to the expected loopback port. `docker ps` and `ss -tlnp | grep 8001`.

**Cannot pull image (403)** — package private. Make it public or `docker login ghcr.io` with a PAT having `read:packages`.

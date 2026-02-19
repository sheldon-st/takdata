# TAK Manager — VPS Deployment Guide

This guide covers deploying TAK Manager (backend API + frontend) on a VPS using
pre-built Docker images from GitHub Container Registry (GHCR).

---

## Architecture on the VPS

```
Internet
  │
  ▼  port 80 (or 443 with SSL)
┌──────────────────────────────┐
│  frontend container (nginx)  │
│  • serves React static files │
│  • proxies /api/* → backend  │
│  • proxies /api/v1/ws/* → WS │
└──────────────┬───────────────┘
               │  Docker network: tak-net
               ▼  port 8000 (internal only)
┌──────────────────────────────┐
│  backend container (FastAPI) │
│  • REST API                  │
│  • WebSocket live status     │
│  • SQLite + uploaded certs   │
└──────────────────────────────┘
```

The backend is **never exposed directly** to the host — all traffic flows through
the frontend nginx container.

---

## Prerequisites

- A VPS running Ubuntu 22.04 / Debian 12 (or similar). ARM64 (e.g. Oracle Cloud
  free tier) and AMD64 both work — images are multi-arch.
- A domain name pointing to your VPS IP (optional but recommended for SSL).
- SSH access with `sudo`.

---

## Step 1 — Install Docker on the VPS

```bash
# One-liner install for Ubuntu/Debian
curl -fsSL https://get.docker.com | sh

# Add your user to the docker group (re-login after)
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker compose version
```

---

## Step 2 — Make GHCR images accessible

Images are published to GitHub Container Registry (`ghcr.io`). By default they
are **private**. You have two options:

### Option A — Make packages public (recommended, no auth needed on VPS)

1. Go to `https://github.com/sheldon-st?tab=packages`
2. Click the **takdata** package → **Package settings** → scroll to **Danger Zone** → **Change visibility** → Public
3. Repeat for **takdata-frontend** once it is published

### Option B — Authenticate on the VPS with a Personal Access Token

1. On GitHub: **Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Generate a token with `read:packages` scope
3. On the VPS:

```bash
echo "<YOUR_PAT>" | docker login ghcr.io -u <your-github-username> --password-stdin
```

---

## Step 3 — Create a deployment directory

```bash
mkdir -p ~/tak-manager
cd ~/tak-manager
```

---

## Step 4 — Download the compose file and configure environment

```bash
# Download the production compose file from the repo
curl -fsSL https://raw.githubusercontent.com/sheldon-st/takdata/main/docker-compose.yml \
     -o docker-compose.yml

# Download the env template and fill in your values
curl -fsSL https://raw.githubusercontent.com/sheldon-st/takdata/main/.env.example \
     -o .env
```

Edit `.env`:

```bash
nano .env
```

Minimum required changes:

| Variable | Default | Notes |
|----------|---------|-------|
| `HOST_PORT` | `80` | Change to `443` only if terminating TLS here |
| `LOG_LEVEL` | `INFO` | Change to `DEBUG` if troubleshooting |
| `CORS_ORIGINS` | `["*"]` | Tighten to `["https://your-domain.com"]` in production |

---

## Step 5 — Pull images and start

```bash
docker compose pull
docker compose up -d
```

Verify containers are running:

```bash
docker compose ps
docker compose logs -f
```

The app is now available at `http://<your-vps-ip>/`.

---

## Step 6 — Open the firewall

```bash
# UFW (Ubuntu)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp   # only if using SSL
sudo ufw reload
```

---

## Updating to a new release

```bash
cd ~/tak-manager
docker compose pull
docker compose up -d
```

Docker Compose will restart only the containers whose images have changed. The
`tak-data` volume (SQLite DB + uploaded certs) is preserved across updates.

---

## Viewing logs

```bash
# All containers
docker compose logs -f

# Backend only
docker compose logs -f backend

# Frontend nginx only
docker compose logs -f frontend
```

---

## Optional — Automatic HTTPS with Caddy

[Caddy](https://caddyserver.com) is the simplest way to add automatic Let's
Encrypt TLS in front of the stack. It handles cert issuance and renewal
automatically.

### 1. Create `Caddyfile`

```
# ~/tak-manager/Caddyfile
your-domain.com {
    reverse_proxy frontend:80
}
```

Replace `your-domain.com` with your actual domain. Caddy will obtain a
certificate automatically on first start (port 80 and 443 must be reachable).

### 2. Create `docker-compose.caddy.yml`

```yaml
services:
  caddy:
    image: caddy:2-alpine
    container_name: tak-manager-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"   # HTTP/3
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
      - caddy-config:/config
    networks:
      - tak-net

volumes:
  caddy-data:
  caddy-config:
```

### 3. Update `.env` to stop the frontend from binding port 80 directly

```env
HOST_PORT=   # leave empty — Caddy takes port 80/443
```

### 4. Start with both compose files

```bash
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d
```

---

## Data persistence

All persistent data lives in the **`tak-data` Docker named volume**:

- `config.db` — SQLite database (TAK config, enablements, sources)
- `certs/` — uploaded `.p12` client certificates

To back it up:

```bash
docker run --rm \
  -v tak-manager_tak-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/tak-data-backup.tar.gz /data
```

To restore from backup:

```bash
docker run --rm \
  -v tak-manager_tak-data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/tak-data-backup.tar.gz -C /
```

---

## CI/CD flow summary

```
git push to main
      │
      ▼
GitHub Actions (.github/workflows/docker-image.yml)
  ├── Build backend  → ghcr.io/sheldon-st/takdata:latest
  └── Build frontend → ghcr.io/sheldon-st/takdata-frontend:latest
           (skipped until frontend/package.json exists)
                │
                ▼
         docker compose pull   (on VPS)
         docker compose up -d
```

Images are tagged with both `:latest` and `:sha-<commit>`. The compose file
always pulls `:latest`. To pin to a specific commit, edit `docker-compose.yml`
and replace `:latest` with the desired SHA tag.

---

## Troubleshooting

**Backend fails to start**
```bash
docker compose logs backend
```
Common causes: volume permission issues, corrupt SQLite DB.

**Frontend shows blank page / 404 on refresh**
Nginx is not serving `index.html` as fallback. Verify [frontend/nginx.conf](frontend/nginx.conf)
has the `try_files $uri $uri/ /index.html;` directive.

**WebSocket shows "Reconnecting..."**
- Check that port 80 is open on the VPS firewall
- Verify `/api/v1/ws/` location block in nginx.conf is above the `/api/` block
- Check backend logs for errors

**Cannot pull image (403 Forbidden)**
The GHCR package is private. Follow Step 2 to make it public or authenticate
with a PAT.

**Port 80 already in use**
Another process is using port 80 (e.g. Apache). Either stop it or set
`HOST_PORT=8080` in `.env` and access the app on that port.

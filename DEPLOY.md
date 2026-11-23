# Deploying TAK Manager

TAK Manager runs as two containers: the **backend** (this repo) and the
**frontend** ([takdata-frontend](https://github.com/sheldon-st/takdata-frontend)).
The reference deployment is a [Dokploy](https://dokploy.com) Compose
application on a VPS, with Dokploy's Traefik handling TLS and an
[Authentik](https://goauthentik.io) forward-auth middleware handling login.

The compose file lives in the frontend repo:
[`docker-compose.yml`](https://github.com/sheldon-st/takdata-frontend/blob/main/docker-compose.yml).

---

## Architecture

```
Internet :443
  │
  ▼
┌────────────────────────────────────────────────────────┐
│ Traefik (managed by Dokploy)                           │
│ • TLS (Let's Encrypt)                                  │
│ • authentik-fwd middleware on both routers             │
│ • Host(data.opengeo.space) && PathPrefix(/api) → API   │
│ • Host(data.opengeo.space)                     → UI    │
└──────────────┬──────────────────────────┬──────────────┘
               │ /api/*                   │ everything else
               ▼                          ▼
     ┌────────────────────┐     ┌────────────────────┐
     │ backend  :8000     │     │ frontend :3000     │
     │ FastAPI + workers  │     │ Next.js standalone │
     │ tak-data volume    │     └────────────────────┘
     └─────────┬──────────┘
               │ CoT over TLS (client .p12)
               ▼
          TAK Server
```

UI and API share one origin, so the browser needs no CORS and the Authentik
session cookie covers both. Neither container binds a host port; both join
the external `dokploy-network`.

---

## Prerequisites

- A VPS with Dokploy installed.
- DNS `A` record for `data.opengeo.space` → VPS IP.
- An Authentik outpost exposed to Traefik as the `authentik-fwd@docker`
  middleware, with an application whose users belong to
  `tak-manager-admin` (read/write) or `tak-manager-viewer` (read-only).
- GHCR images public, or Dokploy registry credentials for `ghcr.io/sheldon-st`.

---

## 1. Create the Compose application

In Dokploy: **Projects → New Application → Compose**.

- **Source:** Git → `https://github.com/sheldon-st/takdata-frontend`, branch
  `main`, compose path `docker-compose.yml`.
- **Environment:**

  ```dotenv
  LOG_LEVEL=INFO
  AUTH_ENABLED=true
  # Optional: default key for AIS sources without their own
  AISSTREAM_API_KEY=
  ```

- **Deploy.** Routing comes from the Traefik labels in the compose file, so
  the Domains tab can stay empty.

## 2. Verify

```bash
curl -I https://data.opengeo.space                   # 302 to Authentik when signed out
docker inspect --format '{{.State.Health.Status}}' <backend-container>   # healthy
```

Sign in, open **TAK Settings**, upload the client `.p12`, set the CoT URL
and connect. The sidebar pill turns green once the TLS session is up.

---

## Running without Authentik

For a private LAN or tailnet, drop the `authentik-fwd@docker` middleware
labels and set `AUTH_ENABLED=false`. Every caller is then treated as admin.

> **Warning:** with `AUTH_ENABLED=false` anyone who can reach the host has
> full control, including uploading certs and pointing feeds at your TAK
> server. Only do this behind a firewall or VPN.

With auth **on**, the backend trusts the `x-authentik-*` headers it
receives. Keep port 8000 unreachable except through Traefik.

---

## Updating

Every push to `main` publishes `latest` and `sha-<short>` images for both
repos; tags `vX.Y.Z` publish `X.Y.Z` and `X.Y`. In Dokploy, click
**Redeploy** (or enable auto-deploy with a webhook). Pin a version tag in
the compose file for repeatable rollbacks.

The backend image runs as uid 1001. On first start after upgrading from a
root-run image, its entrypoint chowns the `tak-data` volume automatically.

---

## Data & backups

The `tak-data` volume holds all state:

| Path        | Contents                                 |
| ----------- | ---------------------------------------- |
| `config.db` | SQLite: TAK config, enablements, sources |
| `certs/`    | Uploaded `.p12` client certificates      |
| `packages/` | Uploaded TAK data packages               |

```bash
# Backup (find the real volume name with `docker volume ls`)
docker run --rm -v <project>_tak-data:/data -v "$PWD":/backup \
  alpine tar czf /backup/tak-data.tar.gz -C /data .

# Restore
docker run --rm -v <project>_tak-data:/data -v "$PWD":/backup \
  alpine tar xzf /backup/tak-data.tar.gz -C /data
```

The DB stores the `.p12` password and source API keys in plain text, so
treat backups as secrets.

---

## Troubleshooting

| Symptom                               | Check                                                                                        |
| ------------------------------------- | -------------------------------------------------------------------------------------------- |
| Traefik 404                           | Router labels match the host; both services are on `dokploy-network`.                        |
| `401` from every `/api` call          | Authentik middleware isn't attached to the API router, or the outpost isn't sending headers. |
| `403 Insufficient permissions`        | User isn't in `tak-manager-admin` or `tak-manager-viewer`.                                   |
| "Reconnecting to live status…" banner | WebSocket `/api/v1/ws/status` blocked; check the backend logs and the API router.            |
| TAK pill stays grey                   | `connect_error` on `GET /api/v1/status` says why (bad cert password, TLS alert, refused).    |
| `events_dropped` climbing             | TAK link is down or slower than the feed; the supervisor reconnects automatically.           |
| Cannot pull image (403)               | Make the GHCR package public or add registry credentials in Dokploy.                         |

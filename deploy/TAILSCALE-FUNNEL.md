# CDAP Tailscale Funnel Runbook

This deployment uses Tailscale Funnel as the public HTTPS edge. Docker services
listen on loopback only; the existing Funnel listener on port 443 is preserved.

## Public endpoints

- Web UI and API: `https://codex-pc.tail409d12.ts.net:8443/`
- MinIO S3 API for presigned downloads: `https://codex-pc.tail409d12.ts.net:10000/`
- Existing service on `https://codex-pc.tail409d12.ts.net/` (port 443) is unchanged.

MinIO console port 9001 is intentionally not exposed.

## Start or restart CDAP

Run from this directory and keep the existing volumes:

```powershell
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.tailscale.yml up -d --build
```

The `minio-init` one-shot service creates or refreshes the application policy,
and `migrate` applies database migrations. Do not use `down -v` for a routine
restart.

## Funnel configuration

```powershell
tailscale funnel --bg --yes --https=8443 http://127.0.0.1:8080
tailscale funnel --bg --yes --https=10000 http://127.0.0.1:9000
tailscale funnel status --json
```

The status output must contain ports 443, 8443, and 10000. The hostname can be
changed by setting `TAILSCALE_HOSTNAME` when starting the Compose overlay; it
must match the Funnel hostname used by the browser-visible presigned URLs.

## Checks

```powershell
Invoke-WebRequest https://codex-pc.tail409d12.ts.net:8443/api/v1/healthz
Invoke-WebRequest https://codex-pc.tail409d12.ts.net:8443/api/v1/readyz
Invoke-WebRequest https://codex-pc.tail409d12.ts.net:10000/minio/health/live
```

`readyz` must report database, Redis, and storage as `ok`.

## Rollback or disable public access

To stop only the CDAP Funnel listeners while leaving the existing 443 service
untouched:

```powershell
tailscale funnel --https=8443 off
tailscale funnel --https=10000 off
```

Then stop the CDAP stack if required:

```powershell
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.tailscale.yml down
```

This does not remove named volumes. A frp deployment would require a separate
public `frps` server, firewall rules, and certificate management; it is not
needed for this single-host setup because Tailscale is already installed and
authenticated.

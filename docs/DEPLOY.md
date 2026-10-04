# Deploying RunCoach

Production target, decided 2026-10-04: **one Hostinger KVM VPS (x86_64, Ubuntu 24.04,
4 GB) running k3s**, behind **Cloudflare** (proxied, free plan), at
**https://runcoach.rohitgajula.in**. Fewer than 10 users, **invite-only**.
CI/CD: GitHub Actions. `development` = work branch (tests only); `production` = deploys.

```
browser ─► Cloudflare (DNS, TLS, WAF, edge rate limit)
             │  Full (strict) TLS with a Cloudflare Origin Certificate
             ▼
         VPS :443 (ufw: only Cloudflare IP ranges on 80/443; SSH 22 key-only)
             ▼
         k3s Traefik (built-in) ── IngressRoute + middlewares (rate limit, headers)
             ├─ /api, /admin, /static ──► Service backend:8000  (gunicorn, Django)
             └─ /                       ──► Service frontend:8080 (nginx, static PWA)
         backend ─► postgres (StatefulSet, PVC) · redis (Deployment)
         worker  (celery -B: default/metrics/ai/planning queues, concurrency 2)
         garmin-worker (celery, queue garmin, concurrency 1 — Garmin limits per IP)
```

## 1. Application settings (env contract)

All config from env; `backend/config/settings.py` must honour:

| Variable | Prod value | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `0` | default stays `1` for dev |
| `DJANGO_SECRET_KEY` | 64+ random chars | **startup must fail** if DEBUG=0 and key missing/default/short |
| `DJANGO_ALLOWED_HOSTS` | `runcoach.rohitgajula.in` | |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://runcoach.rohitgajula.in` | |
| `DJANGO_SECURE` | `1` | when 1: `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https")`, secure session/CSRF cookies, HSTS 1 year (no preload), `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS=DENY`, `REFERRER_POLICY` same-origin. No `SECURE_SSL_REDIRECT` (Cloudflare + Traefik already redirect; avoids loops) |
| `TRUST_CF_CONNECTING_IP` | `1` | middleware sets `REMOTE_ADDR` from `CF-Connecting-IP` so throttles see the real client, not Cloudflare/Traefik |
| `REGISTRATION_MODE` | `invite` | `open` · `invite` · `closed`; default `open` in DEBUG, `invite` otherwise |
| `POSTGRES_*`, `REDIS_URL`, `OPENAI_API_KEY`, `AI_*`, `GARMIN_TOKEN_DIR` | as today | |
| `MEDIA_ROOT` | `/app/media` (PVC) | |
| `AI_MONTHLY_CALL_BUDGET` | e.g. `400` | per athlete; existing budget helper reads it |

## 2. Hardening (app code)

1. **Production settings** per the table; WhiteNoise for static files.
2. **Invite codes**: `InviteCode(code unique, note, max_uses=1, uses, expires_at null, created_at)`
   in `apps/athletes`, admin-registered with a "generate" action; `POST /api/auth/register/`
   requires a valid `invite_code` when mode=`invite` (consumed atomically), refuses all when
   `closed`. `GET /api/auth/registration/` → `{mode}` so the UI shows/hides the field.
3. **Throttles** (per real client IP): login 10/min, register 5/hour, refresh 60/min,
   garmin connect 5/hour, chat as today. All 429 `{detail}`.
4. **Meal photos behind auth**: no public `/api/media/` in prod. `photo_url` becomes a
   signed, expiring URL (`/api/media/signed/<path>?exp=…&sig=…`, HMAC with SECRET_KEY,
   1 h) served by a view that checks the signature. Works in `<img>` without headers.
5. **Account deletion**: `DELETE /api/auth/me/ {password}` deletes the user and everything
   cascading, plus files on disk (FIT files, meal photos, Garmin token dir), and revokes
   refresh tokens. Settings → "Delete account" (type DELETE to confirm).
6. **Privacy note** on Register: what is stored, that coaching text goes to OpenAI (API
   data not used for training), invite-only, delete anytime.
7. **Health**: `GET /api/health/live/` (process only, no deps) for liveness;
   existing `/api/health/` (db+redis) for readiness.

## 3. Images

`backend/Dockerfile.prod` (multi-stage, non-root uid 10001, collectstatic at build,
gunicorn `--workers 2 --timeout 150 --access-logfile -`; chat and Garmin pushes can take
>30 s) and `frontend/Dockerfile.prod` (node build → nginx-unprivileged:8080, SPA
fallback, no-cache for index.html and sw.js, immutable /assets). `backend/.dockerignore`
excludes media/, .garmin/, .env, caches. Built in CI for `linux/amd64`, pushed to
`ghcr.io/rohittgajula/runcoach-backend:<git-sha>` and `…/runcoach-frontend:<git-sha>`.

## 4. Kubernetes (`deploy/k8s/`, Kustomize)

`base/` + `overlays/prod/`. Namespace `runcoach`. Postgres StatefulSet (16-alpine, 10 Gi
PVC, `pg_isready` probes); Redis Deployment; backend Deployment (initContainer runs
`migrate --noinput`; readiness `/api/health/`, liveness `/api/health/live/`; PVCs `media`
5 Gi at /app/media and `garmin-tokens` 1 Gi at /app/.garmin, fsGroup 10001); worker and
garmin-worker Deployments sharing those PVCs (single node → RWO local-path is fine);
frontend Deployment; Services; Traefik `IngressRoute` (websecure, TLS secret
`runcoach-origin-tls`) + `Middleware`s: rate limit keyed on `CF-Connecting-IP` (avg 20/s,
burst 50 for /api; 10/min for /api/auth/), security headers; HTTP→HTTPS redirect.
Resource requests/limits sized for 4 GB. Backup `CronJob` 03:00 IST: `pg_dump | gzip`
to a `backups` PVC, keep 14 days; optional upload to Cloudflare R2 when secret
`runcoach-r2` exists. Secrets are **never in git**: `runcoach-secrets` and
`runcoach-origin-tls` are created on the server by `deploy/scripts/push-secrets.sh` from
the git-ignored `deploy/secrets/`.

## 5. CI/CD (`.github/workflows/`)

- `ci.yml` — push/PR on `development` and `production`: backend pytest with Postgres +
  Redis services; frontend `npm ci && npm run build`.
- `deploy.yml` — push on `production`: run CI, build + push both images (buildx, cache),
  then over SSH (secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`,
  `DEPLOY_KNOWN_HOSTS`): copy rendered manifests (`kubectl kustomize` with the sha tags),
  `kubectl apply`, `kubectl rollout status` for every Deployment (timeout 5 min). Failure
  leaves the old Pods serving. Concurrency group so two deploys never overlap.

## 6. Server bootstrap (`deploy/scripts/bootstrap-server.sh`, run once as root)

Updates + unattended-upgrades, 2 GB swap, `deploy` user with sudo and Rohit's SSH key,
SSH: no root login, no passwords; ufw: 22 open, 80/443 **only from Cloudflare IP
ranges**; fail2ban for SSH; k3s (Traefik on, servicelb on, `--write-kubeconfig-mode 600`)
with kubeconfig for `deploy`.

## 7. What only Rohit can do (accounts)

Cloudflare: add site, switch GoDaddy nameservers, SSL mode Full (strict), create Origin
Certificate. Hostinger: buy VPS (Ubuntu 24.04, India), add SSH key, give IP. GitHub: add the
four `DEPLOY_*` secrets; make the two GHCR packages public after the first build. OpenAI:
set a monthly hard limit.

## 8. Runbook

Files: images `backend/Dockerfile.prod`, `frontend/Dockerfile.prod` (+ `frontend/nginx.conf`);
manifests `deploy/k8s/base` + `overlays/prod` (and `overlays/local` for kind); scripts
`deploy/scripts/{bootstrap-server,push-secrets,restore-backup}.sh`; workflows
`.github/workflows/{ci,deploy}.yml`. Secrets live only in git-ignored `deploy/secrets/`.

### First-time setup (in this order)

1. **Accounts** (§7): VPS (Ubuntu 24.04, your SSH key added), Cloudflare site with the
   `runcoach` A record **proxied** to the VPS IP, SSL mode **Full (strict)**.
2. **Bootstrap the server** (as root, once; safe to re-run):
   `scp deploy/scripts/bootstrap-server.sh root@IP:/root/ && ssh root@IP bash /root/bootstrap-server.sh`.
   It copies root's authorized key(s) to `deploy` and only then disables root/password
   login. Check `ssh deploy@IP kubectl get nodes` works **before** closing the root session.
3. **CI key**: `ssh-keygen -t ed25519 -f runcoach-ci -N '' -C github-actions`; append
   `runcoach-ci.pub` to `/home/deploy/.ssh/authorized_keys` on the server.
4. **GitHub secrets** (Settings → Secrets → Actions): `DEPLOY_HOST` (IP),
   `DEPLOY_USER` (`deploy`), `DEPLOY_SSH_KEY` (contents of `runcoach-ci`),
   `DEPLOY_KNOWN_HOSTS` (output of `ssh-keyscan -t ed25519 IP`). Delete the local key copy.
5. **Origin certificate**: Cloudflare → SSL/TLS → Origin Server → Create (RSA,
   `runcoach.rohitgajula.in`, 15 years). Save as `deploy/secrets/origin.pem` and `origin.key`.
6. **App secrets**: `cp deploy/secrets/prod.env.example deploy/secrets/prod.env`, fill it
   in (no quotes). Optional off-site backups: `r2.env` from `r2.env.example`.
7. `deploy/scripts/push-secrets.sh deploy@IP` — creates `runcoach-secrets`,
   `runcoach-origin-tls` (and `runcoach-r2`). Never prints values.
8. **First deploy**: merge `development` into `production` and push. Watch Actions →
   Deploy. Then make both GHCR packages public (Packages → package → settings) so k3s
   can pull without credentials — the first deploy fails at image pull until you do;
   re-run it after.
9. **First admin**: `ssh deploy@IP kubectl -n runcoach exec -it deploy/backend -- python manage.py createsuperuser`,
   then create invite codes in `/admin/`.

### Deploy

Push (or merge) to `production`. `deploy.yml` runs CI, builds both images for
`linux/amd64` tagged with the commit sha, renders `overlays/prod` with that tag, applies
it on the server and waits for every rollout (5 min each). Backend and frontend roll
with `maxUnavailable: 0`, so a failing new Pod (bad migration, failed readiness) leaves
the old one serving and the workflow red; workers are `Recreate` (beat must never run
twice), so they pause for a few seconds. Rendered manifests are kept on the server
in `~/runcoach/` (last 10, `current.yaml` → the live one).

Status: `ssh deploy@IP kubectl -n runcoach get pods` · logs:
`kubectl -n runcoach logs deploy/backend` (`-c migrate` for migrations), `deploy/worker`,
`deploy/garmin-worker`.

### Rollback

- **Fast, one component**: `ssh deploy@IP kubectl -n runcoach rollout undo deployment/backend`
  (or `frontend`, `worker`, `garmin-worker`). Next push to `production` overrides it.
- **Whole release**: Actions → Deploy → Run workflow → `sha` = the last good commit
  (full sha; `git log production`). Skips build, redeploys that sha's images and
  manifests. Or `git revert` on `production` and push.
- Migrations are not reversed by either. If a release ran a destructive migration,
  roll back the code **and** restore the backup taken before it (below).

### Backups and restore

`postgres-backup` CronJob, 03:00 IST, `pg_dump | gzip` to the `backups` PVC, 14 days;
also uploaded to R2 when `runcoach-r2` exists. Media and Garmin tokens are **not** in
it (tokens can be re-created by reconnecting; meal photos are lost with the disk).

- Take one now: `kubectl -n runcoach create job backup-manual-$(date +%s) --from=cronjob/postgres-backup`
- List: `deploy/scripts/restore-backup.sh --list`
- Restore (stops backend + workers, replaces the schema, starts them; asks to type RESTORE):
  `deploy/scripts/restore-backup.sh latest` or `… runcoach-<timestamp>.sql.gz`, or a
  local file downloaded from R2: `… ./runcoach-<timestamp>.sql.gz`. Run it on the server
  as `deploy` (`scp` it there), or locally with `KUBECTL_CONTEXT=kind-runcoach` for kind.
- Practise it on kind (below) before you need it.

### Rotate secrets

Edit `deploy/secrets/prod.env` (or the cert files), then
`deploy/scripts/push-secrets.sh deploy@IP --restart`.
- `DJANGO_SECRET_KEY`: logs everyone out, invalidates signed media URLs — fine.
- `POSTGRES_PASSWORD`: change it in the database **first**, then push:
  `kubectl -n runcoach exec -it postgres-0 -- psql -U runcoach -d runcoach -c "ALTER USER runcoach PASSWORD 'new'"`.
  (The env var only sets the password when the volume is first initialised.)
- `OPENAI_API_KEY`: create the new key, push, then revoke the old one.
- Origin certificate: replace `origin.pem`/`origin.key`, push (Traefik reloads it; no restart).
- CI SSH key: generate a new pair, add the new public key on the server, update
  `DEPLOY_SSH_KEY`, run a deploy, then remove the old public key.

### Server upkeep

- Re-run `bootstrap-server.sh` now and then: refreshes the Cloudflare IP ranges (ufw
  rules **and** the `runcoach_cf` nftables pre-NAT filter that stops k3s port
  forwarding from bypassing ufw). Everything else is idempotent.
- Security updates install automatically; reboot for kernel updates when convenient
  (`sudo reboot`; k3s and all Pods come back on their own).

### Local smoke test (kind)

`deploy/k8s/overlays/local/up.sh` builds the images, loads them into the
`kind-runcoach` cluster (`deploy/kind/cluster.yaml`), installs Traefik with Helm,
creates a self-signed cert and dummy secrets, deploys, and curls
`https://runcoach.localhost` (health, SPA, admin static, HTTP→HTTPS). `down.sh` removes it.

# Backups and restore (R13 §18)

Two copies of every nightly database dump:

1. **On the server** — the `postgres-backup` CronJob (`deploy/k8s/base/backup.yaml`) runs
   `pg_dump | gzip` at 03:00 IST into the `backups` PVC as
   `runcoach-YYYYMMDDTHHMMSSZ.sql.gz` (UTC timestamp) and keeps 14 days there.
2. **Off-site, Cloudflare R2** — when the optional Secret `runcoach-r2` exists, the Job's
   `upload` container (rclone) copies the new dump to the bucket:
   ```
   daily/runcoach-…sql.gz    every night — the newest 14 are kept
   weekly/runcoach-…sql.gz   the dump whose UTC date is a Sunday — the newest 8 are kept
   ```
   Retention is enforced by the upload script itself, by count
   (`deploy/scripts/r2-backup-upload.sh`), so a missed night never deletes more than it
   should. An R2 lifecycle rule is only a backstop (below).

Only the database is backed up. FIT files, meal photos and Garmin tokens live on the
`media` / `garmin-tokens` PVCs: FIT files can be re-downloaded from Garmin
(`python manage.py reingest`), Garmin tokens are re-created by reconnecting, meal photos
are not backed up.

## Verifying the upload path (no R2 needed)

```
deploy/scripts/test-r2-backup.sh
```
Runs a local S3 server (`rclone serve s3`, the same `rclone/rclone:1.68` image the Job
uses), simulates 70 nightly dumps through `r2-backup-upload.sh` and checks: exactly 14
objects in `daily/`, exactly 8 Sunday dumps in `weekly/`, the newest object downloads,
passes `gzip -t` and is byte-identical to the local dump, and with no bucket configured
the script is a no-op. Last run (2026-10-07): **PASS** (daily window 2026-09-26 …
2026-10-09, 8 weekly).

## Wiring the script into the CronJob (deploy/k8s — lead)

The Job's current `upload` container copies the newest dump to the bucket root and never
prunes. Replace its inline `command` script with the contents of
`deploy/scripts/r2-backup-upload.sh` (it reads the same env the container already has:
`R2_ACCOUNT_ID`, `R2_BUCKET`, `RCLONE_CONFIG_R2_*`; nothing new in the Secret). Either
paste it into the `|` block, or ship it as a ConfigMap
(`kustomize configMapGenerator` from the file) mounted read-only and run
`sh /scripts/r2-backup-upload.sh`. Objects already uploaded to the bucket root by the old
script are left alone; delete them by hand once `daily/` has 14 entries.

## Needs Rohit: create the bucket and token (Cloudflare dashboard)

1. Cloudflare dashboard → **R2 Object Storage** → **Create bucket** → name
   `runcoach-backups`, location *Automatic*, default storage class *Standard* → Create.
2. In the bucket → **Settings** → **Object lifecycle rules** → **Add rule** (backstop only):
   - "daily backstop": prefix `daily/`, *Delete objects* after **30 days**.
   - "weekly backstop": prefix `weekly/`, *Delete objects* after **90 days**.
3. R2 overview → **Manage R2 API Tokens** → **Create API token**:
   permissions **Object Read & Write**, *Apply to specific buckets only* →
   `runcoach-backups`, TTL *Forever* → Create. Copy the **Access Key ID** and **Secret
   Access Key** (shown once) and note the **Account ID** (R2 overview, right side).
4. On your laptop: `cp deploy/secrets/r2.env.example deploy/secrets/r2.env` and fill in
   `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET=runcoach-backups`
   (the file is git-ignored). Then `deploy/scripts/push-secrets.sh` creates the
   `runcoach-r2` Secret.
5. Test without waiting for 03:00:
   ```
   kubectl -n runcoach create job --from=cronjob/postgres-backup backup-now
   kubectl -n runcoach logs job/backup-now -c upload      # "uploaded daily/runcoach-…"
   ```
   and check the object in the bucket's **Objects** tab. Delete the test job afterwards
   (`kubectl -n runcoach delete job backup-now`).

## Restoring

`deploy/scripts/restore-backup.sh` **replaces the whole database**. It stops the backend
and workers, drops and recreates the `public` schema, loads the dump, and starts them
again (the backend re-runs `migrate`). It asks you to type `RESTORE` unless `YES=1`.

From the server PVC (normal case):
```
deploy/scripts/restore-backup.sh --list      # what is on the backups PVC
deploy/scripts/restore-backup.sh latest
deploy/scripts/restore-backup.sh runcoach-20261004T213000Z.sql.gz
```

From R2 (server disk lost, or an older weekly copy):
1. Download the object — Cloudflare dashboard → R2 → `runcoach-backups` → `daily/` or
   `weekly/` → the object → **Download**; or with rclone and the same token:
   ```
   export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare \
          RCLONE_CONFIG_R2_ACCESS_KEY_ID=… RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=… \
          RCLONE_CONFIG_R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   rclone lsf r2:runcoach-backups/daily/
   rclone copyto r2:runcoach-backups/daily/runcoach-20261006T213000Z.sql.gz ./restore.sql.gz
   ```
2. `gzip -t restore.sql.gz` (the script checks too).
3. Where kubectl reaches the cluster: `deploy/scripts/restore-backup.sh ./restore.sql.gz`
   (locally against kind: `KUBECTL_CONTEXT=kind-runcoach deploy/scripts/restore-backup.sh …`).

After a restore:
- `kubectl -n runcoach rollout status deployment/backend` and open the app; sign in.
- Garmin sync resumes on its own; anything synced after the dump is fetched again on the
  next sync (ingestion is idempotent).
- Data written after the dump (habit logs, check-ins, chat) is lost — say so to athletes.
- Rehearse a restore into the local kind cluster once a quarter.

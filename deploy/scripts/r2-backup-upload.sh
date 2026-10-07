#!/bin/sh
# Off-site copy of the nightly pg_dump to Cloudflare R2, with retention (R13 §18).
#
# Runs in the rclone/rclone image (busybox sh) as the `upload` container of the
# postgres-backup CronJob, after the dump container wrote /backups/runcoach-*.sql.gz.
# Layout in the bucket:
#   daily/runcoach-YYYYMMDDTHHMMSSZ.sql.gz    every night, newest KEEP_DAILY kept (14)
#   weekly/runcoach-YYYYMMDDTHHMMSSZ.sql.gz   the Sunday (UTC date) dump, newest KEEP_WEEKLY kept (8)
# Retention is enforced here by count (robust to missed nights); an R2 lifecycle rule on
# the bucket is only a backstop (deploy/RESTORE.md).
#
# Env: R2_ACCOUNT_ID, R2_BUCKET, RCLONE_CONFIG_R2_ACCESS_KEY_ID,
#      RCLONE_CONFIG_R2_SECRET_ACCESS_KEY, RCLONE_CONFIG_R2_TYPE=s3,
#      RCLONE_CONFIG_R2_PROVIDER=Cloudflare (all from the runcoach-r2 Secret / the Job).
# Optional: R2_ENDPOINT (tests point it at a local S3 server), BACKUP_DIR (/backups),
#      BACKUP_FILE (upload this file instead of the newest), KEEP_DAILY, KEEP_WEEKLY.
# Not configured (no bucket / account) -> prints a line and exits 0 (local backup only).
set -eu

if [ -z "${R2_BUCKET:-}" ] || [ -z "${R2_ACCOUNT_ID:-}${R2_ENDPOINT:-}" ]; then
  echo "runcoach-r2 not configured; local backup only"
  exit 0
fi
export RCLONE_CONFIG_R2_ENDPOINT="${R2_ENDPOINT:-https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com}"
dir="${BACKUP_DIR:-/backups}"
keep_daily="${KEEP_DAILY:-14}"
keep_weekly="${KEEP_WEEKLY:-8}"
remote="r2:${R2_BUCKET}"

# Dump names are fixed-format timestamps, so ls|sort is safe here.
# shellcheck disable=SC2012
latest="${BACKUP_FILE:-$(ls -1 "$dir"/runcoach-*.sql.gz 2>/dev/null | sort | tail -n 1)}"
[ -n "$latest" ] && [ -f "$latest" ] || { echo "no dump found in $dir" >&2; exit 1; }
name="$(basename "$latest")"
gzip -t "$latest"

rclone copyto "$latest" "$remote/daily/$name"
echo "uploaded daily/$name"

# Weekday of the dump's UTC date from its name (0 = Sunday), Sakamoto's method —
# plain shell arithmetic, no date(1) flavour differences.
stamp="$(echo "$name" | sed -n 's/^runcoach-\([0-9]\{8\}\)T.*/\1/p')"
if [ -n "$stamp" ]; then
  y=$(echo "$stamp" | cut -c1-4); m=$(echo "$stamp" | cut -c5-6); d=$(echo "$stamp" | cut -c7-8)
  m=${m#0}; d=${d#0}
  if [ "$m" -lt 3 ]; then y=$((y - 1)); fi
  t=$(echo "0 3 2 5 0 3 5 1 4 6 2 4" | cut -d' ' -f"$m")
  dow=$(( (y + y / 4 - y / 100 + y / 400 + t + d) % 7 ))
  if [ "$dow" -eq 0 ]; then
    rclone copyto "$latest" "$remote/weekly/$name"
    echo "uploaded weekly/$name"
  fi
fi

prune() {
  prefix="$1"; keep="$2"
  rclone lsf --files-only "$remote/$prefix/" 2>/dev/null \
    | grep '^runcoach-.*\.sql\.gz$' | sort -r | tail -n +"$((keep + 1))" \
    | while read -r old; do
        rclone deletefile "$remote/$prefix/$old"
        echo "pruned $prefix/$old"
      done
}
prune daily "$keep_daily"
prune weekly "$keep_weekly"

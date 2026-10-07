#!/usr/bin/env bash
# End-to-end check of r2-backup-upload.sh against a local S3 target (R13 §18).
#
# Starts `rclone serve s3` (the same rclone/rclone image the CronJob uses) as a stand-in
# for R2, then simulates 70 nightly backups: each night a fresh gzip dump lands in a
# scratch "backups PVC" and the upload script runs exactly as in the Job. Afterwards:
#   * daily/ holds exactly the newest 14 dumps, weekly/ the newest 8 Sunday dumps;
#   * the newest object downloads, passes gzip -t and matches the local file byte for byte;
#   * with no bucket configured the script is a no-op (exit 0).
# Needs only docker and the local rclone/rclone:1.68 image. No real R2, no secrets.
set -euo pipefail

IMAGE=rclone/rclone:1.68
NET="r2test-$$"
WORK="$(mktemp -d)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cleanup() {
  docker rm -f "s3-$NET" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$WORK/backups" "$WORK/s3/runcoach-backups" "$WORK/restore"
docker network create "$NET" >/dev/null
docker run -d --name "s3-$NET" --network "$NET" -v "$WORK/s3:/data" "$IMAGE" \
  serve s3 /data --addr :8080 --auth-key testkey,testsecret >/dev/null
sleep 2

run_rclone() {
  docker run --rm --network "$NET" -v "$WORK/backups:/backups" -v "$SCRIPT_DIR:/scripts:ro" \
    -v "$WORK/restore:/restore" \
    -e R2_BUCKET=runcoach-backups -e R2_ENDPOINT="http://s3-$NET:8080" \
    -e RCLONE_CONFIG_R2_TYPE=s3 -e RCLONE_CONFIG_R2_PROVIDER=Other \
    -e RCLONE_CONFIG_R2_ACCESS_KEY_ID=testkey -e RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=testsecret \
    -e RCLONE_CONFIG_R2_ENDPOINT="http://s3-$NET:8080" -e HOME=/tmp -e RCLONE_LOG_LEVEL=ERROR \
    --entrypoint sh "$IMAGE" -c "$1"
}

# 70 nights, 2026-08-01 .. 2026-10-09, one script run each (in one container for speed).
run_rclone '
  set -eu
  i=0
  for day in $(seq 0 69); do
    stamp=$(date -u -d "@$(( 1785542400 + day * 86400 ))" +%Y%m%dT213000Z)
    f="/backups/runcoach-$stamp.sql.gz"
    echo "-- dump $stamp" | gzip -9 > "$f"
    BACKUP_FILE="$f" sh /scripts/r2-backup-upload.sh > /dev/null
  done
  echo "daily:";  rclone lsf r2:runcoach-backups/daily/  | sort
  echo "weekly:"; rclone lsf r2:runcoach-backups/weekly/ | sort
' > "$WORK/listing.txt"

daily=$(sed -n '/^daily:/,/^weekly:/p' "$WORK/listing.txt" | grep -c '^runcoach-' || true)
weekly=$(sed -n '/^weekly:/,$p' "$WORK/listing.txt" | grep -c '^runcoach-' || true)
newest=$(sed -n '/^daily:/,/^weekly:/p' "$WORK/listing.txt" | grep '^runcoach-' | tail -n1)
oldest_daily=$(sed -n '/^daily:/,/^weekly:/p' "$WORK/listing.txt" | grep '^runcoach-' | head -n1)
echo "daily objects: $daily (want 14), weekly objects: $weekly (want 8)"
echo "daily window: $oldest_daily .. $newest"
[ "$daily" -eq 14 ] && [ "$weekly" -eq 8 ] || { cat "$WORK/listing.txt"; exit 1; }

# Every weekly object is a Sunday (UTC) dump.
for name in $(sed -n '/^weekly:/,$p' "$WORK/listing.txt" | grep '^runcoach-'); do
  d=${name:9:8}
  [ "$(date -u -j -f %Y%m%d "$d" +%u 2>/dev/null || date -u -d "$d" +%u)" = 7 ] \
    || { echo "weekly $name is not a Sunday"; exit 1; }
done

# Restore path: download the newest and compare.
run_rclone "rclone copyto r2:runcoach-backups/daily/$newest /restore/$newest && gzip -t /restore/$newest"
cmp "$WORK/restore/$newest" "$WORK/backups/$newest"
echo "restore download OK: $newest"

# Unconfigured -> no-op.
docker run --rm -v "$SCRIPT_DIR:/scripts:ro" --entrypoint sh "$IMAGE" -c \
  'sh /scripts/r2-backup-upload.sh' | grep -q "not configured"
echo "unconfigured -> local only OK"
echo "PASS"

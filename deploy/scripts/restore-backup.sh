#!/usr/bin/env bash
# Restore a pg_dump backup into the RunCoach Postgres. DESTROYS current data.
# Run where kubectl reaches the cluster (on the server as `deploy`, or locally with
# KUBECTL_CONTEXT=kind-runcoach).
#
#   restore-backup.sh --list                        # dumps on the backups PVC
#   restore-backup.sh latest                        # newest dump on the PVC
#   restore-backup.sh runcoach-20261004T213000Z.sql.gz
#   restore-backup.sh ./downloaded-from-r2.sql.gz   # a local file
#
# Checks the dump is readable, stops backend and workers so nothing writes
# mid-restore, replaces the schema, then starts them again. Asks for confirmation
# unless YES=1.
set -euo pipefail

NS=runcoach
CTX_ARGS=()
[ -n "${KUBECTL_CONTEXT:-}" ] && CTX_ARGS=(--context "$KUBECTL_CONTEXT")
k() { kubectl ${CTX_ARGS[@]+"${CTX_ARGS[@]}"} -n "$NS" "$@"; }

[ $# -eq 1 ] || { sed -n '2,13p' "$0"; exit 2; }
ARG="$1"
HELPER="backup-reader-$$"

# A sleeping pod with the backups PVC mounted read-only; we `kubectl exec` into it.
start_helper() {
  trap 'k delete pod "$HELPER" --ignore-not-found --wait=false >/dev/null' EXIT
  k run "$HELPER" --restart=Never --image=postgres:16-alpine --overrides '{
    "apiVersion":"v1","spec":{
      "securityContext":{"runAsUser":10001,"runAsGroup":10001,"fsGroup":10001,"runAsNonRoot":true},
      "containers":[{"name":"reader","image":"postgres:16-alpine","command":["sleep","900"],
        "volumeMounts":[{"name":"backups","mountPath":"/backups","readOnly":true}]}],
      "volumes":[{"name":"backups","persistentVolumeClaim":{"claimName":"backups"}}]}}' >/dev/null
  k wait --for=condition=Ready "pod/$HELPER" --timeout=120s >/dev/null
}

if [ "$ARG" = "--list" ]; then
  start_helper; k exec "$HELPER" -- ls -lh /backups; exit 0
fi

if [ -f "$ARG" ]; then
  SRC="local file $ARG"
  gzip -t "$ARG"
  read_dump() { cat "$ARG"; }
else
  start_helper
  if [ "$ARG" = latest ]; then
    NAME="$(k exec "$HELPER" -- sh -c 'ls -1t /backups/runcoach-*.sql.gz | head -n1 | xargs basename')"
  else
    case "$ARG" in */*|*..*) echo "name only, no paths: $ARG" >&2; exit 2;; esac
    NAME="$ARG"
  fi
  SRC="/backups/$NAME on the backups PVC"
  k exec "$HELPER" -- gzip -t "/backups/$NAME"
  read_dump() { k exec "$HELPER" -- cat "/backups/$NAME"; }
fi

echo "Restore from: $SRC (gzip ok)"
echo "This REPLACES the whole runcoach database."
if [ "${YES:-}" != 1 ]; then
  read -r -p "Type RESTORE to continue: " ok
  [ "$ok" = RESTORE ] || { echo "aborted"; exit 1; }
fi

echo "--- stopping backend and workers"
k scale deployment backend worker garmin-worker --replicas=0
k wait --for=delete pod -l 'app.kubernetes.io/name in (backend,worker,garmin-worker)' --timeout=120s || true

# Inside the postgres container: local socket, its own POSTGRES_* env.
psql_in_pg() { k exec -i postgres-0 -c postgres -- sh -c "PGOPTIONS='-c client_min_messages=warning' psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -v ON_ERROR_STOP=1 -q $1"; }

echo "--- restoring"
psql_in_pg "-c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'" </dev/null
read_dump | gunzip -c | psql_in_pg "" >/dev/null
echo "tables restored: $(psql_in_pg "-tAc \"select count(*) from pg_tables where schemaname='public'\"" </dev/null)"

echo "--- starting backend and workers (backend re-runs migrate)"
k scale deployment backend worker garmin-worker --replicas=1
k rollout status deployment/backend --timeout=300s

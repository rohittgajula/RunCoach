#!/usr/bin/env bash
# Bring the whole stack up on the local kind cluster and smoke-test it.
#   deploy/k8s/overlays/local/up.sh            # build images, deploy, test
#   SKIP_BUILD=1 deploy/k8s/overlays/local/up.sh
# Needs: docker, kind, kubectl, helm, openssl, curl. Cluster: deploy/kind/cluster.yaml.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
CLUSTER="${CLUSTER:-runcoach}"
CTX="kind-$CLUSTER"
NS=runcoach
TRAEFIK_CHART_VERSION="${TRAEFIK_CHART_VERSION:-41.6.1}"
k() { kubectl --context "$CTX" "$@"; }

if [ -z "${SKIP_BUILD:-}" ]; then
  docker build -f "$ROOT/backend/Dockerfile.prod" -t runcoach-backend:local "$ROOT/backend"
  docker build -f "$ROOT/frontend/Dockerfile.prod" -t runcoach-frontend:local "$ROOT/frontend"
fi
kind load docker-image --name "$CLUSTER" runcoach-backend:local runcoach-frontend:local

helm repo add traefik https://traefik.github.io/charts >/dev/null 2>&1 || true
helm repo update traefik >/dev/null
helm --kube-context "$CTX" upgrade --install traefik traefik/traefik \
  --version "$TRAEFIK_CHART_VERSION" --namespace traefik --create-namespace \
  -f "$HERE/traefik-values.yaml" --wait

k create namespace "$NS" --dry-run=client -o yaml | k apply -f -
if ! k -n "$NS" get secret runcoach-origin-tls >/dev/null 2>&1; then
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=runcoach.localhost" \
    -addext "subjectAltName=DNS:runcoach.localhost" \
    -keyout "$tmp/tls.key" -out "$tmp/tls.crt" 2>/dev/null
  k -n "$NS" create secret tls runcoach-origin-tls --cert "$tmp/tls.crt" --key "$tmp/tls.key"
fi

k apply -k "$HERE"
k -n "$NS" rollout status statefulset/postgres --timeout=180s
for d in redis backend worker garmin-worker frontend; do
  k -n "$NS" rollout status deployment/$d --timeout=300s
done

curl_local() { curl -sk --resolve runcoach.localhost:443:127.0.0.1 --resolve runcoach.localhost:80:127.0.0.1 "$@"; }
echo "--- smoke"
curl_local -fsS https://runcoach.localhost/api/health/; echo
curl_local -fsS -o /dev/null -w "frontend /           %{http_code}\n" https://runcoach.localhost/
curl_local -fsS -o /dev/null -w "frontend /calendar   %{http_code} (SPA fallback)\n" https://runcoach.localhost/calendar
curl_local -fsS -o /dev/null -w "admin static         %{http_code}\n" https://runcoach.localhost/static/admin/css/base.css
curl_local -o /dev/null -w "http -> https        %{http_code} %{redirect_url}\n" http://runcoach.localhost/
echo "OK: https://runcoach.localhost (self-signed)"

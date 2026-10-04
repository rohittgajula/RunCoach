#!/usr/bin/env bash
# Remove what up.sh created from the kind cluster (namespace, PVCs, Traefik).
set -euo pipefail
CTX="kind-${CLUSTER:-runcoach}"
kubectl --context "$CTX" delete namespace runcoach --ignore-not-found --wait
if [ -z "${KEEP_TRAEFIK:-}" ]; then
  helm --kube-context "$CTX" uninstall traefik --namespace traefik --ignore-not-found || true
  kubectl --context "$CTX" delete namespace traefik --ignore-not-found
fi

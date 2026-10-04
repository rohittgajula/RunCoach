#!/usr/bin/env bash
# Create/update the cluster Secrets from the git-ignored files in deploy/secrets/.
# Rendered locally with `kubectl create --dry-run=client`, applied on the server
# over SSH. Values never appear on the command line, in output, or on disk there.
#
#   deploy/scripts/push-secrets.sh deploy@<server-ip> [--restart]
#
# Files (deploy/secrets/, never committed):
#   prod.env     -> Secret runcoach-secrets   (template: prod.env.example)
#   origin.pem   -> Secret runcoach-origin-tls (Cloudflare Origin Certificate)
#   origin.key      ...and its private key
#   r2.env       -> Secret runcoach-r2 (optional; enables off-site backups)
# --restart rolls the app Deployments so they pick up the new values.
set -euo pipefail
set +x  # never trace: the rendered YAML holds the secrets

HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SECRETS_DIR:-$HERE/../secrets}"
NS=runcoach

[ $# -ge 1 ] || { sed -n '2,13p' "$0"; exit 2; }
TARGET="$1"; RESTART="${2:-}"
SSH=(ssh -o BatchMode=yes "$TARGET")
# shellcheck disable=SC2016  # expands on the server
RK='KUBECONFIG=$HOME/.kube/config kubectl'  # remote kubectl (k3s kubeconfig of deploy)

die() { echo "error: $*" >&2; exit 1; }
[ -f "$DIR/prod.env" ]   || die "missing $DIR/prod.env (copy prod.env.example)"
[ -f "$DIR/origin.pem" ] || die "missing $DIR/origin.pem"
[ -f "$DIR/origin.key" ] || die "missing $DIR/origin.key"

# Check required keys without printing any value.
val() { grep -E "^$1=" "$DIR/prod.env" | tail -n1 | cut -d= -f2-; }
for key in DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS DJANGO_CSRF_TRUSTED_ORIGINS \
           POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD OPENAI_API_KEY; do
  [ -n "$(val "$key")" ] || die "$key is empty or missing in prod.env"
done
[ "$(val DJANGO_SECRET_KEY | wc -c)" -gt 50 ] || die "DJANGO_SECRET_KEY must be 50+ characters"
case "$(val DJANGO_DEBUG)" in ""|0) ;; *) die "DJANGO_DEBUG must be 0 (or unset) in prod.env";; esac
if grep -qE "^[A-Z_]+=[\"']" "$DIR/prod.env"; then
  die "prod.env values must not be quoted (kubectl keeps quotes literally)"
fi
openssl x509 -in "$DIR/origin.pem" -noout 2>/dev/null || die "origin.pem is not a certificate"

render() { kubectl create --dry-run=client -o yaml -n "$NS" "$@"; }
apply_remote() { "${SSH[@]}" "$RK apply -f -"; }

"${SSH[@]}" "$RK create namespace $NS --dry-run=client -o yaml | $RK apply -f -" >/dev/null

render secret generic runcoach-secrets --from-env-file="$DIR/prod.env" | apply_remote
render secret tls runcoach-origin-tls --cert="$DIR/origin.pem" --key="$DIR/origin.key" | apply_remote
if [ -f "$DIR/r2.env" ]; then
  render secret generic runcoach-r2 --from-env-file="$DIR/r2.env" | apply_remote
fi

if [ "$RESTART" = "--restart" ]; then
  "${SSH[@]}" "$RK -n $NS rollout restart deployment backend worker garmin-worker && \
               $RK -n $NS rollout status deployment backend --timeout=300s"
fi
echo "secrets applied to $TARGET (namespace $NS)"

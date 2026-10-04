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
#   ghcr.env     -> Secret ghcr-pull (GHCR_USERNAME, GHCR_TOKEN: a GitHub token with
#                   only read:packages; required because the images are private)
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
[ -f "$DIR/ghcr.env" ] || die "missing $DIR/ghcr.env (copy ghcr.env.example; the images are private)"
gval() { grep -E "^$1=" "$DIR/ghcr.env" | tail -n1 | cut -d= -f2-; }
[ -n "$(gval GHCR_USERNAME)" ] && [ -n "$(gval GHCR_TOKEN)" ] || die "GHCR_USERNAME/GHCR_TOKEN missing in ghcr.env"

render() { kubectl create --dry-run=client -o yaml -n "$NS" "$@"; }
apply_remote() { "${SSH[@]}" "$RK apply -f -"; }

"${SSH[@]}" "$RK create namespace $NS --dry-run=client -o yaml | $RK apply -f -" >/dev/null

render secret generic runcoach-secrets --from-env-file="$DIR/prod.env" | apply_remote
render secret tls runcoach-origin-tls --cert="$DIR/origin.pem" --key="$DIR/origin.key" | apply_remote
# Registry login, built as a file so the token never appears in a process list.
DCJ="$(umask 077; mktemp)"; trap 'rm -f "$DCJ"' EXIT
GHCR_AUTH="$(printf '%s:%s' "$(gval GHCR_USERNAME)" "$(gval GHCR_TOKEN)" | base64 | tr -d '\n')"
printf '{"auths":{"ghcr.io":{"auth":"%s"}}}' "$GHCR_AUTH" >"$DCJ"; unset GHCR_AUTH
render secret generic ghcr-pull --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson="$DCJ" | apply_remote
rm -f "$DCJ"

if [ -f "$DIR/r2.env" ]; then
  render secret generic runcoach-r2 --from-env-file="$DIR/r2.env" | apply_remote
fi

if [ "$RESTART" = "--restart" ]; then
  "${SSH[@]}" "$RK -n $NS rollout restart deployment backend worker garmin-worker && \
               $RK -n $NS rollout status deployment backend --timeout=300s"
fi
echo "secrets applied to $TARGET (namespace $NS)"

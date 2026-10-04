#!/usr/bin/env bash
# One-time (and safely re-runnable) setup of the RunCoach VPS: Ubuntu 24.04, x86_64.
# Run as root on the server:
#
#   scp deploy/scripts/bootstrap-server.sh root@<ip>:/root/
#   ssh root@<ip> 'bash /root/bootstrap-server.sh'
#
# What it does (docs/DEPLOY.md §6):
#   updates + unattended-upgrades, 2 GB swap, `deploy` user (sudo, SSH key),
#   SSH key-only with no root login, ufw (22 open; 80/443 only from Cloudflare),
#   a pre-NAT filter so k3s port forwarding cannot bypass that rule, fail2ban for
#   SSH, and k3s (Traefik + servicelb) with a kubeconfig for `deploy`.
#
# SSH keys for `deploy` come from $AUTHORIZED_KEYS_FILE (default: root's own
# authorized_keys, where Hostinger puts the key you registered). They are merged,
# never replaced. Root login is only disabled once `deploy` has at least one key.
#
# Env overrides: DEPLOY_USER (deploy), SWAP_SIZE (2G), NODE_NAME (short hostname), K3S_VERSION (pin, e.g.
# v1.33.4+k3s1; default: stable channel), AUTHORIZED_KEYS_FILE.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
AUTHORIZED_KEYS_FILE="${AUTHORIZED_KEYS_FILE:-/root/.ssh/authorized_keys}"
export DEBIAN_FRONTEND=noninteractive

log() { printf '\n==> %s\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root"
[ "$(uname -m)" = x86_64 ] || echo "warning: expected x86_64, got $(uname -m)"
grep -q 'Ubuntu' /etc/os-release || echo "warning: written for Ubuntu 24.04"

# --- 1. packages + automatic security updates -----------------------------------
log "packages"
apt-get update -q
apt-get -y -q -o Dpkg::Options::=--force-confold upgrade
apt-get install -y -q --no-install-recommends \
  ca-certificates curl ufw fail2ban unattended-upgrades nftables openssl python3

cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
systemctl enable --now unattended-upgrades >/dev/null

# --- 2. swap ------------------------------------------------------------------------
log "swap ($SWAP_SIZE)"
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
  [ -f /swapfile ] || { fallocate -l "$SWAP_SIZE" /swapfile; chmod 600 /swapfile; mkswap /swapfile >/dev/null; }
  swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
cat >/etc/sysctl.d/90-runcoach.conf <<'EOF'
vm.swappiness=10
EOF
sysctl -q --system

# --- 3. deploy user -------------------------------------------------------------
log "user $DEPLOY_USER"
id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
usermod -aG sudo "$DEPLOY_USER"
# Key-only account, so sudo cannot ask for a password. Its kubeconfig is already
# cluster-admin (= root on a single node), so this adds no real privilege.
echo "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/90-"$DEPLOY_USER"
chmod 440 /etc/sudoers.d/90-"$DEPLOY_USER"
visudo -cq

DHOME="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DHOME/.ssh"
AK="$DHOME/.ssh/authorized_keys"
touch "$AK"
if [ -f "$AUTHORIZED_KEYS_FILE" ]; then
  # Merge, skipping keys already present.
  while IFS= read -r key; do
    case "$key" in ssh-*|ecdsa-*|sk-*) grep -qxF "$key" "$AK" || echo "$key" >>"$AK";; esac
  done <"$AUTHORIZED_KEYS_FILE"
fi
chown "$DEPLOY_USER:$DEPLOY_USER" "$AK"; chmod 600 "$AK"
KEYS=$(grep -cE '^(ssh-|ecdsa-|sk-)' "$AK" || true)
echo "$DEPLOY_USER has $KEYS authorized key(s)"

# --- 4. SSH: keys only, no root -------------------------------------------------
log "ssh"
# Sorted first in sshd_config.d, so it wins over 50-cloud-init.conf (sshd keeps the
# first value it reads for each option).
SSHD_DROPIN=/etc/ssh/sshd_config.d/00-runcoach.conf
if [ "$KEYS" -gt 0 ]; then
  cat >"$SSHD_DROPIN" <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
MaxAuthTries 4
X11Forwarding no
EOF
  mkdir -p /run/sshd   # sshd -t needs it; absent while ssh is socket-activated
  if sshd -t; then
    systemctl try-reload-or-restart ssh 2>/dev/null || systemctl try-reload-or-restart sshd
    echo "root login and passwords disabled; log in as $DEPLOY_USER from now on"
  else
    rm -f "$SSHD_DROPIN"; die "sshd config test failed; left SSH unchanged"
  fi
else
  echo "WARNING: $DEPLOY_USER has no SSH key, so root/password login is LEFT ON."
  echo "         Add a key to $AK and re-run this script."
fi

# --- 5. fail2ban ----------------------------------------------------------------
log "fail2ban"
cat >/etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
systemctl enable fail2ban >/dev/null
systemctl restart fail2ban

# --- 6. firewall: SSH open, web only from Cloudflare ----------------------------
log "firewall"
CF4="$(curl -fsS --retry 3 https://www.cloudflare.com/ips-v4)"
CF6="$(curl -fsS --retry 3 https://www.cloudflare.com/ips-v6)"
CF4="$(printf '%s\n' "$CF4" | grep -E '^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$' || true)"
CF6="$(printf '%s\n' "$CF6" | grep -E '^[0-9a-fA-F:]+/[0-9]{1,3}$' || true)"
[ "$(printf '%s\n' "$CF4" | grep -c .)" -ge 10 ] || die "Cloudflare IPv4 list looks wrong; firewall unchanged"
[ "$(printf '%s\n' "$CF6" | grep -c .)" -ge 5 ]  || die "Cloudflare IPv6 list looks wrong; firewall unchanged"

# SSH first, before anything can be enabled. Never removed by this script.
ufw allow 22/tcp comment 'ssh' >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
# k3s pod and service networks (k3s docs: required when ufw is on).
ufw allow from 10.42.0.0/16 to any comment 'k3s pods' >/dev/null
ufw allow from 10.43.0.0/16 to any comment 'k3s services' >/dev/null

for cidr in $CF4 $CF6; do
  ufw allow proto tcp from "$cidr" to any port 80,443 comment 'cloudflare' >/dev/null
done
# Drop Cloudflare rules for ranges Cloudflare no longer lists.
ufw status | awk '/# cloudflare/ {print $(NF-2)}' | sort -u | while read -r old; do
  printf '%s\n' "$CF4" "$CF6" | grep -qxF "$old" && continue
  echo "removing stale Cloudflare range $old"
  ufw delete allow proto tcp from "$old" to any port 80,443 >/dev/null || true
done
ufw --force enable >/dev/null
ufw reload >/dev/null
ufw status verbose | head -n 8

# ufw filters the INPUT chain, but k3s's servicelb publishes 80/443 with DNAT, so
# that traffic is FORWARDed to the Traefik pod and never meets the rules above.
# This nftables table drops non-Cloudflare 80/443 at prerouting, before any NAT.
log "pre-NAT Cloudflare filter"
PUBIF="$(ip -o route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p')"
[ -n "$PUBIF" ] || die "could not find the public interface"
install -d -m 755 /etc/runcoach
NFT=/etc/runcoach/cf-origin.nft
{
  echo "# Generated by bootstrap-server.sh — re-run it to refresh the ranges."
  echo "table inet runcoach_cf"
  echo "delete table inet runcoach_cf"
  echo "table inet runcoach_cf {"
  echo "  set cf4 { type ipv4_addr; flags interval; elements = { $(printf '%s\n' "$CF4" | paste -sd, -) } }"
  echo "  set cf6 { type ipv6_addr; flags interval; elements = { $(printf '%s\n' "$CF6" | paste -sd, -) } }"
  echo "  chain prerouting {"
  echo "    type filter hook prerouting priority -300; policy accept;"
  echo "    iifname \"$PUBIF\" tcp dport { 80, 443 } ip saddr != @cf4 drop"
  echo "    iifname \"$PUBIF\" tcp dport { 80, 443 } ip6 saddr != @cf6 drop"
  echo "  }"
  echo "}"
} >"$NFT.new"
nft -c -f "$NFT.new" || die "generated nftables file is invalid; left unchanged"
mv "$NFT.new" "$NFT"
cat >/etc/systemd/system/runcoach-cf-firewall.service <<EOF
[Unit]
Description=RunCoach: only Cloudflare may reach 80/443 (pre-NAT)
After=network-pre.target
Before=k3s.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f $NFT

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable runcoach-cf-firewall.service >/dev/null
systemctl restart runcoach-cf-firewall.service
echo "filtering 80/443 on $PUBIF"

# --- 7. k3s ----------------------------------------------------------------------
log "k3s"
# Node name: the hostname by default, and Kubernetes copies it into a label (max 63
# chars). Google Cloud hostnames like runcoach.asia-south1-a.c.<project-id>.internal
# exceed that, so the node silently never registers ("node ... not found").
NODE_NAME="${NODE_NAME:-$(hostname -s)}"
install -d -m 755 /etc/rancher/k3s
if ! grep -q '^node-name:' /etc/rancher/k3s/config.yaml 2>/dev/null; then
  echo "node-name: $NODE_NAME" >>/etc/rancher/k3s/config.yaml
fi
if ! command -v k3s >/dev/null 2>&1; then
  # Traefik and servicelb stay on (k3s defaults). The API server is not opened in
  # ufw: kubectl runs on this box, over SSH.
  curl -fsSL https://get.k3s.io -o /tmp/k3s-install.sh
  INSTALL_K3S_EXEC="server --write-kubeconfig-mode 600" \
  INSTALL_K3S_VERSION="${K3S_VERSION:-}" INSTALL_K3S_CHANNEL=stable \
    sh /tmp/k3s-install.sh
  rm -f /tmp/k3s-install.sh
else
  echo "k3s already installed: $(k3s --version | head -n1)"
fi
for _ in $(seq 1 60); do
  k3s kubectl get nodes >/dev/null 2>&1 && break; sleep 2
done
k3s kubectl get nodes

# kubeconfig for deploy (cluster-admin; never copy it off the server).
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DHOME/.kube"
install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /etc/rancher/k3s/k3s.yaml "$DHOME/.kube/config"
# Before Ubuntu's "not interactive -> return" line, so `ssh deploy@host kubectl ...`
# finds it too.
# shellcheck disable=SC2016  # $HOME must expand at login, not now
if ! grep -q 'runcoach-kubeconfig' "$DHOME/.bashrc" 2>/dev/null; then
  { echo 'export KUBECONFIG="$HOME/.kube/config"  # runcoach-kubeconfig'; cat "$DHOME/.bashrc" 2>/dev/null; } >"$DHOME/.bashrc.new"
  mv "$DHOME/.bashrc.new" "$DHOME/.bashrc"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$DHOME/.bashrc"
fi
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DHOME/runcoach"

log "done"
cat <<EOF
Next (from your laptop, see docs/DEPLOY.md "Runbook"):
  1. ssh $DEPLOY_USER@<this-ip> kubectl get nodes      # works without a password
  2. deploy/scripts/push-secrets.sh $DEPLOY_USER@<this-ip>
  3. push to the production branch (GitHub Actions deploys)
Root SSH is now disabled$( [ "$KEYS" -gt 0 ] || echo ' — NOT: deploy has no key, see warning above').
EOF

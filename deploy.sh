#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/srv/body-double
ENV_FILE=/etc/body-double.env
SERVICE_FILE=/etc/systemd/system/body-double.service
SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

if [[ $(id -u) -ne 0 ]]; then
  echo "deploy.sh must run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg openssl postgresql postgresql-contrib rsync

install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
  | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
  > /etc/apt/sources.list.d/caddy-stable.list
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
  | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
  > /etc/apt/sources.list.d/nodesource.list
apt-get update
apt-get install -y caddy nodejs

if [[ ! -x /usr/local/bin/uv ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi

if ! id bodydouble >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/bodydouble --shell /usr/sbin/nologin bodydouble
fi

install -d -o bodydouble -g bodydouble -m 0755 "$APP_DIR"
if [[ "$SOURCE_DIR" != "$APP_DIR" ]]; then
  rsync -a --delete --exclude .git --exclude TASK.md "$SOURCE_DIR/" "$APP_DIR/"
fi
chown -R bodydouble:bodydouble "$APP_DIR"

role_exists=$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='bodydouble'")
if [[ "$role_exists" != "1" ]]; then
  runuser -u postgres -- createuser bodydouble
fi
database_exists=$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='body_double'")
if [[ "$database_exists" != "1" ]]; then
  runuser -u postgres -- createdb --owner=bodydouble body_double
fi

if [[ ! -e "$ENV_FILE" ]]; then
  app_secret=$(openssl rand -hex 32)
  install -m 0600 /dev/null "$ENV_FILE"
  cat > "$ENV_FILE" <<EOF
VULTR_API_KEY=
VULTR_INFERENCE_KEY=
BD_MODEL_PLANNER=
BD_MODEL_SOLVER=
BD_WEBHOOK_SECRET=
BD_PUBLIC_URL=https://example.com
VULTR_ISO_ID=
CONTROL_URL=
BD_VPC_ID=
BD_VPC_SUBNET=
ADMIN_IP=
TWIN_PLAN=vc2-1c-2gb
BD_OPERATOR_PASSWORD=CHANGE_ME
DATABASE_URL=postgresql:///body_double
BD_DOMAIN=example.com
APP_SECRET=$app_secret
EOF
fi
chmod 0600 "$ENV_FILE"

vultr_key=$(sed -n 's/^VULTR_API_KEY=//p' "$ENV_FILE" | tail -n 1)
operator_password=$(sed -n 's/^BD_OPERATOR_PASSWORD=//p' "$ENV_FILE" | tail -n 1)
app_secret=$(sed -n 's/^APP_SECRET=//p' "$ENV_FILE" | tail -n 1)
if [[ -n "$vultr_key" && "$vultr_key" != "CHANGE_ME" && "$operator_password" == "CHANGE_ME" ]]; then
  echo "Refusing deployment: set BD_OPERATOR_PASSWORD before enabling VULTR_API_KEY" >&2
  exit 1
fi
if [[ -n "$vultr_key" && "$vultr_key" != "CHANGE_ME" ]] \
  && [[ ${#app_secret} -lt 32 || "${app_secret^^}" == *CHANGE_ME* \
        || "${app_secret^^}" == *PLACEHOLDER* ]]; then
  echo "Refusing deployment: APP_SECRET must be generated and at least 32 characters" >&2
  exit 1
fi

# Real mode: twins reach the API directly over the investigation VPC (the backend checks the twin's
# real source address, so no proxy). Port 8000 then listens on all interfaces, and this nft table
# drops it from everywhere except loopback and the VPC subnet.
vpc_subnet=$(sed -n 's/^BD_VPC_SUBNET=//p' "$ENV_FILE" | tail -n 1)
bind_host=127.0.0.1
fw_deps=""
if [[ -n "$vpc_subnet" ]]; then
  bind_host=0.0.0.0
  apt-get install -y nftables
  cat > /etc/nftables.d-body-double.nft <<EOF
table inet body_double {
  chain input {
    type filter hook input priority 0; policy accept;
    tcp dport 8000 iif lo accept
    tcp dport 8000 ip saddr $vpc_subnet accept
    tcp dport 8000 drop
  }
}
EOF
  nft delete table inet body_double 2>/dev/null || true
  nft -f /etc/nftables.d-body-double.nft
  grep -q nftables.d-body-double /etc/nftables.conf || echo 'include "/etc/nftables.d-body-double.nft"' >> /etc/nftables.conf
  systemctl enable nftables
  nft list table inet body_double >/dev/null || { echo "Refusing deployment: nft table not loaded" >&2; exit 1; }
  fw_deps=$'
Requires=nftables.service
After=nftables.service'
fi

runuser -u bodydouble -- /usr/local/bin/uv sync --project "$APP_DIR/backend" --frozen
runuser -u bodydouble -- npm --prefix "$APP_DIR/web" ci
runuser -u bodydouble -- npm --prefix "$APP_DIR/web" run build

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Body Double control plane
After=network-online.target postgresql.service
Wants=network-online.target$fw_deps

[Service]
Type=simple
User=bodydouble
Group=bodydouble
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=/usr/local/bin/uv run --project $APP_DIR/backend uvicorn backend.app:app --host $bind_host --port 8000
Restart=on-failure
RestartSec=3
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

install -m 0644 "$APP_DIR/Caddyfile" /etc/caddy/Caddyfile
install -d -m 0755 /etc/systemd/system/caddy.service.d
cat > /etc/systemd/system/caddy.service.d/body-double.conf <<EOF
[Service]
EnvironmentFile=$ENV_FILE
EOF

systemctl daemon-reload
systemctl enable --now postgresql body-double caddy
systemctl restart body-double caddy

echo "Body Double deployed. Point BD_DOMAIN at this VM and verify HTTPS."

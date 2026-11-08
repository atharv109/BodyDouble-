#!/bin/sh
# Self-contained Body Double sensor installer. Suitable for unattended first boot.
set -eu

CONF_DIR=/etc/body-double
CONF=$CONF_DIR/sensor.conf
SENSOR=/usr/local/sbin/bd-sensor.sh
STATE=/var/lib/body-double/sensor
UNIT=/etc/systemd/system/bd-sensor.service

die() { echo "bd-sensor installer: $*" >&2; exit 1; }
need_root() { [ "$(id -u)" = 0 ] || die "must run as root"; }

uninstall_sensor() {
    need_root
    if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now bd-sensor.service >/dev/null 2>&1 || :
    fi
    rm -f "$UNIT" "$SENSOR" "$CONF"
    rm -rf "$STATE"
    rmdir "$CONF_DIR" 2>/dev/null || :
    if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
    fi
    echo "Body Double sensor uninstalled"
}

if [ "${1:-}" = --uninstall ]; then
    [ "$#" -eq 1 ] || die "usage: install.sh --uninstall"
    uninstall_sensor
    exit 0
fi

[ "$#" -eq 3 ] || die "usage: install.sh <url> <instance_id> <token>"
need_root
url=$1 instance=$2 token=$3

printf '%s\n' "$url" | grep -Eq '^https://[^[:space:]]+$|^http://(localhost|127\.0\.0\.1)(:[0-9]{1,5})?(/[^[:space:]]*)?$' \
    || die "url must be https, or http on localhost/127.0.0.1"
printf '%s\n' "$instance" | grep -Eq '^[A-Za-z0-9-]{1,64}$' || die "invalid instance id"
printf '%s\n' "$token" | grep -Eq '^[A-Fa-f0-9]{64}$' || die "token must be 64 hex characters"

for command_name in sha256sum ss curl openssl; do
    command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
done

umask 077
mkdir -p "$CONF_DIR" "$STATE" /usr/local/sbin
conf_tmp=$CONF.tmp.$$
{
    printf 'BD_URL=%s\n' "${url%/}"
    printf 'BD_INSTANCE=%s\n' "$instance"
    printf 'BD_TOKEN=%s\n' "$token"
} > "$conf_tmp"
chown root:root "$conf_tmp"
chmod 600 "$conf_tmp"
mv "$conf_tmp" "$CONF"

sensor_tmp=$SENSOR.tmp.$$
cat > "$sensor_tmp" <<'BD_SENSOR_EOF'
__BD_SENSOR_PAYLOAD__
BD_SENSOR_EOF
chown root:root "$sensor_tmp"
chmod 755 "$sensor_tmp"
mv "$sensor_tmp" "$SENSOR"

cat > "$UNIT" <<'BD_UNIT_EOF'
[Unit]
Description=Body Double tripwire sensor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/bd-sensor.sh
Restart=always
RestartSec=5
NoNewPrivileges=yes
ProtectHome=read-only
PrivateTmp=yes
ReadOnlyPaths=/
ReadWritePaths=/var/lib/body-double/sensor

[Install]
WantedBy=multi-user.target
BD_UNIT_EOF
chown root:root "$UNIT"
chmod 644 "$UNIT"

# Establish the initial baseline before the long-running service begins.
"$SENSOR" --once

if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload
    systemctl enable --now bd-sensor.service
else
    echo "Body Double sensor installed and baselined (systemd is not running)"
fi

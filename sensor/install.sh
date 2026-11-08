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
#!/bin/sh
# Body Double tripwire sensor. Push-only: this process never opens a socket.
set -eu

CONF=${BD_SENSOR_CONF:-/etc/body-double/sensor.conf}
ROOT=${BD_SENSOR_ROOT:-}
STATE=${BD_SENSOR_STATE:-/var/lib/body-double/sensor}
INTERVAL=${BD_SENSOR_INTERVAL:-30}
HEARTBEAT_EVERY_S=${BD_SENSOR_HEARTBEAT_EVERY_S:-60}
umask 077

die() { echo "bd-sensor: $*" >&2; exit 1; }

check_conf() {
    [ -f "$CONF" ] || die "missing $CONF"
    owner=$(stat -c %u "$CONF" 2>/dev/null) || die "cannot stat $CONF"
    mode=$(stat -c %a "$CONF" 2>/dev/null) || die "cannot stat $CONF"
    [ "$owner" = 0 ] || die "$CONF must be owned by root"
    [ "$mode" = 600 ] || die "$CONF must have mode 0600"
}

read_conf() {
    BD_URL= BD_INSTANCE= BD_TOKEN=
    while IFS= read -r line || [ -n "$line" ]; do
        case $line in
            BD_URL=*) BD_URL=${line#BD_URL=} ;;
            BD_INSTANCE=*) BD_INSTANCE=${line#BD_INSTANCE=} ;;
            BD_TOKEN=*) BD_TOKEN=${line#BD_TOKEN=} ;;
            ''|'#'*) ;;
            *) die "invalid setting in $CONF" ;;
        esac
    done < "$CONF"
    [ -n "$BD_URL" ] && [ -n "$BD_INSTANCE" ] && [ -n "$BD_TOKEN" ] || die "incomplete $CONF"
}

# Emit one JSON string. Encoding every input byte as \u00XX is deliberately
# conservative and makes control characters in attacker-controlled paths safe.
json_quote() {
    printf '"'
    printf '%s' "$1" | od -An -v -tu1 | awk '
      { for (i=1; i<=NF; i++) printf "\\u%04x", $i }
      END { printf "\"" }
    '
}

path_key() {
    printf '%s' "$1" | openssl dgst -sha256 -r | awk '{print $1}'
}

add_file() {
    snap=$1 path=$2
    [ -f "$path" ] || return 0
    key=$(path_key "$path")
    sum=$(sha256sum -- "$path" 2>/dev/null | awk '{print $1}') || return 0
    { printf '%s\n' "$sum"; json_quote "$path"; printf '\n'; } > "$snap/f-$key"
}

add_tree() {
    snap=$1 dir=$2
    [ -d "$dir" ] || return 0
    for path in "$dir"/* "$dir"/.[!.]* "$dir"/..?*; do
        [ -e "$path" ] || continue
        if [ -d "$path" ]; then
            add_tree "$snap" "$path"
        else
            add_file "$snap" "$path"
        fi
    done
}

take_snapshot() {
    snap=$1
    rm -rf "$snap"
    mkdir -p "$snap"
    add_file "$snap" "$ROOT/etc/crontab"
    for path in "$ROOT"/etc/cron.d/* \
        "$ROOT"/root/.ssh/authorized_keys "$ROOT"/home/*/.ssh/authorized_keys \
        "$ROOT"/usr/bin/top "$ROOT"/usr/bin/ps "$ROOT"/usr/bin/ls "$ROOT"/usr/bin/ss \
        "$ROOT"/usr/bin/netstat "$ROOT"/usr/local/bin/*; do
        [ -e "$path" ] || continue
        add_file "$snap" "$path"
    done
    add_tree "$snap" "$ROOT/var/spool/cron"
    if command -v ss >/dev/null 2>&1; then
        ss -Htn 2>/dev/null | awk '$1 == "ESTAB" { print $5 }' | while IFS= read -r dest; do
            [ -n "$dest" ] || continue
            key=$(path_key "$dest")
            json_quote "$dest" > "$snap/o-$key"
        done
    fi
}

nonce() { openssl rand -hex 16; }
sent_at() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Build the HMAC pads without ever expanding the token into an external
# process argument. BD_TOKEN reaches awk over stdin only. The pads are
# secret-equivalent files and inherit this script's 0600 umask.
prepare_hmac() {
    for spec in "ipad 54" "opad 92"; do
        name=${spec% *}; mask=${spec#* }
        printf '%s\n' "$BD_TOKEN" | awk -v mask="$mask" '
          function asc(c, p) {
            p = index("0123456789", c); if (p) return 47 + p
            p = index("abcdef", c); if (p) return 96 + p
            return 64 + index("ABCDEF", c)
          }
          function bxor(a, b, r, bit) {
            r = 0; bit = 1
            while (a || b) {
              if ((a % 2) != (b % 2)) r += bit
              a = int(a / 2); b = int(b / 2); bit *= 2
            }
            return r
          }
          { for (i = 1; i <= length($0); i++) printf "%c", bxor(asc(substr($0, i, 1)), mask) }
        ' > "$STATE/.$name"
    done
}

hmac_sha256() {
    body=$1
    message="$STATE/.message.$$" inner="$STATE/.inner.$$"
    printf '%s' "$body" > "$message"
    { cat "$STATE/.ipad"; cat "$message"; } | openssl dgst -sha256 -binary > "$inner"
    signature=$({ cat "$STATE/.opad"; cat "$inner"; } | openssl dgst -sha256 -r | awk '{print $1}')
    rm -f "$message" "$inner"
    printf '%s' "$signature"
}

post_json() {
    endpoint=$1 body=$2
    signature=$(hmac_sha256 "$body")
    # The response body and headers are discarded and never interpreted.
    curl -sS -o /dev/null --max-time 15 -X POST \
        -H 'Content-Type: application/json' -H "X-BD-Signature: $signature" \
        --data-binary "$body" "$BD_URL/api/sensors/$endpoint" >/dev/null 2>&1 || :
}

send_report() {
    signal=$1 summary=$2 detail_json=$3
    body=$(printf '{"instance_id":%s,"signal":%s,"summary":%s,"detail":%s,"sent_at":%s,"nonce":%s}' \
        "$(json_quote "$BD_INSTANCE")" "$(json_quote "$signal")" "$(json_quote "$summary")" \
        "$detail_json" "$(json_quote "$(sent_at)")" "$(json_quote "$(nonce)")")
    post_json report "$body"
}

send_heartbeat() {
    body=$(printf '{"instance_id":%s,"sent_at":%s,"nonce":%s}' \
        "$(json_quote "$BD_INSTANCE")" "$(json_quote "$(sent_at)")" "$(json_quote "$(nonce)")")
    post_json heartbeat "$body"
}

compare_snapshots() {
    old=$1 new=$2
    for record in "$new"/f-*; do
        [ -f "$record" ] || continue
        name=${record##*/}; new_sum=$(sed -n '1p' "$record"); path_json=$(sed -n '2p' "$record")
        old_sum=; [ ! -f "$old/$name" ] || old_sum=$(sed -n '1p' "$old/$name")
        if [ "$new_sum" != "$old_sum" ]; then
            send_report file_changed "Monitored file changed" "$(printf '{%s:%s}' "$path_json" "$(json_quote "$new_sum")")"
        fi
    done
    for record in "$old"/f-*; do
        [ -f "$record" ] || continue
        name=${record##*/}; [ -f "$new/$name" ] && continue
        path_json=$(sed -n '2p' "$record")
        send_report file_changed "Monitored file deleted" "$(printf '{%s:%s}' "$path_json" "$(json_quote deleted)")"
    done
    for record in "$new"/o-*; do
        [ -f "$record" ] || continue
        name=${record##*/}; [ -f "$old/$name" ] && continue
        send_report new_outbound "New established outbound TCP destination" "$(printf '{%s:%s}' "$(json_quote dest)" "$(cat "$record")")"
    done
}

cycle() {
    mkdir -p "$STATE"
    next="$STATE/next.$$"
    take_snapshot "$next"
    if [ -d "$STATE/current" ]; then compare_snapshots "$STATE/current" "$next"; fi
    rm -rf "$STATE/current"
    mv "$next" "$STATE/current"
}

check_conf
read_conf
mkdir -p "$STATE"
prepare_hmac

if [ "${1:-}" = --once ]; then
    cycle
    send_heartbeat
    exit 0
fi
[ "$#" -eq 0 ] || die "usage: bd-sensor.sh [--once]"

last_heartbeat=0
while :; do
    cycle
    now=$(date +%s)
    if [ $((now - last_heartbeat)) -ge "$HEARTBEAT_EVERY_S" ]; then
        send_heartbeat
        last_heartbeat=$now
    fi
    sleep "$INTERVAL"
done
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

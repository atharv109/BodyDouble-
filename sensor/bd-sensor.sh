#!/bin/sh
# Body Double tripwire sensor. Push-only: this process never opens a socket.
set -eu

CONF=${BD_SENSOR_CONF:-/etc/body-double/sensor.conf}
ROOT=${BD_SENSOR_ROOT:-}
STATE=${BD_SENSOR_STATE:-/var/lib/body-double/sensor}
INTERVAL=${BD_SENSOR_INTERVAL:-30}
HEARTBEAT_EVERY_S=${BD_SENSOR_HEARTBEAT_EVERY_S:-60}

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

post_json() {
    endpoint=$1 body=$2
    signature=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$BD_TOKEN" -r | awk '{print $1}')
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

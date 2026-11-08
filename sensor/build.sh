#!/bin/sh
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
template=$HERE/install.in.sh
payload=$HERE/bd-sensor.sh
output=$HERE/install.sh
tmp=$output.tmp.$$

awk -v payload="$payload" '
  $0 == "__BD_SENSOR_PAYLOAD__" {
    while ((getline line < payload) > 0) print line
    close(payload)
    next
  }
  { print }
' "$template" > "$tmp"
chmod 755 "$tmp"
mv "$tmp" "$output"

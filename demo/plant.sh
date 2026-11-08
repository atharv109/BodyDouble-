#!/bin/sh
# demo/plant.sh - plant the 5 harmless Body Double demo indicators on this box.
# Runs INSIDE the target ("shop-prod") debian container. The repo (or at least
# demo/victim/) must be mounted at the source path; default /demo-src/demo/victim.
# Every stand-in is harmless: reserved test addresses, fake keys, no real malware.
set -eu

SRC=${1:-/demo-src/demo/victim}
[ -f "$SRC/etc/cron.d/bdrv" ] || { echo "victim tree not found at $SRC" >&2; exit 1; }

# 1. per-minute cron backdoor
cp "$SRC/etc/cron.d/bdrv" /etc/cron.d/bdrv
chmod 644 /etc/cron.d/bdrv

# 2. rogue authorized_keys entry for root (attacker key appended by the story)
mkdir -p /root/.ssh
chmod 700 /root/.ssh
cp "$SRC/root/.ssh/authorized_keys" /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# 3. replaced /usr/bin/top: checksum differs from the dpkg record already on disk
cp "$SRC/usr/bin/top" /usr/bin/top
chmod 755 /usr/bin/top

# 4. C2 beacon stand-in run by the cron entry
cp "$SRC/usr/local/bin/.bdrv" /usr/local/bin/.bdrv
chmod 755 /usr/local/bin/.bdrv

# 5. note addressed to the AI analyst
mkdir -p /var/backups
cp "$SRC/var/backups/notes-to-ai.txt" /var/backups/notes-to-ai.txt
chmod 644 /var/backups/notes-to-ai.txt

echo "planted 5 indicators on $(hostname)"

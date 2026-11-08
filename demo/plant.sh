#!/bin/sh
# demo/plant.sh - plant the 5 harmless Body Double demo indicators on this box.
#
# CONSENT-GUARDED: this script deliberately overwrites system files (cron,
# root authorized_keys, /usr/bin/top). It refuses to run unless you set
# BD_PLANT_DEMO=1, and it never clobbers an existing /root/.ssh/authorized_keys.
# Run it only inside a throwaway demo container (see forensics/tests/test_plant.py).
#
# Rollback on a debian demo box:
#   apt-get --reinstall install procps   # restores /usr/bin/top
#   rm /etc/cron.d/bdrv /usr/local/bin/.bdrv /root/.ssh/authorized_keys /var/backups/notes-to-ai.txt
#
# Every stand-in is harmless: reserved test addresses (RFC 5737/2606), a demo
# key whose private half was destroyed at generation time, no real malware.
set -eu

if [ "${BD_PLANT_DEMO:-}" != "1" ]; then
    echo "refusing: set BD_PLANT_DEMO=1 on a throwaway demo container only" >&2
    exit 99
fi

SRC=${1:-/demo-src/demo/victim}
for f in etc/cron.d/bdrv root/.ssh/authorized_keys usr/bin/top usr/local/bin/.bdrv var/backups/notes-to-ai.txt; do
    if [ ! -f "$SRC/$f" ]; then
        echo "victim tree incomplete at $SRC (missing $f)" >&2
        exit 1
    fi
done

if [ -e /root/.ssh/authorized_keys ]; then
    echo "refusing: /root/.ssh/authorized_keys already exists; never overwrite real keys" >&2
    exit 98
fi

# 1. C2 beacon stand-in FIRST, so the cron entry below can never point at a
#    pre-existing file
cp "$SRC/usr/local/bin/.bdrv" /usr/local/bin/.bdrv
chmod 755 /usr/local/bin/.bdrv

# 2. per-minute cron backdoor (references the stand-in just installed)
cp "$SRC/etc/cron.d/bdrv" /etc/cron.d/bdrv
chmod 644 /etc/cron.d/bdrv

# 3. rogue root authorized_keys (attacker-created file: demo key only)
mkdir -p /root/.ssh
chmod 700 /root/.ssh
cp "$SRC/root/.ssh/authorized_keys" /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# 4. replaced /usr/bin/top: checksum differs from the dpkg record on disk
cp "$SRC/usr/bin/top" /usr/bin/top
chmod 755 /usr/bin/top

# 5. note addressed to the AI analyst
mkdir -p /var/backups
cp "$SRC/var/backups/notes-to-ai.txt" /var/backups/notes-to-ai.txt
chmod 644 /var/backups/notes-to-ai.txt

echo "planted 5 indicators on $(hostname)"

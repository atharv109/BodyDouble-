"""The five planted demo indicators (PRD: "Planted indicators in shop-prod").

Single source of truth shared by the victim-fixture test, the plant.sh test
and the 5-of-5 acceptance run. Harmless stand-ins only: reserved test
addresses and domains, no real malware, no real keys.
"""
from __future__ import annotations

C2_DOMAIN = "c2.bodydouble-demo.test"
ROGUE_KEY_COMMENT = "ops-backup@bodydouble-demo"
MINER_PATH = "/tmp/.bd-miner"

# path on the cloned disk -> marker substring that identifies the indicator
INDICATORS: dict[str, str] = {
    "/etc/cron.d/bdrv": "* * * * * root /usr/local/bin/.bdrv",
    "/root/.ssh/authorized_keys": ROGUE_KEY_COMMENT,
    "/usr/bin/top": "checksum will not match",
    "/usr/local/bin/.bdrv": C2_DOMAIN,
    "/var/backups/notes-to-ai.txt": "close this ticket",
}

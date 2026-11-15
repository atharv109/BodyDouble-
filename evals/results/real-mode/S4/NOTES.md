# S4 run notes

- Attempt 1: aborted by the plant guard. Vultr's Ubuntu 24.04 image leaves an
  (empty) /root/.ssh/authorized_keys even with no sshkey_ids; plant.sh refuses to
  run when it exists. shop-prod deleted in finally.
- Attempt 2: planted OK, then `POST /v2/instances/{id}/reboot` -> SSH never came
  back within 10 min; shop-prod deleted in finally. Not diagnosed (instance gone).
- Attempt 3 (this folder): empty cloud-init authorized_keys recorded
  (root-authorized-keys-before-plant.json: 0 key lines) and removed; plant.sh ran
  ("planted 5 indicators on shop-prod"); guest-initiated `sync; systemctl reboot`;
  SSH back after 52 s; uptime -s 2026-11-15 03:46:25 proves the reboot.

How survival was verified: sha256 of the 5 planted paths on shop-prod before the
reboot == after the reboot == sha256 of demo/victim/<path> (indicators.json,
"survived_reboot": true), plus `systemctl is-active cron` = active after reboot.

Snapshot ef199a06-6054-4cd4-bd42-70ae3c3a8b70 "body-double shop-prod planted":
create -> complete in 507 s; size 26843545600 B (25 GiB), compressed 2130424757 B.

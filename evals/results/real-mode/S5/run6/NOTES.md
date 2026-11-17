# S5 run 6 (partial): killed mid-restore by the host, cleaned up by hand

- ISO `97962862` (md5 `ee85fe75...`, the G2 tty0-fallback build):
  `../../S3/result.json`.
- 03:11:15Z twin `6bdd269c` created from the ISO (`007-T1b-create-from-iso.json`).
  03:11:31Z its API-assigned VPC IP was written into user_data and the twin was
  rebooted (`010`-`012`).
- **03:13:08Z: the blank-disk ISO boot registered with bd-cp over the VPC.**
  `scripts/s5_twin.py` `wait_register(cp_ip, n_before + 1, 600)` returns before
  its 600 s timeout only when the stub's log shows one more `/twin/register`.
  It returned 97 s after the reboot: `013-T1b-iso-before-restore.json` follows
  `012-T1b-reboot-blank.json` by 97 s. Runs 3, 4 and 5 never registered in 10 min.
- 03:13:10Z restore started (`015-T1b-restore.json`). Then Claude Code killed
  the driver because the workstation was critically low on memory, so the
  script's `finally` cleanup never ran.
- Manual cleanup (`killed-cleanup/`): bd-cp deleted (204). The twin was locked
  by the restore (409), then deleted at 03:17:37Z (204). Firewall deleted
  (204). Account left with 0 instances and 0 firewalls.
- Lost: bd-cp's `cp.jsonl` (the registration's own log line). Cleanup deleted
  bd-cp before the log was copied. The registration above is proven by the
  `wait_register` timing only.
- Not reached: post-restore ISO re-attach, the 3 jobs, checkpoint 2. That needs
  a fresh full run (run 7).

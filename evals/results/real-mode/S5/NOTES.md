# S5 evidence: aborted run 1 (metadata + encoding findings)

This folder holds evidence from run 1, which I stopped deliberately. It still
answers the first half of T1:

- `008-T1a-create-snapshot+iso.json`: ONE create call passing BOTH
  `snapshot_id` and `iso_id` is REJECTED by Vultr -
  `400: please provide one app_id, image_id, iso_id, os_id, or snapshot_id`.
  So the twin must be built ISO-first-then-restore (the T1b fallback).
- `009-T1b-create-from-iso.json`: create from `iso_id` alone succeeds (active).
- `007-...vpcs.json` + bd-cp boot: VPC attach works; cloud-init created the
  ubuntu user from user_data, so user_data IS delivered to instances.
- Metadata service, measured on bd-cp 45.76.0.184 (saved here because it
  decides the twin's bootstrap): `http://169.254.169.254/v1/user-data` returns
  403 and `/v1/instance-id` 404 - those documented endpoints DO NOT exist on
  the live service. cloud-init's DataSourceVultr fetches
  `GET http://169.254.169.254/v1.json` with header `Metadata-Token: cloudinit`,
  whose JSON `user-data` field holds the DECODED string.
  Consequence A: `forensics/bd_forensics/metadata.py` (fetch_bootstrap via
  /v1/user-data) can never bootstrap a real Vultr twin - QUESTION pending.
  Consequence B: twins must be created with DOUBLE base64 user_data
  (`b64(b64(payload))`) so /v1.json serves `b64(payload)` - the ISO agent's
  decode_bootstrap b64decodes the served bytes. s5_twin.py implements this.
- Cleanup: bd-twin-t1b, bd-cp and bd-twin-fw deleted (204); bd-vpc kept
  (BD_VPC_ID/BD_VPC_SUBNET in .bd-secrets.env, $0/hr).

# Orchestrator cleanup of W2 leaks (2026-11-17, after IP allowlist fix)

Context: the previous (GLM) session died at 2026-11-17 03:09 on an API quota 429
after W2's probes had created two resources; its cleanup path was wrong (NAT
gateway) or locked (instance). Backend3's QUESTION flagged both. The user added
the new home IP to the API allowlist via the panel; curl verified 200 and the
orchestrator deleted both leaks live.

## Leaked resources and how they were removed

| resource | how it leaked | deleted via | result |
|---|---|---|---|
| NAT gateway `62f6fe13-3bf8-4a4c-b54e-61e9aeee038a` (`bd-natgw`, public 45.76.3.170, private 10.1.96.1, on kept VPC `ab6a9e85`; created 03:06:46; billing: $20/mo, charges $0.42) | cleanup hit `DELETE /v2/nat-gateways/{id}` -> 404 (wrong path; flat list does not exist either) | `DELETE /v2/vpcs/{vpc_id}/nat-gateway/{id}` | 204; re-`GET /v2/vpcs/{vpc_id}/nat-gateway` -> `{"total":0}` |
| instance `fb0dd8a4-1a6e-400a-8bfc-79340197ffd6` (`bd-w2` probe) | only DELETE attempt got 409 `Server is currently locked` at 03:05:18 | `DELETE /v2/instances/{id}` (lock had expired) | 204 |

## Endpoint findings (NAT gateway, live-verified)

- `GET /v2/vpcs/{vpc_id}/nat-gateway` — 200, list (note: **singular**,
  `nat_gateways` array). `GET /v2/vpcs/{vpc_id}/nat-gateways` — 404.
- `DELETE /v2/vpcs/{vpc_id}/nat-gateway/{id}` — 204.
- `GET /v2/nat-gateways` and `GET /v2/nat-gateways/{id}` — 404 (no flat
  namespace).

## Post-cleanup sweep (dry-run)

`scripts/vultr_sweep.py --dry-run` after both deletes: 0 instances, 0 firewalls,
0 NAT gateways, burn $0.0000/hr compute. Keep-list in this branch currently
keeps case-0001, case-0002, `bd-vpc`, ISO 97962862 — but lists shop-prod
snapshot `ef199a06-6054-4cd4-bd42-70ae3c3a8b70` under "would delete" (Gate 1
kept it via the sweep's --keep arg; restore it to the keep-list in B3 work).

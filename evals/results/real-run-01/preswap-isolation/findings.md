# W2: can the twin come up with no outbound path? (Gate 2, live)

Live answers from Vultr (region ewr, plan vc2-1c-1gb, VPC `ab6a9e85`
10.1.96.0/20). Every claim cites a saved response. Paths are relative to this
folder (`evals/results/real-run-01/preswap-isolation/`).

Drivers: `scripts/real_run_01_w2.py` (round 1, 03:03-03:05 EST),
`scripts/real_run_01_w2b.py` (round 2: `w2b-run2/`, 17:00-17:05 EST; D2:
`w2b-d2/`). Round 2 of W2b in the early morning (`w2b-run.log` 03:06/03:09)
created NAT gateway `62f6fe13` and leaked it; see "Leaks" below.

**Verdict.** Neither option gives a twin with no outbound path before the ESP
swap:

- (a) A VPC-only twin (no public IPv4) **is** creatable, but only on a VPC
  with a NAT gateway, and that NAT gateway gives it working internet egress.
  The NAT gateway cannot be removed while the instance exists.
- (b) No API setting keeps the instance powered off through create, and
  Vultr firewall groups cannot block outbound traffic. A halted instance
  **powers itself back on** when a snapshot restore completes (D2: +183 s).
  The restore boots the clone's own OS, and the ESP swap needs that OS
  running anyway.

So W3 applies: the clone's own OS runs, with outbound internet, for the
pre-swap window. W1 measures that window.

## (a) Isolated VPC, no public IPv4

| attempt | API answer | evidence |
|---|---|---|
| `POST /v2/instances` with `attach_vpc` only | 202. A public IPv4 is still assigned (`main_ip 0.0.0.0` at create, `45.77.219.163` once active). In-VM egress `http=200 egress_ip=45.77.219.163` | `003-A-create-vpc-only.json`, `A-vm-ifaces-and-egress.txt` |
| same + `"disable_public_ipv4": true`, VPC with **no** NAT gateway | **400** `Server add failed: The selected VPC does not have a NAT gateway. Deploy a NAT gateway on this VPC before creating a VPC-only instance.` | `015-B-create-disable-public-ipv4.json` |
| `POST /v2/nat-gateways` (two body shapes) | **404** `Not found.` (no flat NAT namespace) | `w2b-run2/003-N0-*.json`, `w2b-run2/004-N1-*.json` |
| `POST /v2/vpcs/{vpc}/nat-gateway` `{region, label}` | **201**, `status: pending`, then `active` after 185 s | `w2b-run2/005-N2-*.json`, `w2b-run2/006`-`017`, `w2b-run2/w2b-run.log` |
| `disable_public_ipv4: true` once the NAT gateway is active | **202**. Instance active with `main_ip 10.1.96.3` = `internal_ip` (no public IPv4) | `w2b-run2/018-B2-create-vpc-only-with-natgw.json`, `w2b-run2/B2-fields.json` |
| egress from that VPC-only instance (via a jump host over the VPC) | **open**: `https443 http=200`, egress IP `45.63.22.247` (the NAT gateway's), DNS ok, ICMP ok | `w2b-run2/B2-egress-WITH-natgw.txt` |
| `DELETE /v2/vpcs/{vpc}/nat-gateway/{id}` while the VPC-only instance exists | **422** `Unable to remove NAT Gateway: please remove all VPC-only instances from this network first` | `w2b-run2/025-B3-delete-natgw.json` |

So "VPC-only, then remove the NAT gateway" is refused by the API. A VPC-only
twin always has NAT egress.

### NAT gateway endpoints (live-verified)

| call | result | evidence |
|---|---|---|
| `POST /v2/vpcs/{vpc}/nat-gateway` | 201 `{"nat_gateway": {...}}` | `w2b-run2/005-N2-*.json` |
| `GET /v2/vpcs/{vpc}/nat-gateway` | 200 `{"nat_gateways": [...]}` (singular path, plural key) | `w2b-run2/006-*.json`, `orchestrator-cleanup.md` |
| `GET /v2/vpcs/{vpc}/nat-gateways` | 404 | `orchestrator-cleanup.md` |
| `DELETE /v2/vpcs/{vpc}/nat-gateway/{id}` | 204 (422 while VPC-only instances exist) | `w2b-run2/manual-cleanup/003-delete-nat.json`, `orchestrator-cleanup.md` |
| `GET`/`POST`/`DELETE /v2/nat-gateways[/{id}]` | 404 | `007-cleanup-nat-gateways.json`, `orchestrator-cleanup.md` |

Price: $20/mo (orchestrator-cleanup.md). `scripts/vultr_sweep.py` now
enumerates and deletes NAT gateways per VPC.

## (b) Powered off or network-dead until after the ESP swap

| attempt | API answer | evidence |
|---|---|---|
| create with `"power_on": false` | 202, **silently ignored**: `power_status: running` | `016-C-create-power-on-false.json`, `C-fields-after-create.json` |
| firewall rule `direction: out, action: drop, port: ""` | 400 `Invalid port number` | `007-E2-out-drop-all-port-empty.json` |
| firewall rule `direction: out, action: drop, port: 1-65535` | 201, **stored as `action: accept`** | `008-E2b-out-drop-all-port-range.json`, `E3-rules-after.json` |
| in-VM egress with those out rules | still open (`http=200`) | `E4-egress-after-out-rules.txt`, `E6-egress-after-rule-delete.txt` |
| `POST .../halt` | 204, `power_status: stopped` | `011-D1-halt.json`, `D2-power-after-halt.txt` |
| `POST .../halt` on a just-created (pending) instance | 409 `Unable to stop server: Cannot stop server while it is pending` | `w2b-d2/try1/004-D2-halt.json` |
| `POST .../restore` on the halted instance | 202 `inprogress`; 15 s later still `stopped` (`server_status: locked`) | `013-D3-restore-while-halted.json`, `014-GET-*.json`, `D4-power-after-restore.txt` |
| restore-on-halted tail: does it power on by itself? | **Yes.** `stopped`/`server_status: locked` for 168 s, then `power_status: running`, `server_status: ok` at +183 s, with no start call | `w2b-d2/D2-restore-halted-timeline.txt`, `w2b-d2/w2b-run.log` |

So halting before the restore only delays the boot until the restore
finishes. And even if the instance stayed off, the ESP swap is done by
SSH into the clone's own OS (`docs/real-mode-findings.md`, ESP swap), and
the restored disk boots ahead of the CD. Starting it boots the clone's OS
with its public interface. A powered-off window does not remove the
unsealed boot; it only delays it.

## Leaks during W2 (and fixes)

- NAT gateway `62f6fe13` (early-morning W2b): cleanup used
  `DELETE /v2/nat-gateways/{id}` (404). It was deleted by the orchestrator
  via `/v2/vpcs/{vpc}/nat-gateway/{id}` (`orchestrator-cleanup.md`).
- Instance `fb0dd8a4` (round 1): the only DELETE got 409 `Server is
  currently locked` (`019-cleanup-instances.json`); the cleanup treated the
  409 as done. It was deleted by the orchestrator (`orchestrator-cleanup.md`).
- NAT gateway `f004be28` (round 2): the instance DELETE returned 204 before
  the instance was gone, so the NAT delete got 422 and the cleanup gave up
  (`w2b-run2/028-cleanup-nat-gateways.json`). Deleted about 30 s later
  (`w2b-run2/manual-cleanup/`).
- Fix: `Api.delete_until_gone` (`scripts/bdvultr.py`) retries
  400/409/412/422/5xx until 2xx/404. All drivers and the sweep use it
  (`scripts/test_bdvultr.py`).

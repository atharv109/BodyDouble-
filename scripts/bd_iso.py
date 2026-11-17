"""S2/S3: publish bodydouble-forensics.iso and register it with Vultr.

    uv run --with boto3 python scripts/bd_iso.py --upload
    uv run --with boto3 python scripts/bd_iso.py --register
    uv run --with boto3 python scripts/bd_iso.py --upload --register

gh's fine-grained PAT cannot create GitHub releases (Contents: write missing),
so with the operator's go-ahead the ISO is published on a short-lived Vultr
Object Storage subscription labelled bd-iso-upload instead (TASK.md sanctions
that fallback; scripts/vultr_sweep.py deletes it in S6).

--upload   create/reuse the subscription, upload the ISO, generate presigned
           GET+HEAD URLs (7 days), verify a HEAD -> 200, save the URLs to
           .bd-secrets.env as BD_ISO_URL / BD_ISO_URL_HEAD (never the repo).
--register POST /v2/iso with the URL and poll until status: complete, then
           save the id to .bd-secrets.env as VULTR_ISO_ID (replacing the old one).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, __import__("os").path.dirname(__file__))
from bdvultr import Api, evidence, load_secrets, set_secret  # noqa: E402

ISO = Path(__file__).resolve().parent.parent / "iso/out/bodydouble-forensics.iso"
LABEL, BUCKET, KEY = "bd-iso-upload", "bd-iso-upload", "forensics/bodydouble-forensics.iso"
REGION = "ewr"
PRESIGN_S = 7 * 24 * 3600  # SigV4 max


def get_s3_credentials(api: Api, sub_id: str, host_fallback: str) -> tuple[str, str, str]:
    """(access_key, secret_key, endpoint_host) for the subscription; never logged."""
    sub = api.get(f"/v2/object-storage/{sub_id}")["object_storage"]
    access, secret = sub.get("s3_access_key"), sub.get("s3_secret_key")
    if not (access and secret):
        raise RuntimeError("subscription has no s3 credentials yet")
    return access, secret, sub.get("s3_hostname") or host_fallback


def upload(api: Api, env: dict[str, str]) -> str:  # returns the GET presigned URL
    import boto3  # noqa: PLC0415
    from boto3.s3.transfer import TransferConfig  # noqa: PLC0415

    out = evidence("S2")
    # reuse an existing bd-iso-upload subscription instead of paying twice
    sub = next((s for s in api.list_all("/v2/object-storage", "object_storages")
                if s.get("label") == LABEL and s.get("status") != "deleted"), None)
    if sub is None:
        # the v2 API is cluster+tier based: /v2/object-storage-plans does not exist;
        # Legacy tier has locations [] (undeployable) so pick a tier that serves the cluster
        clusters = [c for c in api.get("/v2/object-storage/clusters")["clusters"]
                    if c["region"] == REGION and c.get("deploy") == "yes"]
        tiers = api.get("/v2/object-storage/tiers")["tiers"]
        picked = min(((c, t) for c in clusters for t in tiers
                      if any(loc.get("id") == c["id"] for loc in t.get("locations") or [])),
                     key=lambda ct: (ct[1].get("price", 1e9), ct[0]["id"]))
        cluster, tier = picked
        status, d = api.call("POST", "/v2/object-storage",
                             {"cluster_id": cluster["id"], "tier_id": tier["id"], "label": LABEL})
        sub = d["object_storage"]
        print(f"created {LABEL} on {cluster['hostname']} tier {tier['slug']} (${tier.get('price')}/mo)")
    sub_id = sub["id"]
    print(f"object-storage {sub_id}: waiting for status active")
    sub, took = api.wait(f"/v2/object-storage/{sub_id}", "object_storage", "status", "active", 900, 10)
    print(f"active after {took:.0f}s")

    access, secret, host = get_s3_credentials(api, sub_id,
                                              f"{sub.get('region', REGION)}1.vultrobjects.com")
    s3 = boto3.client("s3", endpoint_url=f"https://{host}", aws_access_key_id=access,
                      aws_secret_access_key=secret, region_name=REGION)
    try:
        s3.create_bucket(Bucket=BUCKET)
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    size = ISO.stat().st_size
    print(f"uploading {ISO.name} ({size:,} B) to https://{host}/{BUCKET}/{KEY}")
    t0 = time.monotonic()
    s3.upload_file(str(ISO), BUCKET, KEY, Config=TransferConfig(multipart_chunksize=64 * 1024 * 1024))
    print(f"uploaded in {time.monotonic() - t0:.0f}s")
    head = s3.head_object(Bucket=BUCKET, Key=KEY)
    assert head["ContentLength"] == size, (head["ContentLength"], size)

    get_url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": KEY},
                                        ExpiresIn=PRESIGN_S)
    head_url = s3.generate_presigned_url("head_object", Params={"Bucket": BUCKET, "Key": KEY},
                                         ExpiresIn=PRESIGN_S)

    # S2 done-when: curl -I (HEAD) must return 200. Try HEAD first; if the
    # provider mangles presigned HEADs, a GET with -I --range also shows 200.
    # The local network resets TLS mid-handshake often (10054) - retry.
    import httpx  # noqa: PLC0415
    rec: dict | None = None
    for _ in range(4):
        try:
            with httpx.Client(timeout=60) as c:
                r = c.head(head_url)
                ok, how = r.status_code == 200, "HEAD presigned"
                if not ok:
                    r = c.get(get_url, headers={"Range": "bytes=0-1023"})
                    ok, how = r.status_code == 200, "ranged GET standing in for HEAD"
                rec = {"how": how, "status": r.status_code,
                       "content_length": r.headers.get("content-length"),
                       "url_base": f"https://{host}/{BUCKET}/{KEY}", "expires_s": PRESIGN_S,
                       "subscription": sub_id}
                if ok:
                    break
        except httpx.ConnectError:  # TLS reset mid-handshake: retry
            continue
    if rec is None or rec["status"] != 200:
        raise SystemExit(f"URL check failed: {rec}")
    (out / "upload.json").write_text(
        __import__("json").dumps(rec, indent=2) + "\n", encoding="utf-8")
    print(f"verify: {rec['status']} via {rec['how']} on {rec['url_base']}")
    set_secret("BD_ISO_URL", get_url)
    set_secret("BD_ISO_URL_HEAD", head_url)
    return get_url


def register(api: Api, env: dict[str, str]) -> None:
    out = evidence("S3")
    url = env["BD_ISO_URL"]
    status, d = api.call("POST", "/v2/iso", {"url": url}, ok=(200, 400))
    if status == 400:
        # already registered from an earlier run? re-point at the same one
        existing = [i for i in api.list_all("/v2/iso", "isos") if i.get("status") != "failed"
                    and (i.get("filename") or "").startswith("bd-")]
        if not existing:
            raise SystemExit(f"Vultr refused the ISO URL: {d}")
        iso_id = existing[0]["id"]
        print(f"reusing registered ISO {iso_id} ({existing[0].get('filename')})")
    else:
        iso_id = d["iso"]["id"]
        print(f"registered ISO {iso_id}; Vultr is downloading it")
    set_secret("VULTR_ISO_ID", iso_id)
    iso, took = api.wait(f"/v2/iso/{iso_id}", "iso", "status", "complete", 3600, 30)
    print(f"ISO status complete after {took:.0f}s (size {iso.get('size')})")
    final = api.get(f"/v2/iso/{iso_id}")
    (out / "result.json").write_text(__import__("json").dumps(final, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--register", action="store_true")
    args = ap.parse_args()
    env = load_secrets()
    api = Api(env["VULTR_API_KEY"])
    if args.upload:
        upload(api, env)
    if args.register:
        if not env.get("BD_ISO_URL") and not args.upload:
            raise SystemExit("no BD_ISO_URL in secrets; run --upload first")
        register(api, env)
    if not (args.upload or args.register):
        ap.error("nothing to do: pass --upload and/or --register")
    return 0


if __name__ == "__main__":
    sys.exit(main())

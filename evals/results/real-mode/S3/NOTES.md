# S3 evidence: ISO registered with Vultr (integrity match: True)

- `scripts/bd_iso.py --register` POSTed the presigned Object Storage URL
  (BD_ISO_URL from .bd-secrets.env) to `POST /v2/iso`; Vultr downloaded the
  393,216,000 B ISO and reported `status: complete` after 61 s
  (result.json). The new id 7c91b469-f503-4fb7-9518-cedb2c71ede0 replaced the
  dead old one in .bd-secrets.env as VULTR_ISO_ID (done via set_secret).
- Integrity: Vultr's server-side computed md5sum (8ed1b4f55442585427c401c26e1d8151)
  equals the md5 of the local iso/out/bodydouble-forensics.iso - bit-clean transfer.
- The registration is $0/hr (ISOs cost nothing until attached), so the sweep's
  default keep of VULTR_ISO_ID is free; the Object Storage publisher supporting
  it is deleted by the S6 sweep.

# Complete encrypted recovery

The application now keeps a durable `execution_catalog` in the application database. Every new project/user writer registers its canonical SQLite journal **before** financial dispatch; the configured legacy testnet writer/workbench is registered too. Network, main account, API signer, role and absolute source path are bound. A wallet/network cannot silently move to a second journal or overlap another registered trading identity. Explicit migration requires reconciliation; creating a fresh file does not reset nonce/history authority.

`discover_sources` includes the paper database, every catalogued execution database, configured legacy/project journals, derived user journals for earlier local versions and the independent treasury book. Missing mandatory journals or changed catalog/account identity fail the whole inventory. The existing snapshot format now accepts bounded hashed execution roles (at most 128 databases). User/financial proofs, consumed commands, signatures, token lots, strategy-author settlement/payment records and treasury reservations are preserved in their actual databases; private key/environment files are never archive inputs.

## Local encryption and restore

`scripts/ops-config.py` creates ignored `.env.ops` with an independent random 256-bit backup key, without printing it or enabling storage. Existing files are preserved. Keep an independently protected recovery copy: losing this key makes the encrypted backups unrecoverable. It is not included inside the backup it decrypts.

```powershell
node scripts/python.mjs scripts/ops-config.py
node scripts/python.mjs scripts/offsite-backup.py --snapshot --output artifacts/recovery-new.ldb
node scripts/python.mjs scripts/offsite-backup.py --open artifacts/recovery-new.ldb --destination artifacts/decoded-new
node scripts/python.mjs scripts/backup.py --restore artifacts/decoded-new/manifest.json --destination artifacts/restore-new
```

The envelope uses AES-256-GCM with a fresh 96-bit nonce and authenticated version/key identifier. It authenticates before creating restore paths. Only exact manifest-listed SQLite files are admitted; duplicate entries, path traversal, compressed archives, oversized content and altered hashes are refused. Maximum bundle size is 256 MiB; this is an explicit MVP recovery bound, not a hidden truncation. Existing output files/directories are never overwritten. `.ldb` files, environment secrets, databases and artifacts are excluded from source packaging and Docker build contexts.

Snapshots are verified per database, **not an atomic point-in-time snapshot across databases**. Pause entry admission and reconcile all journals/external state before resuming from recovery. Decoding/restoring always targets a new isolated directory; it does not replace live files or activate signers. Catalog paths remain historical source bindings. A restored copy must be mapped/migrated deliberately after exchange reconciliation, not pointed at a live signer automatically. An old snapshot cannot prove that no transaction occurred after it was taken.

## Actual S3 transport code

Set the private `OPS_S3_BUCKET`/region and dedicated scoped AWS credentials in `.env.ops`, or explicitly select an instance role. Default storage is disabled. The official pinned Boto3 SDK handles AWS endpoint resolution, verified TLS and request signing; arbitrary remote URLs/public ACLs are not supported. The bucket should have public access blocked, encryption, versioning/retention appropriate to the owner and least-privilege Get/Put access restricted to the configured prefix. Provisioning these policies is an external owner action; no bucket was created.

```powershell
node scripts/python.mjs scripts/offsite-backup.py --upload artifacts/recovery-new.ldb --arm
node scripts/python.mjs scripts/offsite-backup.py --fetch OBJECT_KEY --output artifacts/downloaded-new.ldb
```

Upload requires explicit offsite enablement/arming, authenticates the envelope, sends only ciphertext and adds server-side AES256 storage encryption. Object names use the encrypted payload's SHA-256. Conditional `If-None-Match: *` refuses overwrite; an existing object is accepted only after reading and comparing the same encrypted bytes. A transport timeout does not claim upload success. Retry the **same encrypted file**, not a newly encrypted payload, when reconciling that object. Remote reads verify size, object hash and the authentication tag before local restore. SDK retries are bounded to one attempt; a separately scheduled owner monitor can decide subsequent attempts.

## Evidence

Thirteen focused cases cover catalog completeness/canonical-wallet refusal, encrypted multi-database restore, incorrect keys/header/tag/ciphertext, path traversal, missing journals, conditional S3 write/read/retry and preservation of an uncertain exchange entry/nonce without replay. Forty-nine combined recovery/project/user/workbench cases pass. S3 calls use the official SDK with Stubber; no actual upload occurred.

A real local encrypted snapshot of the existing labelled demo and independent empty treasury was created, authenticated, decoded and restored into an isolated directory on 2026-10-17 (two databases, 825,291 encrypted bytes). Live databases were preserved and uploads remained false. The local key and recovery files are ignored. This proves the local path; off-machine AWS permissions/retention, real network delivery and disaster recovery on another host remain unobserved.

The Python lock now has 64 exact versions, including `boto3==1.43.114` and its pinned transitive additions. All installed versions match, `pip check` succeeds, and the strict 2026-10-17 PyPI advisory lookup audited all 64 with zero skips and zero known vulnerabilities. This does not replace independent review or image provenance checks.

References: [AWS Boto3 S3 examples](https://docs.aws.amazon.com/code-library/latest/ug/python_3_s3_code_examples.html), [existing SQLite backup mechanics](BACKUP-RESTORE.md), [public server preparation](PUBLIC-DEPLOYMENT.md).

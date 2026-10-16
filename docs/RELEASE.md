# Local release and production handoff

Current supported release: **one local paper service**, one worker per file-backed SQLite database, API bound to `127.0.0.1:8000`, web at `http://127.0.0.1:3000`. User authentication is bound to that exact origin. The release configuration is a packaging contract, not a replacement for runtime settings. Never expose the existing service with a tunnel or change the bind address to make it public.

Jurisdiction, domain, hosting and token role stay `null` at the owner's request. Tentative US interest does not establish an eligible audience or a legal operating entity. Token issuance, staking, revenue sharing, user custody and marketing claims have no approved specification. No access rule or legal conclusion is inferred from a blank field.

## Repeatable source package

After tests/build and a local substage commit:

```powershell
node scripts/python.mjs scripts/release-bundle.py --output artifacts/releases/local-candidate
```

The packager requires a clean `codex/` branch, rejects tracked environment/runtime/key paths, writes a **new** directory and hashes the committed source ZIP and dependency locks. It excludes ignored runtime files because it archives Git's committed tree. It does not certify source contents, dependency provenance or review quality. Do not force-add secrets to Git; filename checks are an additional boundary only. Nothing is pushed or deployed. The ZIP requires installation and building in the target environment; it is not an executable container image.

Reproduce locally using the exact source revision, `npm ci`, the Python lock and editable API install with `--no-deps`, then run API/web tests, typecheck and web production build as described in `README.md`. Run one loopback API process and one loopback frontend process. Keep credentials outside the package and avoid concurrent workers over a restored database.

Rollback is an owner-controlled source revision plus an **isolated** verified snapshot drill. Preserve the current databases and unknown exchange commands. Do not overwrite a newer execution journal with an older backup or reset nonces to resume trading. Revoked sessions remain invalid after process restart; financial permissions require independent exchange readback/reconciliation.

## Monitoring and backup interfaces

`scripts/check-health.py --json` emits one JSON observation for an owner-run collector, using exit codes 0 (local service ready/no critical alert), 1 (blocked/critical), 2 (unavailable/malformed). It sends no notification and schedules nothing. The collector must treat missing observations as unavailable and test an actual delivery plus recovery event. A healthy paper service never means exchange protection, production eligibility or token readiness.

`scripts/backup.py` produces a verified local SQLite snapshot and manifest; see `BACKUP-RESTORE.md`. An external backup integration should upload only the closed snapshot directory and manifest through a separately configured encrypted/authenticated provider, record object identity/version/checksum/time, retrieve it to a new machine/directory, run manifest verification and perform the isolated restore drill. Secrets need a separate access-controlled recovery mechanism. A provider upload acknowledgment alone is insufficient. No provider, credentials, upload or off-machine restore has been configured/performed here.

## Independent review package

Give the reviewer the exact revision/source-manifest hash, dependency locks/audit, `ARCHITECTURE.md`, `SECURITY-REVIEW.md`, `USER-EXECUTION.md`, `USER-CAPITAL.md`, `USER-ACCEPTANCE.md`, API routes, test results and private sanitized acceptance/restore evidence. Review signature domains and expiry, access scopes, nonce ownership, proposal/fill attribution, cash-flow accounting, partial-fill protection, emergency recovery, model budgets, arbitrary input, logging and wallet privacy. The internal review is not independent approval.

| External production gate | Current status / evidence required |
| --- | --- |
| User execution integration | Partial local contracts/hooks; no end-to-end user signer/runner or enabled financial endpoint. Complete integration and actual testnet acceptance first. |
| Independent security review | Not performed; record reviewer identity, revision, findings, fixes and follow-up verification. |
| Public identity boundary | Not implemented; design supported domain/TLS, wallet origin, user/operator roles, authenticated mutation access, abuse/cost limits and privacy policy before exposing anything. |
| Leadership and persistence | Local OS lock only. Distributed worker/signer leadership, nonce isolation, database migrations and restore semantics need implementation/review if more than one host is selected. |
| Alert delivery | Stdout interface only; actual external delivery, escalation and missed-heartbeat detection untested. |
| Off-machine recovery | Local snapshots/drills only; encrypted transfer, access controls, independent retrieval and recovery time/data-loss objectives unset. |
| Hosting and credentials | Unselected; no provisioning, secret manager, public binding or deployment performed. |
| Jurisdiction and audience | Unspecified; current platform terms, geographic access, counsel review and user disclosures required. |
| Financial activation | No mainnet implementation/activation; funded testnet and owner-approved budget/runbook required. |

No document, owner checkbox or manifest boolean changes these gates or enables execution. Additional implementation depends on the selected production topology and legal/product decisions. The controlled pilot plan in `PILOT.md` remains disabled.

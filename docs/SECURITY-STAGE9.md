# Stage 9 security review

Security decision: **Do not launch yet** for real-money public operation.
Risk level: **High** until external financial/runtime acceptance is completed. Local paper operation is separately verified.

## Threat model

FastAPI/Next.js receive untrusted pitches, browser wallet data and public exchange/provider responses. Valuable assets are trading authority, owner-scoped financial signatures, treasury funds and the command/nonce history needed to recover safely. Models and browsers cannot enlarge coded risk/capital/execution permissions. Financial writers are separate opt-in owner processes; public APIs never load user API-key maps or Solana/Ethereum treasury keys.

## Confirmed findings and fixes

- **[High, OWASP A04] Incomplete financial recovery inventory — fixed in code.** The former `scripts/backup.py` selected only paper, configured legacy testnet and treasury. New project/user journals could be omitted. `ops/catalog.py`, `ops/inventory.py` and the updated snapshot tooling now register/discover every new writer's canonical journal, reject missing files, preserve uncertain commands/nonces and authenticate encrypted restore inputs. A different journal cannot silently reuse a registered wallet/network.
- **[Medium, OWASP A05] Loopback-only identity configuration could not support public hosting — addressed for one host.** The old auth origin/host boundary was fixed to loopback, and generic forwarded headers were unsuitable as trusted rate-limit identity. Public mode now requires exact HTTPS origin, distinct strong proxy/operator secrets and an authenticated overwritten client-IP header. Direct API bypass/foreign origins and excess active application connections are refused. This is not distributed scaling.
- **[Medium, OWASP A09] No external operational alert delivery — implemented, externally unverified.** Readiness previously stayed local. Durable redacted webhook delivery, financial uncertainty observation and runner heartbeats now exist. Actual receiver/host-outage acceptance remains open.

## Review coverage and practical checks

Owner/tenant separation, absent authentication, alternate owner IDs, proof/command replay, wrong signature domains, changed fees/quantities/limits, source/network mismatch, malformed money, partial fills, nonce persistence, HTTP body/origin/host boundaries, redirects and notification payload redaction are covered by local tests. The latest complete local run passes 511 Python/69 client cases plus the production build. Source review found no use of `dangerouslySetInnerHTML`, browser storage for wallet sessions, dynamic eval or untrusted shell execution in application code in this pass. Provider-supplied strings are rendered as React text; wallet icons are not injected as raw SVG. There is no public file-upload route. Donation webhooks cannot certify settlement; donation records are polled through authenticated provider API.

Keys/configuration/databases/encrypted backups are excluded from source packaging and Docker context. The generated `.env.server` and `.env.ops` stay ignored, and their secrets were not printed. The 64-entry pinned Python dependency set matches installed metadata; strict advisory lookup found no known vulnerabilities/skips on 2026-10-17. Prior npm production advisory results and independent supply-chain/image review remain separately scoped; a clean lookup does not certify dependency safety.

## Remaining launch gates / fix order

1. The separate user mainnet boundary is now implemented and locally tested. Keep all financial execution disabled until real owner-reviewed wallet/API-wallet/builder-fee/fill/protection/revocation/recovery evidence exists. Actual Solana mint, treasury funding and The Giving Block credentials/provider acceptance are missing.
2. Build/run/scan the server images on a working Docker host, validate Caddy/HTTPS/proxy isolation and least-privilege cloud credentials, then perform a real off-machine restore/delivery drill. Docker CLI parses Compose, but this workstation's Linux daemon is unavailable; no containers/server were deployed.
3. Obtain independent security review, resolve material findings and establish operational ownership, backup-key custody, host outage monitoring and explicit financial budgets. This is a developer self-review, not independent approval. Multi-host leadership/session/rate-limit operation is unsupported; the prepared release is constrained to one host/worker. Cross-network funding is still explicit, not an implemented autonomous bridge.

No third-party systems were attacked, no real financial order/transfer occurred and no jurisdiction or token right was invented. The applied [security-launch-audit skill](C:/Users/User/.codex/skills/security-launch-audit/SKILL.md) requires an evidence-based decision; it does not require pausing authorized code work or asking for deployment approval while implementation remains incomplete.

# Internal local boundary review

Security decision: **Do not launch yet** (public hosting or financial production).
Risk level: **High for an unreviewed public/financial release**. The confirmed local findings below are fixed; production gates remain open. This is an internal code review, not the independent review required by 6.1c.

Date: 2026-10-16. Scope: this repository's FastAPI/Next.js local application, paper broker, testnet adapter, account/consent previews and recovery tools. Only owned local code was tested adversarially. Third-party exchange calls remained ordinary unsigned public-data reads.

## Threat model

- Valuable assets are signing credentials, operator authority, model-call budget, accurate risk/capital state, durable nonces and unambiguous account ownership.
- Model prose, pitch input, wallet/provider metadata, external responses and downloaded previews cannot grant execution permissions. Code controls risk and capital; signer credentials remain in a separate owner process.
- Mainnet order submission, user order submission, fee collection, token transactions, uploads, payment processing and webhooks are not implemented. Public account inspection is intentionally unauthenticated and grants no ownership or mutation authority.
- The current trust boundary is a single-machine loopback application. Public service identity, operational leadership and exchange acceptance are separate work.

## Confirmed findings and fixes

| Severity / mapping | Evidence before fix | Risk and remediation |
| --- | --- | --- |
| Medium / A02:2025 Security Misconfiguration | Tests using a foreign `Host` and foreign/null `Origin` reached the local API with HTTP 200. | Missing local browser/host boundary. Added explicit loopback hosts and exact local origins; foreign Host now returns 400 and foreign Origin 403 before application work. This supplements authentication; it does not replace it. |
| Medium / A02:2025 | A 65,537-byte JSON body reached JSON validation and returned 422. | Request parsing and buffering were not bounded before route validation. Added a 64 KiB limit, streamed-byte counting without Content-Length, malformed-header rejection and a five-second body-read deadline. Oversized requests now return 413 and slow partial bodies 408 before route execution. |
| Medium / A02:2025 | A synthetic invalid token appeared in the rendered settings validation exception. | Misconfigured startup could echo input credentials to logs. All settings classes now hide input values in rendered validation errors; tests cover operator and provider credential markers. No actual credential disclosure was observed during this review. |
| Low / A02:2025 | Account API responses lacked explicit no-store/nosniff headers. | Added `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` to local API responses. |

Classification reference: [OWASP A02:2025](https://top10.owasp.org/2025/A02_2025-Security_Misconfiguration/). Findings are based on the repository behavior, not inferred from this category alone.

## Verification and reviewed surfaces

- 215 Python tests and 11 wallet tests pass. The nine local-boundary tests include chunked bodies, slow reads, duplicate headers, Unicode invalid bearer data, allowed CORS preflight and a valid local POST. Financial/recovery and operator authorization tests pass alongside durable admission and local worker ownership checks.
- Live local checks: Next's proxy returned account state with 200/no-store/nosniff; direct API requests rejected foreign Host/Origin. The browser still loaded public-account data and a cost preview with no console errors. The production build passes.
- Operator mutations require the configured bearer token. Non-ASCII malformed bearer data returns 401 rather than causing a string-comparison exception. Consent previews accept no signature and expose no submission route.
- Account address, network, approval binding, money precision, client request ID and expiry validation are covered. User balances never become shared execution capital. Public watch mode is not reported as authenticated ownership.
- React renders user/external strings as text. No application match was found for `dangerouslySetInnerHTML`, `eval`, pickle deserialization, shell-enabled process execution or public-prefixed secret variables. Wallet-provided image/SVG URLs are not rendered.
- The signer excludes generic transfer/withdraw actions and mainnet writes. Commands are claimed durably and not blindly replayed. Recovery refuses existing destinations and checks snapshot integrity. Tests use explicitly public, unfunded key vectors; no real wallet permission or signed exchange request was used.
- Dependencies are locked. Strict pip-audit 2.10.1 checked all 56 exact Python lock entries without skips; installed versions matched and pip check passed. The Python and npm production advisory checks both reported zero known vulnerabilities. See [DEPENDENCY-AUDIT.md](DEPENDENCY-AUDIT.md) for input hashes, commands and limits. Full source/provenance review and hashed Python installation artifacts remain outside this check.

## Fix order and remaining gates

Subsequent local user work adds EOA sign-in with exact server-generated origin/chain/nonce/message binding, single-use proof consumption, canonical signature recovery, hashed scoped tokens, expiry/revocation and restart invalidation. Private order illustrations derive their address from that session, enforce per-trade controls and retain disabled execution flags. Tokens/signatures/private plans are excluded from public state and event exports. Authentication/ownership tests pass, including concurrent replay and revocation during account lookup. This is not an independent review of the new authentication flow; real wallet-extension behavior and exchange execution remain acceptance gaps.

1. Completed locally: host/origin/body boundaries, error redaction, API headers, existing-authorization regression checks and recovery tooling.
2. Before financial activation: owner-reviewed funded testnet evidence, actual wallet authorization/signing, native protection, approval/revocation and fee/funding receipts. An unsigned preview or mocked exchange is insufficient.
3. Before public hosting: authenticated service/tenant mutations, durable distributed abuse limits, trusted reverse-proxy/TLS configuration, production frontend security policy, worker/signer leadership, migration/backup retention, off-machine recovery, alerting, independent security review and owner decisions on operating scope/jurisdictions.

Coverage gaps: no funded exchange tests, paid model call, real wallet-extension authorization, PostgreSQL recovery, production ingress, penetration test, full Git-history secret scan or independent cryptographic review. Local process access and local backup confidentiality remain the machine owner's responsibility. No public deployment was performed.

Security decision: **Do not launch yet**.

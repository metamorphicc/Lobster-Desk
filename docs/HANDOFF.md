# Delivery handoff — 2026-10-16

All completed local substages are committed on `codex/mvp-foundation`. The remote is `https://github.com/metamorphicc/Lobster-Desk.git`. No push, deployment, real order, transfer or token launch was performed. See `ROADMAP.md` for separate software and external acceptance checkboxes.

## Usable now

Run `npm run dev` and open `http://127.0.0.1:3000`. Stages 0–4 deliver the local paper tank: BTC pitches, analyst/risk/capital decisions, deterministic limits, simulated execution/protection and a public decision/trade journal. Demo model/data sources are labelled. Optional public market data never changes paper execution into real trading.

The Testnet tab supports public wallet/address observation, exact fee illustrations, unsigned permission previews, optional scoped EOA sign-in, private order illustrations and private observed loss references. Signing in grants preview access only. Actual extension financial signing and user execution are not enabled.

The local user execution core binds exact consent, unique API-wallet roles, private user capital and canonical separate journals to the broker. Tests substitute an in-memory exchange. Its writer is locked independently of arming flags; there is no HTTP financial-proof/order route or unlock setting. Unknown prehistory/account modes, incomplete history, revoked approvals, changing costs and expired/changed consent fail closed. Entry-only fee/permission checks do not block risk-reducing reconciliation; user protection/recovery omits builder fees.

## Remaining-stage local deliverables

| Stage | Delivered locally | Still open |
| --- | --- | --- |
| 5.2d.4–5c | Per-user loss references, consent/profile/signature contracts, restricted signing bounds, locked orchestration, fill/fee observations and atomic audit links. | Real financial wallet RPC/runner activation integration, per-user runner leadership and complete journal recovery inventory; funded exchange acceptance. |
| 5.2d.6a | Private acceptance case template and contained evidence-file inventory. | Actual extension prompts, orders, stops, revocation, fee/funding receipts and owner review. |
| 6.1c.6–7 | Clean committed-source ZIP/manifests, local-only configuration, structured healthy/blocked/unavailable monitor output and external-integration/review handoff. | Public identity/security/hosting implementation, selected domain/topology, external monitoring delivery, off-machine recovery and independent security review. |
| 6.2a | Disabled pilot plan and exact budget/loss/recovery rehearsal. | Owner capital/loss/reserve choices, reviewed mainnet implementation, production gates and actual pilot mandate/observations. |
| 7.1a | Independent receipt book, loss carry-forward, capital/revenue separation and provisional reserve/allocation policy. | Jurisdiction, entity, token role/rights/network, reserves, expenses/tax policy and legal/product review. |
| 7.2a | Private spend/purchase/disposal links, exact quantities, duplicate/excess checks and treasury restore coverage. | Real approved transactions, chain-specific receipt authentication/finality, token implementation and reviewed public reporting. |

The owner postponed funded testnet acceptance and left jurisdiction, domain, hosting and token role undecided. These remain blank; no profit-sharing/staking entitlement or US-access eligibility is invented. Main stages 5–7 remain unchecked where external work or a deliberately closed integration is still required.

## Local operator commands

All outputs below are ignored local artifacts. Use a **new** output path for each capture.

```powershell
node scripts/python.mjs scripts/user-acceptance.py template --output artifacts/user-acceptance/record.json
node scripts/python.mjs scripts/user-acceptance.py inventory --record artifacts/user-acceptance/record.json --output artifacts/user-acceptance/inventory.json
node scripts/python.mjs scripts/check-health.py --json
node scripts/python.mjs scripts/pilot-report.py --output artifacts/pilot/report.json
node scripts/python.mjs scripts/treasury-report.py --output artifacts/economics/treasury.json
node scripts/python.mjs scripts/buyback-report.py --output artifacts/economics/buybacks.json
node scripts/python.mjs scripts/release-bundle.py --output artifacts/releases/new-candidate
```

The monitor reads only the local API; stopped services produce an unavailable report/exit 2. Evidence inventory, pilot/economics calculations and source packaging never sign or contact an exchange. Receipt reports are owner-supplied/unverified even when arithmetic passes. A missing token/reserve policy produces no allocation, not a guessed budget.

`scripts/backup.py` captures the local paper database, the configured owner testnet ledger when present, and `data/treasury.sqlite3` when present. It does not enumerate all future user execution journals. Restore only into a new directory and reconcile financial state separately; never reset a live nonce/receipt journal from an old snapshot to resume execution.

## Verification

The final local checks are recorded in `VERIFICATION.md`: **357 Python tests**, **27 Node wallet tests**, TypeScript and the web production build pass. Relevant tests cover exact money, signature domains/replay/clock/expiry, concurrent claims/receipts, strict role/account isolation, guard failure after leverage, actual fixture partial fills and stop recovery, revenue/loss/reserve arithmetic, duplicate purchase/disposal prevention and isolated restore. One upstream Starlette/httpx test-client deprecation warning remains; tests do not require changing the locked runtime to silence it.

A real local paper-plus-empty-treasury snapshot was created and restored into an isolated directory. Default acceptance/pilot/economic reports were generated with unverified/disabled flags. No fabricated production trades or revenue were inserted. Temporary services from earlier browser checks were stopped; no new daemon/automation was installed.

The independent review, deployment, funded testnet/mainnet and token gates are **not** completed by tests, manifests, document checkboxes or owner-supplied receipt hashes. The detailed continuation references are `USER-EXECUTION.md`, `USER-ACCEPTANCE.md`, `RELEASE.md`, `PILOT.md`, `ECONOMICS.md` and `BUYBACK-REPORTING.md`.

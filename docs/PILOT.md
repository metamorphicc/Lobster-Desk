# Controlled pilot preparation

Status: **no mainnet pilot, mainnet broker, deployment or funding**. This stage delivers a non-executing local budget rehearsal. It neither chooses an owner budget nor treats paper PnL as evidence of profitability.

`release/pilot-plan.json` leaves owner capital, absolute loss budget and reserve floor unset. The planning ceilings are BTC only, isolated leverage up to 2x and $10–$50 entries. These inherit a conservative testnet ceiling; they are not a mainnet approval. Daily loss 1%, drawdown 5% and per-trade stop-risk 0.25% remain limits, not promises that gap losses cannot exceed them.

```powershell
node scripts/python.mjs scripts/pilot-report.py --output artifacts/pilot/unconfigured.json
```

Optional `--observation` accepts exact decimal strings and explicit provenance (`offline_fixture` or `owner_supplied_unverified`). Money supplied by an owner is still not an authenticated exchange receipt. Empty observations produce `measures=null`, not invented zero profits/volume/retention. Report hashes bind plan and observations; no result sets execution permission true.

The rehearsal subtracts net external capital flows from equity to compare performance with initial/day/high-water references. Deposits cannot dilute the loss basis, which uses the smaller of initial/current equity. Funding belongs in equity once; it is not added again. The result is **not realized PnL**. Incomplete/stale history, unidentified exposure, unknown commands, unconfirmed protection of an open position or a latched halt prevent a passing rehearsal. Changing a plan cannot erase losses or reset a live execution ledger.

Before any actual pilot, finish Stage 5 integration and real testnet acceptance, resolve every external gate in `RELEASE.md`, select a reviewed mainnet implementation, obtain an explicit owner capital allocation and define a dated/revision-bound pilot mandate. Record the exact account/agent, start/end, total loss budget, reserves, maximum trade size, allowed markets, operator coverage and stop/recovery responsibilities. A file boolean cannot authorize that work.

During an eventual pilot, preserve all proposal/review/consent/nonce/order/fill/funding/cashflow links. Separately report user fill fees, builder fees received, project trading realized PnL, funding, operating costs and external deposits. Track actual organic user volume and repeat use with defined denominators and privacy controls; do not infer either from demo sessions or wash activity. Stop new entries on breached budgets or missing observations; preserve risk-reducing reconciliation. API-wallet revocation is not a substitute for confirming exposure is flat.

Advancement criteria need owner approval before the pilot: complete accounting, no unresolved critical findings/commands, verified protection/recovery, actual net economics after expenses and a representative observation period. No duration, return target, revenue promise or token entitlement is invented here. Retrospective reports must label sample size, data gaps and whether receipts were independently checked.

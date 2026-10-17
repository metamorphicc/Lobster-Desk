# Buyback and disposal reporting

Status of this legacy report: **local receipt accounting only**. The owner subsequently selected Solana; the separate executable purchase/burn flow is described in `SOLANA-TREASURY.md`. No mint is configured and no actual swap/burn has occurred. This report continues to represent owner-supplied observations rather than the new runner's RPC evidence.

The book links three separate facts:

1. A recorded USDC `buyback_spend` in the treasury book.
2. An owner-supplied purchase observation, matching that exact spending receipt and cost, with a network/asset identifier, settlement event reference, exact atomic token quantity, decimals and evidence hash.
3. Optional disposal observations attributed to the purchased lot, each with a unique event reference and matching asset/network.

Each spending receipt funds one recorded purchase. Duplicate identities are idempotent only when the complete input matches; conflicting reuse is refused atomically. Cumulative disposals cannot exceed a purchased lot. Purchase observations do **not** debit USDC again. Token amounts are integer strings and decimals stay attached to each lot, so different assets/precisions are never silently added together.

`supply_reduction` observations require exact before/after supply arithmetic matching the claimed quantity. `sink_transfer` is reported separately and never called a supply reduction. Purchased-but-undisposed tokens remain unallocated. Buying is not burning, and an arbitrary dead-looking address is not proof of irrevocable destruction. Token-specific semantics, event authenticity, chain finality/reorg handling, custody attribution and circulating supply cannot be verified before the chain/contract/specification exists. One disposal observation must consume a distinct part of the purchased lot; do not describe the same tokens first as a sink transfer and again as a separate burn.

```powershell
node scripts/python.mjs scripts/buyback-report.py --output artifacts/economics/buybacks.json
```

Optional `--purchase` and `--disposal` take private JSON matching `Purchase` / `BurnObservation`. Append the matching USDC spend through `treasury-report.py` first. Event references must identify a unique chain/account transaction and event/log; a bare transaction hash is insufficient when multiple events share it. Evidence files remain private, their hashes are supplied by the owner, and the tool does not fetch or authenticate them. Retry identical inputs after a partial reporting failure; no duplicate spending is created. Existing output files are never overwritten.

Every report keeps `receipts_authenticated=false`, `burns_verified=false`, `transfers_authorized=false` and `token_contract_selected=false`. Report hashes detect accidental changes; they are not exchange/on-chain signatures. Even arithmetically consistent owner observations are not independently verified public receipts. Missing purchase links are explicitly listed. Do not advertise these reports as actual buybacks/burns until external evidence is independently checked against the eventual approved specification.

The treasury book now participates in local snapshots/restore drills, including purchase/disposal tables. `scripts/backup.py` includes `data/treasury.sqlite3` when present; select another path with `--treasury-book`. A restored book preserves duplicate protection and linkage, but does not establish chain finality or authorize new treasury transactions. Off-machine recovery remains unverified.

Public reporting, when approved, needs a reviewed sanitized publication artifact plus authenticated explorer/RPC receipts, policy/revision, exact treasury spend, obtained asset/amount, attributable supply change, expenses and remaining allocation. Contract/token implementation and automatic execution remain deferred until the owner defines token role and rights.

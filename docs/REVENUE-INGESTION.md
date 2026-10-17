# Received revenue reconciliation

`RevenueImporter` reads only the fixed Hyperliquid mainnet `/info` host. It imports actual `rewardsClaim` ledger updates, never estimated fees, unclaimed balances or paper profit. Hyperliquid combines builder and referral claims: automatic attribution requires an explicitly empty referral list on a dedicated builder account. Historical account use still needs owner reconciliation. `builderRewards` is recorded without assuming it is a lifetime counter; imported claims cannot exceed the observed `claimedRewards` aggregate.

Run from the repository root after selecting an exact historical window (milliseconds, at most seven days):

```powershell
node scripts/python.mjs scripts/import-builder-revenue.py --builder YOUR_BUILDER_ADDRESS --start-ms START --end-ms END
```

This is a read-only exchange request and a local book write. It does not claim rewards or transfer money. Inclusive pagination, duplicate/conflicting hashes, late observations, cursor gaps and malformed USDC values fail closed. Receipts and the ingestion cursor commit in one SQLite transaction. Repeat with an overlapping window; do not skip intervals. The first interval is an explicit baseline, not a reconstruction of lifetime revenue.

For project trading settlements, optionally set `PROJECT_TREASURY_PATH` to the same `TREASURY_PATH` used by the API. The separate mainnet project runner attempts settlement after each tick. It requires a flat account, terminal owned trades, complete cash-flow/funding history and agreement between actual owned fill PnL minus fees plus signed funding and cash-flow-neutral account performance (one micro-USDC observation tolerance; the booked value itself must have exact USDC precision). Builder fees already included in a fill's fee are not deducted twice. Foreign activity or incomplete history blocks settlement. Testnet and paper settlements are refused. Losses require sufficient recorded principal/cash, so missing capital receipts must be reconciled first.

Each flat checkpoint books only the increment from the previous cumulative settlement. A deposit, withdrawal, restart or repeated report does not manufacture profit. These are aggregate project-account settlements; they do not claim exact per-partial-fill funding allocation.

The legacy receipt provenance remains `owner_supplied_unverified`: fixed-host exchange observations are not cryptographic chain proofs, and a local administrator can rewrite the database. The public report does not certify production metrics or finality. Global recorded cash is not a claim of spendable Solana USDC: cross-network funding must be reconciled separately before any Solana operation.

Verified offline: 36 focused revenue/book/distribution cases, including atomic rollback, restart idempotency, changed history, malformed amounts, referral ambiguity, fee/funding inclusion and rejection of unrealized/testnet profit. No real builder account or transaction was used.

Sources: [Hyperliquid info schemas](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [ledger event schemas](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/nodes/l1-data-schemas).

## Continuous observation

Copy `.env.revenue.example` to ignored `.env.revenue`; set the dedicated public builder address, an exact `REVENUE_BASELINE_MS` and the same treasury book path used by the API/financial runners. `npm run revenue` only inspects configuration. `REVENUE_ENABLED=true` and `npm run revenue -- --run` start fixed-host read-only observation, with a single local process lease and default 30-second polling. `--once` performs one bounded cycle and returns nonzero if reconciliation fails. No wallet or model key is used.

The first historical timestamp is explicit; the observer never guesses lifetime revenue or silently skips a prior manual-import cursor. The builder/baseline binding is immutable. Each cycle overlaps its prior cursor, covers at most seven days, and atomically advances only after complete receipt validation. Long downtime catches up in successive bounded cycles. A 60-second observation delay reduces indexing races; it is not a finality proof. A late conflicting receipt stops accounting for owner reconciliation rather than adding income twice. The existing actual receipt book directly drives the 40/20/40 earmarks.

`GET /api/v1/economics` includes redacted observer status/last success; Treasury displays it. The operations monitor emits a static warning on failed/stale active observation. Graceful stop marks the observer stopped; a crash leaves its active observation available for stale detection. The receipt DB is already in encrypted recovery inventory. Twelve new focused tests cover restart, exact allocation/deduplication, failed observation/cursor preservation, monitor redaction, bounded catchup, baseline immutability/clock rollback, refusal to skip manual history and exact environment timestamps. No real builder account was used.

This observer cannot claim unreceived rewards or transfer capital. Automatic Hyperliquid reward claiming, allocation transfers and Hyperliquid-to-Solana/Ethereum funding are not implemented; the bounded financial runners currently require prefunded destination wallets. Those principal movements must be reconciled without becoming new earnings. Do not describe the complete financial product as model-API-key-only activation.

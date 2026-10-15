# Funded testnet acceptance

Status: **not performed**. Offline fixtures and read-only captures do not complete this gate.

Run this procedure as the account owner after reviewing `TESTNET.md`. Use a dedicated testnet account, an approved API wallet and the smallest permitted BTC notional within the $50 configured cap. Do not use mainnet capital. No development command automatically funds an account or runs these scenarios.

## Evidence capture

```powershell
node scripts/python.mjs scripts/testnet-evidence.py
```

This command reads testnet `/info` observations and writes a new JSON file under ignored `artifacts/`. Use `--output` for a different local path; existing files are never overwritten. It never loads the signer environment, reconciles a trade or submits an exchange command. Configured public addresses allow account queries. Without them it captures anonymous connectivity and marks account checks incomplete.

Order identities are checked again against the exchange before including associated BTC fills. At most 100 local order references and the latest 2,000 account fills are queried. Captures omit pitch text, keys and signatures. Observations are sequential rather than an atomic exchange snapshot. Preserve the local ledger, runner logs and exchange receipts alongside captures; do not publish private environment files.

Every report leaves `funded_acceptance_verified=false`. Its hash detects accidental changes but does not authenticate an exchange receipt or prove historical protection. A reviewer must evaluate each case below and record pass/fail, timestamps, intent IDs, exchange order IDs and supporting files in an owner-controlled acceptance record.

## Required cases

| Case | Owner action | Required observation |
| --- | --- | --- |
| Identity and permissions | Inspect the dedicated owner account and API wallet before enabling the signer. | Public addresses match; API wallet approval is valid; signing with the owner key is refused. |
| Entry | Stage an unexpired approved testnet setup, then invoke the separate owner runner once. | Actual BTC fill belongs to the recorded client/order ID; size, limit, leverage and account match approval. |
| Partial execution | In a controlled testnet session, obtain an actual partial IOC fill. Do not represent an offline fixture as this case. | Protection quantity follows actual filled exposure, never the larger requested entry. |
| Native stop | Observe the owned stop in exchange orders, then observe its actual trigger/execution. | Reduce-only direction/quantity/trigger match; fills reconcile to flat; remaining owned target is removed. |
| Restart | Stop and restart the runner with `--reconcile` while retaining the same ledger. | The entry is not submitted again; nonce state persists; ownership and protection are re-established from exchange observations. |
| Timeout | Interrupt the runner/network around a controlled request and restore observation access. | An uncertain command is reconciled by client order ID. No automatic entry replay occurs. |
| Cleanup and isolation | Reconcile a completed trade; check that no unrelated order was cancelled. | Flat owned exposure, matched entry/exit fills, no owned leftover protection. Unidentified exposure blocks modification. |
| Fees and funding | Compare exchange fills, actual fee denomination and funding history with the account ledger. | Fill fee and closed PnL totals match. Funding and external capital flows are separately accounted for; current software totals exclude funding. |
| Failure handling | Review protection-failure behavior and recovery against the testnet account. | Failed stop confirmation triggers a latched halt and bounded reduce-only recovery; owner verifies residual exposure. |

## Exit criteria

Do not mark 5.1d complete until these cases have real exchange evidence and an owner-reviewed record. Unavailable partial-fill scenarios, truncated fill history, unresolved commands or missing funding reconciliation keep acceptance open. Production activation, public hosting, user fee collection and token operations have additional independent gates.

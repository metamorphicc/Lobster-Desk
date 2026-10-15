# Testnet execution boundary

The execution package is an independently journaled **testnet-only** adapter. The main tank remains paper by default. No mainnet write host or transfer/withdrawal action is implemented.

## Authority

A setup must carry both reviewer approvals, a current coded risk/capital approval, its policy version, expiry and a matching approval hash. Only BTC setups evaluated against testnet market data are eligible. A dedicated account must be flat and have no outstanding orders before entry. The order is resized against actual testnet account capital, BTC precision, the worst permitted IOC price, the reviewed maximum quantity and the signer's absolute entry cap (default $50).

The signer uses the official `hyperliquid-python-sdk` signing implementation with the testnet domain, no vault address and no builder fee. Its public operations are BTC orders, isolated leverage up to 2x, and cancellations by client order ID. A main account's own private key is refused; use a separately approved API wallet. Signatures expire after five seconds at most, and entries cannot outlive their proposal approval.

## Persistence and recovery

The testnet database binds permanently to one account/API-wallet identity. A new key or account requires a new ledger. Never reuse this API wallet in another application or with another nonce database.

Commands are stored and atomically claimed before signing or sending. Nonces are allocated in the same transaction and survive restarts. Any claimed command is treated as possibly submitted: a crash or HTTP timeout never causes automatic replay of the entry. `unknownOid` is not proof that an order failed. An unresolved intent holds the execution slot and requires reconciliation or owner investigation.

An unconfirmed leverage update prevents entry. At this stage an ambiguous leverage acknowledgement remains blocked for owner review; the adapter does not silently repeat it.

## Protection and execution facts

Entry is an IOC order with a bounded execution price. Partial execution is protected at the observed position size rather than the requested size. The broker checks owned order IDs, account direction, position size, leverage and exchange fills.

A stop is considered confirmed only when `frontendOpenOrders` reports the matching BTC client order ID, side, reduce-only flag, trigger and actual quantity. A successful POST alone is insufficient. If the stop cannot be confirmed, the armed broker attempts a reduce-only emergency exit and latches a halt. This conservative behavior may close a position during API propagation delays; test it explicitly before any pilot.

When a position shrinks, replacement protection is installed before older owned orders are cancelled. Flat position plus reconciled owned entry/exit fills is required for closure. Remaining owned protection must be cleaned up before the execution slot is released. Unknown exits are not blindly resubmitted; residual-size exits have a bounded attempt count.

Native trigger orders still have execution price limits. A gap, liquidity failure or unavailable API can prevent execution at the desired price. No component promises a guaranteed maximum realized loss.

## Current verification limits

Offline tests exercise signatures, persisted command ownership and an in-memory exchange's partial-fill/failure scenarios. Fixed-host HTTP behavior is tested with `httpx.MockTransport`. These are not observed exchange trades.

Funded testnet acceptance remains mandatory: dedicated API-wallet approval, actual fills, partial fills, native stops, cancellation, fee/funding accounting and restart reconciliation. The initial adapter reads the latest 2,000 fills; missing historical fills keep reconciliation incomplete rather than inventing PnL. Fill fees/closed PnL are observations, not a complete account-return calculation including funding. Keep the dedicated account free of external transfers and manual trading; capital-flow-adjusted performance accounting remains a production gate.

## Local workbench

`npm run dev` starts the paper tank and the Testnet tab. It never starts a signer. The HTTP service reads public settings from `.env`; it does not instantiate `SignerSettings` or read `.env.testnet-signer`.

Without credentials, **Check readiness** reads BTC testnet metadata and prices. Unknown funding and missing account approval remain visibly incomplete. This CLI does the same read-only inspection:

```powershell
node scripts/python.mjs scripts/testnet-runner.py
```

For an owner-managed testnet experiment, configure these public values in the root `.env`:

```dotenv
MARKET_SOURCE=hyperliquid-testnet
DATABASE_URL=sqlite:///data/testnet-paper.db
HL_TESTNET_DATABASE_URL=sqlite:///data/testnet.db
HL_TESTNET_MAX_ENTRY_NOTIONAL=50
# Supply your own public addresses, without quotes or placeholder angle brackets:
# HL_TESTNET_ACCOUNT_ADDRESS=...
# HL_TESTNET_API_WALLET_ADDRESS=...
# OPERATOR_TOKEN=... (at least 24 characters)
```

Use a dedicated, funded testnet owner account and a separately approved API wallet. Restart the API after changing configuration. The two databases must be separate, including their resolved SQLite file paths. Changing an identity requires a new execution ledger.

Pitch a BTC setup in the tank. After both reviews and coded capital approval, select it in **Testnet**, preview its actual account-based size, enter the local operator token and choose **Stage intent locally**. An approved paper entry may already have simulated a fill; its bound, unexpired testnet-data review can still authorize a separately staged testnet intent. Closed, rejected, expired, altered, demo-data and mainnet-data reviews cannot. A paper fill never automatically submits an exchange order.

Staging only writes the separate execution journal. It repeats fresh account, wallet approval, market and risk checks; it creates no signature or exchange command. Repeated staging of an unchanged unsent intent is idempotent. **Cancel local intent** uses the same operator token and is allowed only before any command has been prepared. Cancellation and command preparation serialize in the ledger transaction. Cancelled or otherwise terminal intents cannot open another entry; submit a new reviewed pitch instead.

There is no HTTP dispatch endpoint, and no private-key field in the UI. The workbench polls the local journal, including actual observed fills from the separate runner. Readiness does not certify funded acceptance.

## Separate owner signer

This is an explicit exchange-write step for the owner after reviewing the implementation and testnet acceptance procedure. It is never executed as part of automated development checks.

Copy `.env.testnet-signer.example` to `.env.testnet-signer` locally. Set `HL_SIGNER_PRIVATE_KEY` to the dedicated testnet API wallet key and `HL_SIGNER_ENABLED=true` only when ready to submit. Never use an owner account private key, put keys into a pitch, or share them in chat. The configured public API-wallet address must match the private key. The file is ignored by Git.

Submit a staged intent once and continue reconciliation:

```powershell
node scripts/python.mjs scripts/testnet-runner.py --dispatch --trade YOUR_INTENT_ID --watch
```

After a restart, resume reconciliation rather than blindly opening another trade:

```powershell
node scripts/python.mjs scripts/testnet-runner.py --reconcile --trade YOUR_INTENT_ID --watch
```

`--reconcile` can install protective orders, cancel owned leftovers or attempt a reduce-only emergency exit. It is not a read-only command. Only the invocation without either action flag is read-only. A local OS file lease prevents concurrent owner runners using the same ledger file; it is not distributed leader election. Use one machine and one runner for this API wallet. Multi-host/PostgreSQL signing remains an unverified operational configuration.

Ctrl+C stops the monitor, not the exchange position. Check the exchange account and native protective orders before leaving it unattended. Removing credentials does not close positions. This initial runner has no halt-reset command: investigate a latched halt and reconcile the account before creating another experiment.

## Sources

For read-only evidence capture and the mandatory funded scenarios, see [TESTNET-ACCEPTANCE.md](TESTNET-ACCEPTANCE.md). Tooling preparation does not complete funded acceptance.

- [Exchange orders and client order IDs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint)
- [API wallets and nonce ownership](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets)
- [Order/fill queries](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Official SDK](https://github.com/hyperliquid-dex/hyperliquid-python-sdk)


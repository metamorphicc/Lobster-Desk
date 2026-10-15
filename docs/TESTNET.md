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

## Sources

- [Exchange orders and client order IDs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint)
- [API wallets and nonce ownership](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets)
- [Order/fill queries](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Official SDK](https://github.com/hyperliquid-dex/hyperliquid-python-sdk)


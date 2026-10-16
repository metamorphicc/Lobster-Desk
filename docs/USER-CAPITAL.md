# Private user capital observations

`GET /api/v1/users/testnet/capital` and `POST /api/v1/users/testnet/capital/refresh` require a local wallet session; the account is derived from its recovered address. References, receipts and observations remain private tables in the paper SQLite database, outside the public journal. No endpoint accepts client-supplied balances, receipts, risk references or reset authority.

First refresh starts a reference only for a flat account with positive equity and an exact fresh exchange timestamp. Earlier history remains unknown. The daily reference starts at the first observation within its UTC date, **not a reconstructed midnight balance**. Neither references nor a green monitoring state grant entry permission.

Subsequent refreshes read the fixed testnet non-funding ledger and BTC funding history. Pagination overlaps the last timestamp, deduplicates identities and fails closed on stalled/over-budget pages; it never skips a timestamp to pretend completeness. Requests are bounded to seven days and ten pages per stream. Receipt conflicts or late updates to an observed interval require review. HTTP/network failure returns unavailable rather than zero balances.

Known external flows are kept separately from performance. Deposits increase external cash-flow totals; withdrawals and transfers decrease them when their direction and fee semantics are unambiguous. Funding is reported separately but remains part of observed equity: it is **not added again**. Performance balance is equity minus cumulative external flows since the baseline. Net equity change excluding flows is that balance minus initial observed equity; it is not labelled realized trading profit.

The observed loss checks compare performance balance with the recorded daily reference and performance high-water mark. Loss allowance uses the smaller of initial/current equity, so deposits cannot dilute previously incurred losses. The old daily window is checked before rollover. Halts are latched and survive restart; there is no public reset endpoint. Existing private-order previews remain historical snapshots; a latched halt refuses new previews.

Supported receipts: USDC deposits, zero-fee withdrawals/internal/subaccount transfers, explicit spot/perps account-class transfers, and BTC funding. Nonzero transfer/withdrawal fees, vault/rewards/liquidation/other funding types or unsupported schemas require owner review; their accounting semantics are not guessed. This conservative boundary is deliberate while funded acceptance is postponed.

The private UI offers explicit start/refresh, current equity, cash flows, funding and net equity change since the baseline. Old observations are marked stale. Snapshots include all three private tables; restoring them does not reset halts or authorize execution. Data retention and off-machine confidentiality remain operator responsibilities.

Verified offline: 261 Python tests, including deposit/loss separation, duplicate funding, old-day checks, drawdown, address isolation, restart, late/conflicting history rollback, exact decimal JSON, pagination failure and authenticated HTTP boundaries. The production web build and 27 wallet tests pass. Actual wallet/receipt behavior and complete capital reconstruction remain exchange acceptance gates.

Sources: [time-range pagination](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#pagination), [funding/non-funding queries](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals#retrieve-a-users-funding-history-or-non-funding-ledger-updates), [ledger schemas](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions).

# Distribution policy v3

`fees-bot60-team40-author50-donate50-v3` is enforced in Decimal code. The owner replaced the own-agent token buyback destination with donations on 2026-10-21; user-author shares and builder fees remain unchanged.

Received builder fees net of refunds allocate **60% bot capital / 40% team**, corresponding to **0.03% / 0.02%** of fee-bearing entry volume at the total 0.05% builder fee. Amounts are exact USDC; rounding dust stays in bot capital. Anonymous pitches, deposits, unrealized PnL and unclaimed rewards create no author entitlement or received revenue.

Verified user-strategy settlements allocate **50% of cumulative positive net profit to the author / 50% to bot capital** after per-strategy loss recovery. Past author payments are subtracted once. Attributed net profit includes observed closed-fill PnL minus fill fees plus unambiguously attributed funding. Every owned execution can be allocated once, including a zero-cash account checkpoint when gains and losses offset. These metadata checkpoints create liabilities, never cash.

Own-agent positive cumulative net realized profit allocates **50% to donations / 50% to bot capital**, after expenses and portfolio loss recovery, excluding user-strategy profit. The total eligible basis is conservatively capped by whole-account profit after author entitlement. Historical buyback spending offsets the new donation entitlement so spent dollars cannot be allocated twice. Deposits, received fees and open PnL do not create donations. Later losses reduce outstanding entitlement before another allocation.

Author, team and donation earmarks are protected from new project entries and author payouts. New token buyback preparation and unsigned dispatch are disabled before any network request; already signed operations can still be reconciled and existing purchased lots retain recovery/burn handling. Historical receipts remain immutable cash debits.

The product shows **Charity pool** beside Trading PnL, with a separate **Sent** figure. Public amounts require a single registered mainnet project source, exact reconciled settlement identities and matching cumulative settlement totals; absent, fixture or mismatched evidence publishes null. No recipient or payment provider has been selected for this policy: sent remains zero for the current policy and transfers stay disabled. The old retired `charity_payout` writer is not revived. An accrual is not a completed donation; the payment integration remains pending.

No local report authorizes a transfer or proves external acceptance. Author balances and verified observed-payment handling are described in [STRATEGY-SHARING.md](STRATEGY-SHARING.md).

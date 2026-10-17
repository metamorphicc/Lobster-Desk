# Distribution policy v2

`fees-bot60-team40-author50-v2` is enforced in Decimal code and displayed in Treasury. It supersedes the previous donation policy.

Received builder fees net of refunds allocate **60% bot capital / 40% team**, corresponding to **0.03% / 0.02%** of fee-bearing entry volume at the total 0.05% builder fee. Amounts are exact USDC; rounding dust stays in bot capital. Anonymous pitches, deposits, unrealized PnL and unclaimed rewards create no author entitlement or received revenue.

Verified user-strategy settlements allocate **50% of cumulative positive net profit to the author / 50% to bot capital** after per-strategy loss recovery. Past author payments are subtracted once. Attributed net profit includes observed closed-fill PnL minus fill fees plus unambiguously attributed funding. Every owned execution can be allocated once, including a zero-cash account checkpoint when gains and losses offset. These metadata checkpoints create liabilities, never cash.

All author/team outstanding liabilities are protected from new project entry sizing and token purchases. The existing token rule is restricted to the agents' own strategy profits after expenses and portfolio losses. User-strategy profits do not fund buybacks. Unknown operating/liability/tax reserves still suppress a spendable buyback budget. A recorded payout or later loss can block further allocation until recovered.

Historical retired-payment receipts remain immutable cash debits so a software update does not rewrite balances. New donation receipt appends are refused; no donation runner/provider/API/UI remains. The legacy generic receipt report is capped by this current policy rather than allowing fee income or author shares to fund token purchases.

No local report authorizes a transfer or proves external acceptance. Author balances and verified observed-payment handling are described in [STRATEGY-SHARING.md](STRATEGY-SHARING.md).

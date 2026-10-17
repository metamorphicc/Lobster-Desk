# Lobster Desk — product features

Current economics v2 replaces the former donation allocation. Executable donation/provider code, CLI/configuration and UI were removed in Stage 10. Default execution remains paper; implementing accounting does not activate real trading or payments.

| ID | Feature | Current behavior |
| --- | --- | --- |
| F01 | Autonomous research | Bounded BTC trend, breakout and mean-reversion hypotheses, chronological history/funding tests, cost stress and critic veto. |
| F02 | Agent decisions | Analyst/risk review and deterministic banker/executor; models cannot enlarge risk or capital permissions. |
| F03 | User pitches | Anonymous pitches remain available. Signed-in users can submit a wallet-attributed strategy before review; submitting does not guarantee execution. |
| F04 | Project execution | Separate opt-in testnet/mainnet runner with small positions, exact loss budgets, partial-fill protection and recovery. Attributed user strategies use project capital after the same reviews and coded gates. |
| F05 | User-owned trading | Separate Testnet/Mainnet sign-in, explicit permissions/exact trade signatures, private journals and dedicated API-wallet runners. This differs from earning an author share on project-funded trades. |
| F06 | Public audit | Tank, Research and Journal views, public project exchange observations and evidence exports. Wallet authorship records, user account journals and proofs remain private. |
| F07 | Fee-funded capital | 0.05% entry builder fee, additional to exchange costs: 0.02% of notional to the team and 0.03% to bot capital. Only received, reconciled fees are allocated. |
| F08 | Strategy-author share | 50% of positive cumulative net realized profit per verified user strategy goes to its author; 50% remains in bot capital. Fees/funding count once, strategy losses must be recovered, and retries do not allocate again. |
| F09 | Author balances/payments | Private earned/paid/outstanding balances and public aggregate totals. A separate opt-in bounded Hyperliquid USDC payout runner selects verified earned recipients, persists commands before sending and requires matching debit/credit observations. Operator-only recording of an existing transfer is also supported; uncertainty blocks replacement payments. |
| F10 | Bot-only token policy | Existing 50% eligible own-agent net-profit buyback/burn rule remains for the agents' own strategies. User-strategy profits and author/team liabilities are excluded. Solana mint/funding/acceptance remain external configuration. |
| F11 | Product data and navigation | Actual public mainnet BTC candles with 1m/5m/15m views. Public capital and trades use registered mainnet project observations; absent/stale capital stays blank. The tank, Journal, Research and My strategies form the main navigation; treasury, fee allocation and operational tools remain in docs and `/operator`. |

## Fee distribution

| Destination | Executed entry notional | Received-fee share |
| --- | --- | --- |
| Team | 0.02% | 40% |
| Bot capital | 0.03% | 60% |
| Total | 0.05% | 100% |

Illustration: $1,000,000 of fee-bearing entry volume would generate $500 gross fees, split $200 team / $300 bot. These are hypothetical values, not production revenue. Micro-USDC rounding dust stays with bot capital. Team revenue is before operating costs.

## User-strategy profits

A strategy belongs to the wallet that authenticated before submitting it. Display names do not establish ownership, and old anonymous pitches cannot be claimed afterward. Attribution is bound to the exact reviewed pitch, network and execution journal.

Only closed mainnet project trades accrue real author shares. Net profit includes confirmed fill PnL, trading fees and attributable signed funding. Cumulative losses in that strategy are recovered before further entitlement. For $100 eligible net profit, the author earns $50 and $50 remains with the bot. Payouts reduce outstanding liability and cash; they do not create another trading expense or another profit credit.

Author/team liabilities are reserved before new project entries and before any bot-only token buyback. A cash movement or capital deposit is not new revenue. Accrued author shares do not prove a payment. See [STRATEGY-SHARING.md](STRATEGY-SHARING.md) for endpoints and boundaries.

There is no donation feature, token-holder dividend, staking entitlement, guaranteed return or arbitrary strategy-code execution. Real reward claiming, treasury funding/routing, wallet acceptance and public launch remain separate from local tests.

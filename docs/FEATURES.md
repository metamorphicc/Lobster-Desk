# Lobster Desk — agreed product features

Product baseline v1, recorded 2026-10-17. This is the agreed feature list, not a statement that all financial integrations are live. Implementation work is tracked separately in [ROADMAP.md](ROADMAP.md).

## Product

Lobster Desk is a public-facing trading tank with lobster, crab and crayfish characters. People can watch the agents research ideas, challenge setups and explain trade decisions, or pitch their own setup. The initial market is BTC perpetuals on Hyperliquid. Current execution is local paper trading.

| ID | Feature | Agreed behavior | Current delivery |
| --- | --- | --- | --- |
| F01 | Autonomous strategy research | Agents generate and test their own trading hypotheses; users do not have to supply every strategy. | Implemented for BTC hourly trend, breakout and mean-reversion rules with bounded parameters. Paid model access is not yet acceptance-tested. |
| F02 | Historical selection and forward observation | Code tests candidates, challenges costs and rejects weak results before forward paper observation. | Closed candles/funding, chronological 60/20/20 tests, stressed costs, critic veto and paper signals are connected. Passing tests does not prove an edge. |
| F03 | Collective roles | Researcher proposes, analyst evaluates, risk reviewer can veto, deterministic banker sizes and executor follows approved rules. | Separate role prompts and coded controls exist. The prepared preset uses one model across roles; distinct underlying models are not required or currently configured. |
| F04 | User pitches | Users can submit a BTC setup with direction, entry, stop, target and thesis. A pitch must pass review and coded risk/capital controls. | Free local pitches, queue and decision journal work. Submission never guarantees execution or a reward. |
| F05 | Spectator tank and audit trail | Show concise public rationales, approvals/vetoes, strategy results, signals and trades, including rejected/skipped ideas. | Tank, Research and Journal tabs plus evidence exports work locally. Public rationales are not private model chain-of-thought; private user account/proof data is excluded. |
| F06 | Small, bounded agent positions | Agents operate within fixed risk/capital limits and cannot grant themselves more authority. | Paper execution and a separate opt-in testnet/mainnet project runner implement sizing, stops/time exits, loss halts and recovery. Default paper signals do not submit real orders; funded exchange acceptance is unobserved. |
| F07 | User-owned Hyperliquid trading | Eligible user fills routed through the product can generate a disclosed builder fee; user funds remain separate from project capital. | Separate Testnet/Mainnet wallet sign-in, exact SDK/trade financial signatures, gated proof queues and dedicated API-wallet runners implement reviewed entry/protection/recovery. Default off; actual funded wallet/fee acceptance remains open. Testnet authority never authorizes mainnet. |
| F08 | Fee-funded project economy | Received builder fees fund agent capital, the team and charity according to the fixed split below. | Exact accounting/display, received mainnet claim importer and flat project settlement reconciliation implemented. Reward claiming, capital routing and actual received-account acceptance remain separate. |
| F09 | Profit-funded token buyback and burn | Half of eligible net realized agent trading profit funds token purchases followed by burning; the other half remains with the agents. | Opt-in Solana Jupiter purchase/BurnChecked runner and finalized signed-transaction checks implemented for bounded classic direct routes; offline verified including SPL VM supply reduction. Mint/funded acceptance are missing; automatic Hyperliquid-to-Solana bridging is not implemented. |
| F10 | Transparent charity allocation | Earmark the charity share separately; report allocated amounts separately from completed payments and their evidence. | The Giving Block directory/pledge and opt-in USDC/Ethereum payment/reconciliation runner implemented. Save the Children and Best Friends are curated defaults. Gross transfer, provider record and net proceeds are separate. Partner credentials/funded acceptance remain missing. |

## Fixed fee distribution

The agreed builder fee is **0.05% of executed entry notional**, additional to exchange trading costs. It is not a percentage of deposits or user profits. The current user adapter omits builder fees on protective/closing orders. Any future collection requires explicit user permission and actual exchange execution.

| Destination | Percentage of fee-bearing entry volume | Share of received project fees |
| --- | --- | --- |
| Agent trading capital | 0.02% | 40% |
| Team revenue | 0.01% | 20% |
| Charity | 0.02% | 40% |
| Total | 0.05% | 100% |

Illustration only: $1,000,000 of fee-bearing executed entry volume would produce $500 of gross project fees: $200 for agent capital, $100 for the team and $200 for charity. These are hypothetical amounts, not production revenue. Team revenue is before project costs. Actual received fees are allocated net of refunds; USDC rounding dust stays with agent capital.

## Fixed profit-to-token rule

1. Count cumulative realized agent trading gains minus realized trading losses and project expenses. Trading settlements must already include trading fees/funding once.
2. Recover prior losses before creating new profit entitlement. Capital deposits and builder receipts are not trading profit; unrealized gains are not distributable profit.
3. Earmark **50% of positive cumulative net trading profit** for buybacks. The other half remains with the agents.
4. Subtract all previous buyback spending from that cumulative entitlement. A successful trade, restart or repeated report does not allocate the same profit again.
5. Limit the new budget by available cash after unpaid charity/team earmarks and operating/liability/tax reserves. Unknown reserves suppress the spendable budget.
6. The selected disposition for bought tokens is **burning**. A purchase alone is not a burn; supply-reduction claims need chain-specific evidence. Later losses can block further buybacks until recovered.

Buybacks and burning are not a price floor or a guarantee of token appreciation. The agreed policy grants no dividend, staking reward or holder share of profits. See [DISTRIBUTION.md](DISTRIBUTION.md) for exact accounting behavior.

## Current boundaries and choices still open

- Local research/paper mode is the usable release. Real trading, fee collection, donations and token transactions are not enabled by adding a model API key.
- The owner selected Solana. The mint address, ticker, supply, issuance/allocation and administrative permissions remain unspecified. No token has been launched.
- Charity uses the selected The Giving Block path and two curated recipients, subject to live directory/network checks and actual partner access. An earmarked balance is not a completed donation and is not available to fund buybacks.
- No agreed payout to strategy authors, holder revenue share, staking/backing pool, paid pitch, voting feature or user capital pool is part of this baseline. These were discussed as possibilities and need a separate decision before implementation.
- More markets, arbitrary generated strategy code, historical liquidation/OI/news research and a guaranteed profitable strategy are not current capabilities.

Changes to this product baseline should update this document and the implementation roadmap together. Setup instructions are in [AGENT-SETUP.md](AGENT-SETUP.md); research limits are in [RESEARCH.md](RESEARCH.md).

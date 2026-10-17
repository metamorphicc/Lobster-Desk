# Implemented economics revision

The owner explicitly requested implementation after the initial documentation-only decision. Stage 10 replaces the previous donation system in executable code and UI.

- Total entry builder fee: **0.05%**.
- Team: **0.02% of notional / 40% of received fees**.
- Bot capital: **0.03% of notional / 60% of received fees**.
- Verified user-strategy net profits: **50% author / 50% bot**, with trading fees/funding and per-strategy loss recovery.
- Donation execution, configuration, command and interface removed.

See [FEATURES.md](FEATURES.md), [DISTRIBUTION.md](DISTRIBUTION.md) and [STRATEGY-SHARING.md](STRATEGY-SHARING.md). Author entitlements accrue from reconciled closed mainnet project trades. Actual payouts have a separate opt-in bounded Hyperliquid runner and an operator-only observed-transfer receipt path. No real payment was sent during implementation. The separate existing own-agent token policy does not use user-strategy profit.

All work stays in local commits on `lobster-desk`; never push automatically.

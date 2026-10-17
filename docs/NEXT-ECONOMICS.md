# Revised economics — owner decision, 2026-10-17

This decision supersedes the earlier donation allocation. It is recorded for the next implementation pass; current accounting/UI still implement the previous policy. No financial runner was activated or funds transferred.

- Total builder fee remains **0.05% of executed entry notional**.
- **0.02% of entry notional (40% of received fees)** goes to the team.
- **0.03% of entry notional (60% of received fees)** replenishes the bot's trading capital.
- Donations are cancelled. The donation integration should be retired from active product flows.
- Profit from bot trades attributed to a user's strategy is allocated **50% to that strategy's author and 50% back to bot capital**. The same profit cannot also fund the former buyback allocation.

This does not authorize trading every submitted strategy: review and deterministic risk/capital controls still apply. No user payout feature exists yet. Before implementing payouts, specify attributable net profit/costs, loss recovery, author ownership, settlement timing and recipient verification. The treatment of profits from the agents' own strategies, including any remaining token buyback policy, was not changed explicitly in this decision.

The owner requested deferring substantial code changes to conserve usage. All prior work is preserved in local commits on `lobster-desk`; the working tree was clean, so no stash was necessary. Never push automatically.

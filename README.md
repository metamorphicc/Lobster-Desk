# Lobster Desk

A public trading tank: pitch a BTC setup, watch three crustacean agents challenge it, and follow the decision through a verifiable paper trade.

**Local development. No mainnet order execution, deposits, token, or fee collection is enabled.** Market data and execution modes are independent: live Hyperliquid data can drive simulated trades.

## Structure

- `apps/api`: FastAPI, deterministic risk/capital controls, paper broker, market feeds, agent adapters, persistent audit journal.
- `apps/web`: Next.js trading tank and pitch interface.
- `docs/ROADMAP.md`: stages, substages, acceptance criteria, and completion status.
- `docs/ARCHITECTURE.md`: financial authority, data flow, and safety boundaries.

See the roadmap for implementation progress. Every completed substage is a separate local commit on `codex/mvp-foundation`. The `origin` remote points to the owner's GitHub repository; nothing is pushed automatically.


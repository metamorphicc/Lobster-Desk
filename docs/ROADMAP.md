# Implementation roadmap

## Delivery rules

Each checked substage has its own local commit. No pushes or deployments. A stage is complete only after its acceptance checks pass. Local paper trading is the first usable release; external funding and execution are separate gates.

## Stage 0 — Foundation

- [x] **0.1 Repository and specification.** Local branch, GitHub remote, architecture, delivery rules, initial scope.

## Stage 1 — Financial core

- [x] **1.1 Risk and capital contracts.** Decimal calculations, BTC allowlist, leverage/notional/loss limits, freshness, expiry, position sizing. Verified: 25 invariant/validation tests.
- [ ] **1.2 Persistent paper broker.** Atomic reservations, idempotent fills, append-only events, position lifecycle, restart and fee accounting tests.

## Stage 2 — Data and agents

- [ ] **2.1 Market feeds.** Explicit synthetic demo feed and read-only Hyperliquid feed; no silent fallback from live to synthetic data.
- [ ] **2.2 Decision pipeline.** Analyst, risk reviewer, banker, durable transitions and recorded reasons; deterministic demo provider plus optional real model adapter.

## Stage 3 — Local service

- [ ] **3.1 API and worker.** Validated pitches, idempotency, shared state, SSE, automatic position protection, protected operator controls and API tests.

## Stage 4 — Usable product

- [ ] **4.1 Tank interface.** Responsive character scene, chart, pitches, queue, decision log, positions and transparent treasury; meaningful empty/error/loading states.
- [ ] **4.2 Integration and handoff.** Browser flow, persistence/recovery verification, production build, local launch scripts and operational documentation.

## Stage 5 — Exchange testnet and user execution

- [ ] **5.1 Testnet execution adapter.** Separate signer, official SDK, nonce ownership, partial fills, exchange-native stops and reconciliation. Requires a funded testnet account and dedicated API wallet for end-to-end verification.
- [ ] **5.2 User-owned trading.** Wallet connection, builder-fee approval, explicit user signatures, fee disclosure, order status and account isolation. Verify approval and revocation before enabling collection.

## Stage 6 — Controlled production release

- [ ] **6.1 Operational readiness.** Independent security review, restore drill, alerting, credentials, supported jurisdictions, deployment and loss-budget configuration.
- [ ] **6.2 Small mainnet pilot.** Owner-authorized capital and activation; monitor actual fills, fees, funding, drawdown, retention and organic volume. Never infer readiness from paper profits alone.

## Stage 7 — Token economics (after validation)

- [ ] **7.1 Economic and legal specification.** Jurisdiction, token rights, expense/reserve waterfall, loss recovery and buyback budget.
- [ ] **7.2 Buyback reporting.** Owner-approved transactions with public receipts; no autonomous treasury transfers in the trading agent.

## Initial financial policy

- BTC only; one open position, including outstanding reservations.
- Up to 2x leverage; isolated account assumptions for the future exchange adapter.
- Planned loss at the stop including estimated execution costs <= 0.25% of equity.
- Daily loss threshold: 1% of day-start equity, including open PnL.
- Maximum drawdown: 5% from the equity high-water mark.
- Minimum notional: $10; maximum notional: 25% of equity in the initial paper policy.
- Stale or missing market data, expired proposals, invalid model output, or failed controls prevent entry.
- Paper PnL includes modeled taker fees and slippage; funding is explicitly excluded until implemented.
- Cash deposits, trading profit and hypothetical builder revenue are reported separately.


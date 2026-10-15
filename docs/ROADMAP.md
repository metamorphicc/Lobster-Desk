# Implementation roadmap

## Delivery rules

Each checked substage has its own local commit. No pushes or deployments. A stage is complete only after its acceptance checks pass. Local paper trading is the first usable release; external funding and execution are separate gates.

## Stage 0 — Foundation

- [x] **0.1 Repository and specification.** Local branch, GitHub remote, architecture, delivery rules, initial scope.

## Stage 1 — Financial core

- [x] **1.1 Risk and capital contracts.** Decimal calculations, BTC allowlist, leverage/notional/loss limits, freshness, expiry, position sizing. Verified: 25 invariant/validation tests.
- [x] **1.2 Persistent paper broker.** Atomic reservations, idempotent fills, append-only events, position lifecycle, restart and fee accounting. Verified: 37 core tests, including concurrency, rollback and gap losses.

## Stage 2 — Data and agents

- [x] **2.1 Market feeds.** Explicit synthetic demo feed and read-only Hyperliquid feed; no silent fallback from live to synthetic data. Verified: parsing, caching and outage behavior; 40 tests total.
- [x] **2.2 Decision pipeline.** Analyst, risk reviewer, banker, durable transitions and recorded reasons; explicit scripted demo provider and optional Anthropic structured-output adapter. Verified: 45 tests; paid provider contract mocked, no API key used.

## Stage 3 — Local service

- [x] **3.1 API and worker.** Validated pitches, idempotency, shared state, SSE, independent position protection and protected operator controls. Verified: 51 API/core tests. Loopback-only service; no mainnet order route.

## Stage 4 — Usable product

- [x] **4.1 Tank interface.** Original character scene, candlestick chart, validated pitches, queue, decision journal and transparent treasury. Production build passes; browser pitch reached capital reservation. Responsive checks continue in 4.2.
- [x] **4.2 Integration and handoff.** Browser flow, persistence/recovery, production build, cross-platform launch scripts, pinned dependencies and operational documentation. Verified: 60 tests, typecheck/build, responsive UI and public-data smoke check. See `VERIFICATION.md` for unverified external dependencies.

## Stage 5 — Exchange testnet and user execution

- [ ] **5.1 Testnet execution adapter.** Separate signer, official SDK, nonce ownership, partial fills, exchange-native stops and reconciliation. Requires a funded testnet account and dedicated API wallet for end-to-end verification.
  - [x] **5.1a Contracts and restricted signer.** BTC precision, reviewed proposal binding including expiry/reviews, isolated leverage, official SDK testnet-domain signatures and $50 default entry cap. Verified offline: signature domain recovery and fail-closed constraints; 86 tests total.
  - [x] **5.1b Durable order lifecycle.** Separate persistent ledger, atomic command claims/nonces, no blind replay after timeout, deduplicated fills and exchange-confirmed protection of actual filled size. Verified offline: 108 tests including partial fills, restart, rejected stops and fixed-host transport.
  - [ ] **5.1c Local testnet workbench.** Read-only readiness/preflight, operator-only staging, separate journal and tests; no automatic activation.
  - [ ] **5.1d Funded testnet acceptance.** Verify API wallet permissions, actual partial fills/stops and restart with a funded testnet account. Not complete until observed on the exchange.
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


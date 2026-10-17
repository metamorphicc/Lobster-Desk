# Implementation roadmap

## Delivery rules

Each checked substage has its own local commit. No pushes or deployments. A stage is complete only after its acceptance checks pass. Local paper trading is the first usable release; external funding and execution are separate gates.

Current handoff: local preparation includes Stage 8 autonomous paper research and agreed economics. Main Stages 5–7 remain partial because funded acceptance, live/public integrations, public hosting/identity controls, owner capital, the Solana mint/provider credentials and financial activation are outstanding. Stage 9 implements separately gated financial writers; external acceptance remains open. See `HANDOFF.md`; a checked preparation substage does not complete its parent production gate.

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
  - [x] **5.1c Local testnet workbench.** Read-only readiness/preflight, operator-only staging/cancellation, separate journal and owner-run signer CLI. Verified: 124 tests, typecheck/build, anonymous public testnet inspection and responsive browser checks. No automatic activation or exchange orders during development.
  - [ ] **5.1d Funded testnet acceptance.** Verify API wallet permissions, actual partial fills/stops and restart with a funded testnet account. Not complete until observed on the exchange.
    - Owner postponed this gate; continuing local user-trading implementation without enabling exchange execution.
    - [x] **5.1d.1 Acceptance tooling.** Unsigned evidence capture, fresh order identity queries and an owner review matrix; reports never certify acceptance automatically.
- [ ] **5.2 User-owned trading.** Wallet connection, builder-fee approval, explicit user signatures, fee disclosure, order status and account isolation. Verify approval and revocation before enabling collection.
  - [x] **5.2a Public account boundary.** Independent read-only testnet user accounts, validated public addresses, exact fee units and current builder approval inspection. No authentication, server-held user keys or order route.
  - [x] **5.2b Wallet interface.** EIP-6963 discovery, explicit EIP-1193 connection, account/network-change isolation and public-address watch mode in the Testnet tab. Verified: 11 wallet-session tests, production build and responsive browser lookup; real extension signing remains outside this read-only substage.
  - [x] **5.2c Builder consent plans.** Exact fee previews and SDK-compatible unsigned approval/revocation payloads, account binding and downloadable plans. Verified: 155 Python tests, 11 wallet tests, build and browser cost/download/revocation checks. No automatic signing or collection.
  - [ ] **5.2d User execution acceptance.** Explicit user signing, actual testnet orders/protection, builder eligibility, approval/revocation and fee receipts. Requires owner-reviewed exchange evidence before activation.
    - [x] **5.2d.1 Local wallet authentication.** One-time server challenges, EOA signature recovery, hashed scoped sessions, replay/expiry/restart/clock checks. Verified offline: 230 Python tests. No trading authority or real wallet signature used.
    - [x] **5.2d.2 Explicit sign-in interface.** Separate public watch and verified session states, reviewed sign-in message, account/network invalidation and memory-only tokens. Verified: 27 Node wallet tests, build and responsive public-watch separation. Real extension prompts remain unverified.
    - [x] **5.2d.3 Private order preview.** Session-bound per-trade sizing/fees, immutable private records, idempotency and explicit execution blockers. Verified: 249 Python tests, 27 Node tests, build and actual React message/report layouts using labelled offline fixtures. User daily-loss references, exchange signing/submission and funded acceptance remain open.
    - [x] **5.2d.4 User capital references.** Private durable observation-based loss references, deduplicated cash flows/funding, latched halts and exact JSON money parsing. Unknown prehistory, truncated/late history and ambiguous-fee receipt types never authorize entry. Verified: 261 Python tests, 27 Node tests and production build. This is not reconstructed full-day/all-time accounting or funded acceptance.
    - [ ] **5.2d.5 Explicit exchange consent and order path.** Fresh reviewed user signatures, serialized nonces, owner-bound execution journal, confirmed-fill protection and observed builder approval/revocation/fees. Keep activation gated while acceptance is postponed.
      - [x] **5.2d.5a Local consent contracts and execution hooks.** Immutable unique-API-wallet profiles, private SDK-compatible unsigned permissions, exact-plan EIP-712 local intents, atomic offline proof handoff, entry-only broker guards and observed builder-fee components. No financial proof/dispatch HTTP route. Live multi-user orchestration remains unimplemented; see `USER-EXECUTION.md`.
      - [x] **5.2d.5b Locked user orchestration rehearsal.** Canonical separate journals, atomic plan/proof audit links, exact quantity/price/expiry signing bounds, refreshed user cash-flow/fee/builder/account-scope gates and entry-only builder fees. Offline partial-fill/recovery tests substitute an in-memory exchange. Real user writer/runner/wallet integration remains closed and unaccepted.
      - [x] **5.2d.5c Global wallet-role isolation.** API wallet, user main and builder roles cannot overlap across registered profiles; the shared project builder may serve multiple independent users.
      - [x] **5.2d.5d Unattended offline runner.** Standalone five-scenario lifecycle/recovery rehearsal with new isolated databases, public unfunded vectors and hashed reports. No HTTP/wallet/credential access or live mode; production user transport stays locked.
      - [x] **5.2d.5e Unsigned consent workbench.** Private redacted context/journal, exact local/SDK payload review, immutable plan binding and downloads without wallet RPC. Python-generated SDK fixtures drive client rejection tests; responsive state layouts and production build pass. No financial signing or submission route is enabled.
    - [ ] **5.2d.6 User exchange acceptance.** Real extension behavior and owner-reviewed testnet evidence. Local proofs and unsigned previews do not complete this gate.
      - [x] **5.2d.6a Acceptance inventory.** Private bounded evidence templates, contained file hashes and wallet/fee/recovery case matrix. Inventory never certifies acceptance or enables exchange transport.

## Stage 6 — Controlled production release

- [ ] **6.1 Operational readiness.** Independent security review, restore drill, alerting, credentials, supported jurisdictions, deployment and loss-budget configuration.
  - [x] **6.1a Local recovery tooling.** Verified SQLite snapshots, hashes/counts, committed WAL capture and restore into a new directory. Tested actual local paper recovery and offline unknown-command/nonce preservation; live ledgers are never replaced automatically.
  - [x] **6.1b Local API boundary review.** Exact loopback hosts/origins, bounded bodies/slow reads, redacted settings errors and scoped internal report. Verified: 172 Python tests, 11 wallet tests, build, live proxy/browser checks and npm production audit. Public launch remains gated by 6.1c.
  - [ ] **6.1c Production readiness.** Independent security review, authenticated public service, distributed limits/leadership, alerts, off-machine recovery, deployment and jurisdiction decisions. Local tests do not complete this gate.
    - [x] **6.1c.1 Local readiness API.** Separate liveness/readiness, worker task/tick checks, SQL counters and scoped non-mutating alerts. Verified: 186 Python tests, including actual local worker ticks, stale exposure, database failure and unresolved testnet state.
    - [x] **6.1c.2 Operator diagnostics interface.** Local status panel and fixed-loopback probe command. Verified: 195 Python tests, 11 wallet tests, production build, healthy/disabled-worker browser and CLI checks, responsive layouts. No external notification delivery or activation.
    - [x] **6.1c.3 Durable pitch admission.** Persistent bounded request windows and SQL queue/review-budget counts. Verified: 207 Python tests, including independent-store concurrency, restart, clock rollback, corrupt state, snapshot recovery and forwarded-header bypass attempts. This local control does not replace production identity or distributed leadership.
    - [x] **6.1c.4 Local paper worker ownership.** Single-process ownership per SQLite database, startup/shutdown cleanup and OS lock release after actual owner termination. Verified: 215 Python tests and a live duplicate-API startup refusal. Distributed leadership remains outside this local substage.
    - [x] **6.1c.5 Locked dependency advisory check.** All 56 Python lock entries audited without skips, installed-version/consistency checks and npm production audit. Zero reported advisories on 2026-10-16; this is not an independent supply-chain review. See `DEPENDENCY-AUDIT.md`.
    - [x] **6.1c.6 Local release preparation.** Clean committed-source packaging, lock/archive hashes, local-only configuration, monitor JSON interface and explicit independent-review/off-machine recovery handoff. Public hosting, distributed controls and actual external integrations remain unimplemented/unverified; see `RELEASE.md`.
    - [x] **6.1c.7 Monitor failure contract.** Machine-readable unavailable/malformed observations return exit 2 with a static critical alert; scoped output cannot acquire production authority or expose raw configuration.
    - [x] **6.1c.8 Owner-selected branch support.** Source packaging accepts the clean attached `lobster-desk` branch without requiring a prefix; owner branch instructions and documentation match the rename. Runtime/secret-path and disabled-activation checks remain intact.
- [ ] **6.2 Small mainnet pilot.** Owner-authorized capital and activation; monitor actual fills, fees, funding, drawdown, retention and organic volume. Never infer readiness from paper profits alone.
  - [x] **6.2a Disabled pilot rehearsal.** Exact-decimal, hash-bound budget plan and cash-flow-neutral loss/recovery checks with no mainnet transport. Owner capital/loss/reserve choices remain blank; missing observations produce null metrics. See `PILOT.md`.

## Stage 7 — Token economics (after validation)

- [ ] **7.1 Economic and legal specification.** Jurisdiction, token rights, expense/reserve waterfall, loss recovery and buyback budget.
  - [x] **7.1a Local treasury accounting and policy rehearsal.** Independent append-only receipt book, exact USDC, atomic idempotency/hash chain, capital/revenue separation, loss carry-forward and reserve-bounded provisional allocation. Historical generic policy rehearsal; Stage 8.1 now specifies the agreed fee/profit/burn split. Token network/contract and reserve amounts remain unset; no transfer authority. See `ECONOMICS.md`.
- [ ] **7.2 Buyback reporting.** Owner-approved transactions with public receipts; no autonomous treasury transfers in the trading agent.
  - [x] **7.2a Local receipt-linked reporting.** Exact spend/purchase/disposal linkage, no duplicate spend or excess disposal, separate sink transfers/supply-reduction claims, private hashed reports and treasury snapshot recovery. No real transactions, chain authentication, publication or token contract; see `BUYBACK-REPORTING.md`.

## Stage 8 — Autonomous strategy research and agreed economics

- [x] **8.1 Fee/profit/burn accounting.** New default entry builder fee 0.05%, exact 40/20/40 received-fee earmarks and cumulative net-profit 50% buyback entitlement, with prior spending, loss recovery, charity/team protection and unknown-reserve blockers. No transfers or burns; see `DISTRIBUTION.md`.
- [x] **8.2 Historical data and deterministic strategy laboratory.** Validated closed hourly candles/funding, bounded three-family grammar, next-bar Decimal simulation, chronological 60/20/20 selection and stressed costs. Verified: 14 focused tests plus real read-only 1,440-candle/funding smoke check. Hourly path/funding approximations and rolling-history reuse are explicit; see `RESEARCH.md`.
- [x] **8.3 Autonomous paper research cycle.** Bounded development-only hypotheses and independent veto role, durable call/schedule limits, interrupted-call recovery, atomic signal/pitch provenance and strategy time exits through the existing paper controls. Read-only audit/economics APIs and isolated runner; real model requests remain mocked without owner keys. See `RESEARCH.md`.
- [x] **8.4 Research interface and key-only paper setup.** Research history/results/critic/signal links and full evidence export, independent distribution display, ignored key preset and checked launcher. Verified: 388 Python tests, 46 Node tests, TypeScript/build, responsive live/labelled state views and isolated research DB restore. Real paid-provider acceptance, execution, donations and burns remain unverified/disabled; see `AGENT-SETUP.md`.
- [x] **8.5 Product feature baseline.** Agreed feature inventory, 0.05% entry fee / 40-20-40 distribution and 50% eligible net-profit buyback/burn rule recorded in `FEATURES.md`, with implementation status and undecided options separated. Documentation only; no financial activation or code behavior change.

## Stage 9 — Complete operational integrations

These are code deliverables, not documentation substitutes. Default operation remains paper; implementing a writer does not authorize the developer to send funds/orders. Every external integration must distinguish executable code, offline verification and observed external acceptance.

- [x] **9.1 Network-bound execution core.** Explicit mainnet/testnet fixed transports/signing domains, immutable network/account journals and disjoint order IDs. Offline mainnet fixtures reuse partial-fill protection and restart recovery. No real orders; see `EXECUTION-NETWORKS.md`.
- [x] **9.2 Autonomous project execution runner.** Separate opt-in owner process bridges reviewed research signals to network-bound dispatch, with OS lease, exact observed cash-flow/loss references, explicit budgets, strategy time exits and restart recovery. Five focused runner tests use an in-memory exchange; no financial command run. Web paper state remains separate; see `PROJECT-EXECUTION.md`.
- [x] **9.3 User financial signing and runner.** Explicit permission/intent signing, verified submission endpoints, per-user execution ownership and full journal recovery.
  - [x] **9.3a Financial testnet core.** New execution-consent domain, gated owner proof queue, immutable SDK permission jobs, separate API-key runner, per-owner journals/leases and recovery-only signer independent of expired reviews. Eight new focused cases pass; real wallet/funded acceptance and user mainnet remain open. See `USER-FINANCIAL.md`.
  - [x] **9.3b Financial wallet workbench.** Separate explicit SDK/trade EIP-712 review/sign/queue UI, strict wallet/profile/domain/fee/plan validation, account-change invalidation and private runner status. Treasury displays redacted Solana/charity evidence. 58 Node tests, TypeScript/production build and eight labelled state previews at 320/375/414/768 pass. Real wallet/provider acceptance remains unobserved.
  - [x] **9.3c User mainnet boundary.** Explicit Mainnet tab, chain/domain-separated sign-in and financial consent, namespaced profiles/plans/capital/jobs, distinct dedicated API wallets/journal roots and mainnet runner configuration. Six new backend and eleven client cases pass, including partial-fill/restart, cross-network refusal and uncertain permission no replay. Full backend: 495 passed; client: 69 passed; production build and 320/375/414/768 views pass. A real public mainnet account lookup passed; no financial command or extension signature occurred. Funded acceptance remains open.
- [x] **9.4 Forward paper funding.** Signed historical hourly settlements update cash/position PnL atomically and exactly once, including closed-position recovery/restart/concurrency. Missing coverage blocks new entries while protection remains independent. API/UI label tracked versus legacy unmodeled scope; see `PAPER-FUNDING.md`.
- [x] **9.5 Received revenue reconciliation.** Fixed-mainnet received-claim ingestion and flat-account net settlement, atomic cursors/receipts, dedicated-builder attribution and fill/funding/equity checks. 36 focused offline cases pass; actual account reconciliation remains unobserved. No reward claim or transfer; see `REVENUE-INGESTION.md`.
- [x] **9.6 Solana treasury execution.** Separate opt-in exact-input Jupiter purchase and full purchased-lot SPL BurnChecked, fixed mainnet/genesis, durable claims/signatures, finalized balance checks and read-only evidence API. 13 focused tests include actual SPL execution in LiteSVM; 72 combined checks pass. Supports bounded classic direct routes, requires separately funded Solana wallet; no automatic cross-chain bridge or observed funded acceptance. Mint remains unspecified; see `SOLANA-TREASURY.md`.
- [x] **9.7 Historical charity integration — removed in Stage 10.1.** The Giving Block authenticated EIN-matched directory, selected children/animal causes, exact USDC/Ethereum pledge and bounded payment runner, finalized-transfer/provider-record separation and uncertain-state recovery. Ten offline scenarios pass; real partner credentials, wallet funding and provider acceptance remain missing. No actual pledge/payment; see `CHARITY.md`.
- [x] **9.8 Public operation code.** Configurable public identity boundary, server packaging, external alerts, encrypted backup integration and operational checks. No deployment during implementation.
  - [x] **9.8a Public single-host boundary/packaging.** Exact HTTPS signing origin, distinct proxy/operator secrets, trusted client identity, connection bounds, standalone Next/Docker/Caddy source and private config generator. 52 focused backend/58 Node cases and build pass; Compose validates. Container runtime/HTTPS acceptance unverified because Docker daemon is unavailable. No deployment; see `PUBLIC-DEPLOYMENT.md`.
  - [x] **9.8b Complete encrypted recovery.** Canonical financial-journal catalog/inventory, authenticated AES-256-GCM bundles, bounded immutable AWS SDK S3 transport and isolated restore. Thirteen focused/49 combined cases pass, including uncertain-entry nonce recovery without replay; actual local two-database encrypted restore passed. Real off-machine AWS acceptance remains unobserved. See `ENCRYPTED-RECOVERY.md`.
  - [x] **9.8c External operational alerts.** Durable static-code outbox, runner/financial uncertainty observations, fresh instance-bound API checks, heartbeat aging, HMAC generic/Slack format and bounded retry/recovery. Eleven focused cases and a real local no-notification probe pass. External receiver/whole-host outage acceptance remains open. See `OPERATIONAL-ALERTS.md` and `SECURITY-STAGE9.md`.

- [x] **9.9 Connected reporting and revenue observation.** Complete the background receipt-to-report path without relabelling simulated income.
  - [x] **9.9a Public project exchange journal.** Read-only catalog-bound project activity, exact network labels, reviewer/fill/protection links and a separate Journal block. User journals, signed commands, raw failures, keys, file paths and wallet identities are excluded. Four focused privacy/recovery cases, production build and eight labelled state views at all four responsive widths pass. No actual project financial activity was created.
  - [x] **9.9b Continuous received-fee observer.** Explicit baseline and immutable source, seven-day catchup bounds, overlap/deduplication/restart, error alerts and public redacted status. Twelve focused/31 combined receipt cases pass; default CLI inspects without networking. Actual received fees feed the 40/20/40 accounting without manual re-entry. Reward claiming and cross-chain funding remain owner operations, not silently implemented transfers.

  - [x] **9.9c Integrated handoff and verification.** Updated current setup/capability map, explicit remaining capital-routing boundary and historical-record labelling. Full backend: 511 passed; client: 69 passed; TypeScript/build and live Journal/Treasury mobile views pass. No push or financial activation.

## Stage 10 — Revised fees and strategy-author profit sharing

- [x] **10.1 Financial backend and donation removal.** Donation provider/payment code, runner/config/command and active API integration removed. Received fees allocate 60% bot / 40% team. Authenticated pre-review attribution follows approved project execution into exact closed-fill/funding settlement; 50% author liabilities reserve cash and cannot fund buybacks or new entries. Private accruals and operator-only verification of already completed source/recipient transfers are connected. Historical receipts stay readable; new donation receipts are refused.
- [x] **10.2 Revised product interface.** Donation panels removed, 60/40 bot/team fees and 50/50 user-strategy profits displayed, verified strategy submission/private earnings/payment statuses added and mechanics copy updated. TypeScript/production build, eight actual React component states and live Treasury at 320/375/414/768 pass; no donation copy or horizontal overflow.
- [x] **10.4 Bounded author payout runner.** Dedicated project source, exact earned recipients/reserves/batches, fixed mainnet USD sends, durable claims/nonces, matching source/recipient payment observations and no replay/auto-clear after timeout. Seven focused offline cases pass; default CLI makes no HTTP or financial request. Actual payments remain disabled/unobserved.
- [x] **10.3 Integrated verification/handoff.** Current policy/configuration documentation and setup/handoff updated. Full backend: 522 passed; client: 69 passed; production build passes. Actual React submission/earnings states and live Treasury checked at 320/375/414/768 without overflow; local preview retained. No push or financial activation.

## Financial policy

The owner-directed economics revision is implemented in Stage 10: received fees allocate 40% team / 60% bot; verified user-strategy net profits allocate 50% author / 50% bot. Donation execution is retired. See `STRATEGY-SHARING.md` for accounting, authorship and observed payment boundaries. Historical Stage 8–9 descriptions below/above record the superseded implementation.

- BTC only; one open position, including outstanding reservations.
- Up to 2x leverage; isolated account assumptions for the future exchange adapter.
- Planned loss at the stop including estimated execution costs <= 0.25% of equity.
- Daily loss threshold: 1% of day-start equity, including open PnL.
- Maximum drawdown: 5% from the equity high-water mark.
- Minimum notional: $10; maximum notional: 25% of equity in the initial paper policy.
- Stale or missing market data, expired proposals, invalid model output, or failed controls prevent entry.
- New paper positions include modeled taker fees/slippage and reconciled hourly funding; older positions retain an explicit unmodeled-funding label.
- Cash deposits, trading profit and hypothetical builder revenue are reported separately.


# Delivery handoff — 2026-10-17

Completed substages are committed locally on `lobster-desk`, the branch name requested by the owner. GitHub remote: `https://github.com/metamorphicc/Lobster-Desk.git`. No push, deployment, real financial order/transfer, token issuance or external message was performed. `ROADMAP.md` separates implemented software from observed external acceptance; `FEATURES.md` is the agreed product baseline.

## Run locally

Open `http://127.0.0.1:3000`. The current demonstration uses synthetic data/scripted reviews, autonomous research and the preserved `data/tryout.db`; paper positions and fees are labelled as simulations. `npm run dev` starts the default local application. For paid-model research with public market history, use `npm run setup:agents`, enter the model key in ignored `.env.agents`, then `npm run agents:check` and `npm run agents`. That preset is paper-only and uses a separate database. See `AGENT-SETUP.md`.

The tank accepts BTC pitches and can generate its own bounded trend/breakout/mean-reversion hypotheses. Code tests chronological history and stressed costs, applies critic/analyst/risk vetoes and deterministic capital limits, and records accepted, rejected and skipped decisions. Forward paper funding is reconciled hourly for tracked positions; legacy unmodeled positions retain their label. Models never run arbitrary generated code, hold wallets or enlarge risk limits.

## Implemented financial integrations

| Area | Implemented software | Activation/acceptance still needed |
| --- | --- | --- |
| Project trading | Separate opt-in mainnet/testnet runner, restricted official-SDK signing, exact loss/capital budgets, non-replayed command journal, confirmed-fill stops, independent recovery/time exits. Public Journal block reads registered project activity separately from paper performance. | Dedicated funded account/API wallet, budgets, delegation, actual exchange/restart evidence. |
| User trading | Separate Testnet/Mainnet account views and sign-in domains, immutable dedicated profiles, exact private trade previews, explicit SDK/EIP-712 consent/proof queues, owner-bound runners/journals/leases and recovery. Legacy local rehearsal stays locked. | Builder/account eligibility, separate API wallets, owner-reviewed real extension/permission/order/fill/fee/revocation acceptance. |
| Received revenue | Fixed-mainnet actual claim importer, continuous durable cursor observer, exact 60/40 bot/team allocation, flat project net-PnL reconciliation including fees/funding. Observer status appears in Treasury. | Actual fee-bearing user volume, received claims, explicit history baseline and account reconciliation. Reward claiming/capital transfers remain owner operations. |
| Buyback and burn | Bounded Solana Jupiter classic direct-route purchase, exact received lot, SPL BurnChecked, finalized transaction/balance checks, durable uncertain-state recovery. | Actual classic SPL mint and liquidity, Jupiter access, separately funded USDC/SOL treasury, reserve policy and funded acceptance. |
| Public operation | Single-host HTTPS/proxy identity boundary, standalone Docker/Caddy packaging, complete financial-journal inventory, AES-256-GCM/S3 backup transport, isolated restore, durable redacted alert outbox/runner observations. | Domain/hosting, working container runtime, cloud/receiver credentials, off-machine drill, independent review and external runtime acceptance. |

Default execution remains paper. The API never loads financial private-key maps; financial runners are separate opt-in owner processes. Neither sign-in nor viewing/downloading a plan authorizes trading. Testnet consent cannot authorize mainnet. No real wallet permission or financial command was submitted during development.

## Configuration entry points

Each command below only inspects configuration by default; it does not activate a financial runner.

```powershell
npm run agents:check
npm run execution
npm run users:execution
npm run users:execution -- --config .env.users-mainnet
npm run revenue
npm run authors:payouts
npm run treasury
```

Templates are `.env.agents.example`, `.env.execution.example`, `.env.users.example`, `.env.users-mainnet.example`, `.env.revenue.example`, `.env.author-payouts.example`, `.env.treasury.example`, `.env.server.example` and `.env.ops.example`. Actual copies, keys, databases, recovery keys and backups remain ignored. Never put a main-wallet key in an API-wallet map. Activation details and bounded financial operations are documented in `PROJECT-EXECUTION.md`, `USER-FINANCIAL.md`, `REVENUE-INGESTION.md`, `SOLANA-TREASURY.md` and `STRATEGY-SHARING.md`.

## Explicit remaining boundaries

The token network is **Solana**; mint, ticker, supply, issuance/allocation and administrative permissions are unspecified. No token has been launched. The token policy allocates 50% of eligible own-agent strategy profit after losses/costs/reserves to purchase then burn. User-strategy profits are excluded; those profits accrue 50% to the verified author and 50% to bot capital. It grants no staking/dividend/holder-payout right or price guarantee.

Actual reward claiming, allocation transfers and Hyperliquid-to-Solana bridging are **not implemented as autonomous operations**. The current financial runners require prefunded dedicated destination wallets. Principal movements must not be booked as income twice. This is a concrete remaining integration boundary, not a missing model API key. Unknown reserves prevent spending. Funding, wallet permission and token/liquidity decisions cannot be invented locally.

Funded testnet acceptance was postponed by the owner. Jurisdiction, domain and hosting remain blank. Local tests do not certify compliance, financial profitability or production readiness. `SECURITY-STAGE9.md` records developer self-review; an independent review is still outstanding. The Docker CLI validates Compose, but its Linux daemon is unavailable, so no container/runtime/HTTPS deployment is claimed.

## Recovery and checks

Stage 10 removes the donation provider/payment module, command/configuration and UI. Signed-in users can submit attributed strategies and inspect private profit shares; the mainnet project runner binds those strategies to closed fills/funding and reserves author liabilities before further entries. A separate opt-in bounded author payout process signs only earned-recipient Hyperliquid USDC sends and records payments after matching source/beneficiary observations; manual observed-transfer imports remain available when no automatic job is unresolved. See `STRATEGY-SHARING.md`.

Every new writer registers its canonical network/account/signer journal before dispatch. Recovery inventory includes all registered project/user ledgers, application, treasury and operational outbox databases; missing/mismatched journals refuse incomplete backup. Encrypted restore validates MAC/manifests before writing into a new directory. Never overwrite live nonce/command state or automatically resume an old snapshot; reconcile external state first. See `ENCRYPTED-RECOVERY.md` and `OPERATIONAL-ALERTS.md`.

Latest verification is recorded in `VERIFICATION.md`. Tests use public unfunded vectors, HTTP fixtures, an in-memory exchange and a real SPL program in LiteSVM. Real public market/account reads were verified without signing. Production metrics/revenue were not fabricated. The local browser remains available for inspection.

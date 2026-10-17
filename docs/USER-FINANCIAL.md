# Explicit user financial execution

Stage 9.3a adds an executable **testnet** path separate from the locked offline rehearsal. It does not turn sign-in, downloaded plans or `Lobster Desk Local Intent` signatures into trading authority. The new trade signature uses the distinct EIP-712 domain **Lobster Desk Execution Consent**, binding owner, exact private plan hash, dedicated API wallet, builder, fee and a short queue deadline. The saved plan binds quantity, price, direction, leverage, protections and current reviews. The existing rehearsal remains unconditionally locked.

## Separation of responsibilities

- The API uses the authenticated session only to identify the owner. Financial job creation/proof acceptance additionally requires `USER_TESTNET_FINANCIAL_ENABLED=true`; default is false. A valid new owner signature is required for each SDK permission or exact trade plan.
- SDK `approveAgent`, `approveBuilderFee` and zero-fee builder revocation jobs are immutable, owner/profile bound and share the durable serialized main-wallet nonce sequence. The SDK permissions themselves persist until revoked: the 30-second local queue deadline is not an on-chain permission expiry.
- `POST /api/v1/users/testnet/financial/jobs` prepares an idempotent job (`kind`: `agent`, `builder`, `revoke_builder`, `trade`; trade also supplies `plan_id`). `POST .../{id}/proof` verifies the exact owner signature and queues it. These routes never call `/exchange`.
- `GET /api/v1/users/testnet/financial` and `.../jobs/{id}` are private owner views. Proofs are redacted. The context reads only that owner's canonical execution journal and exposes no private keys.
- `npm run users:execution` inspects configuration without HTTP or financial dispatch. The separate process alone reads ignored `.env.users`, mapping each registered main public address to its dedicated API-wallet private key. Main-wallet private keys must never be put in that map. Public profiles are registered through the existing protected operator profile route; user/agent/builder roles cannot overlap.

## Opt-in runner

Copy `.env.users.example` to `.env.users`, register matching public profiles, configure the application's builder and `USER_TESTNET_EXECUTION_ROOT` (default `data/users-financial`). Explicit `USER_EXECUTION_ENABLED=true`, `npm run users:execution -- --run --arm` and API financial enablement are required for admission; source must be `hyperliquid-testnet`. Merely setting a model API key enables none of this. The API process never imports the key-map settings.

Each owner/agent pair has one journal and OS lease. Before entry, the inherited coded controls refresh account scope, builder eligibility/current approval, agent approval, account fees, cash-flow-neutral daily loss/drawdown references and exact user quantity/limit/expiry. Builder fees appear only on entry. Permission commands are claimed before HTTP and never automatically submitted twice. A timeout remains uncertain even if the current permission already matches: that observation cannot prove an old signed command will not arrive later. Uncertainty blocks new permissions and entries until reviewed. No automatic command reset endpoint exists.

The runner reconciles existing owned exposure before new jobs. Recovery rebuilds from the execution journal, independent of expired model reviews/previews, using a signer that **cannot enter or change leverage**. It refreshes funding/cash-flow risk references; accounting failure can trigger an owned reduce-only exit without allowing an entry. Actual fills determine stop size. Rejected/expired entries, fee revocation and uncertain commands cannot silently replay a trade. A cross-database interruption after proof claim but before staging needs inspection/fresh consent, not a second claim.

The runner remains opt-in for risk reduction after entry admission is disabled. Stopping all signer processes also stops active reconciliation; exchange-native protection remains on the exchange and must be checked by the owner. Revoking the API wallet can remove the runner's ability to close; the main wallet must then manage exposure directly.

## Verification and boundaries

Eight new focused cases cover financial-domain separation from rehearsal, idempotency/one-time claims, actual broker partial-fill protection and restart despite unavailable model review, SDK permission/revocation construction, uncertain permission no replay, expiry/owner refusal and gated authenticated HTTP proof acceptance without dispatch. All financial HTTP uses in-memory fixtures/public unfunded key vectors. No real wallet prompt, permission, funded order or builder fee collection was observed. Original 27 intent/orchestration cases still pass.

The browser signing workbench is the next substage. User-owned mainnet execution and funded acceptance remain separate open work; the autonomous project runner's mainnet support does not imply that the user testnet routes support mainnet. `.env.users` and its contents are ignored and excluded from source packaging; include all canonical journals in recovery inventory, then reconcile exchange state before resuming after a restore.

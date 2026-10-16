# User execution boundary

This is local preparation, not verified user trading. Funded acceptance is postponed. The web service has no financial-signature submission or order dispatch route. All user transport/signing flags remain false; an environment flag cannot turn them on.

## Implemented contracts

An operator can register an immutable public profile using `POST /api/v1/operator/user-testnet-profile`. It binds one user main address, a separate API wallet unique across profiles, the configured builder and its exact fee in tenths of a basis point. No private key is accepted. Profile replacement needs an explicit reconciliation/migration design; overwriting a live profile is refused.

A wallet-authenticated user can prepare SDK-compatible, **unsigned** agent/builder permissions at `POST /api/v1/users/testnet/permission-plans`. Nonces are serialized in the database. Other applications signing for the same main wallet are outside this local sequence: exchange acceptance must establish operational nonce ownership. Generated plans are not approvals, and their local display deadline cannot revoke an exchange permission.

`POST /api/v1/users/testnet/intents` takes only a private saved `plan_id`. `GET /api/v1/users/testnet/intents/{id}` requires the same authenticated owner. The EIP-712 local-intent domain is deliberately different from Hyperliquid's transaction domain. The message binds the exact immutable preview hash, owner, API wallet, builder, fee, nonce and expiry (at most 30 seconds). A sign-in signature cannot satisfy this contract.

Core-only offline verification and handoff methods test canonical EOA signatures, expiry, owner/profile/plan binding and a one-time atomic claim. A crash after claim does not permit replay. No HTTP endpoint accepts these financial proofs. Offline signatures use public unfunded test vectors only. Stored intent data is private and excluded from the public decision feed.

The existing restricted testnet broker now supports an asynchronous entry guard before staging, before leverage and again after leverage. A guard failure prevents entry. Reconciliation/protection/reduce-only recovery does not depend on that entry-only guard. Its signer can bind one configured builder/rate to order actions. Fill receipts preserve an observed `builderFee` component separately: it is already included in `fee`, so it is never added again. A missing component remains unknown. A user fill fee is **not** proof of revenue received by the project's builder wallet.

## Locked orchestration rehearsal

`users/execution.py` now connects the saved local proof/plan to a canonical per-owner/per-agent journal and the existing broker. The staged trade atomically records intent/plan/profile/proof hashes, retaining the proposal-to-fill link. The signer clamps entry quantity, worst limit, leverage and expiry to consent. Cost assumptions may tighten only. Fresh account/cash-flow history, API-agent approval, exact builder approval/rate, builder capital and explicit standard account scope are rechecked at each entry checkpoint. Missing/ambiguous state blocks entry. The user's capital references are separate from project capital. A claim and staging span separate databases: failure after claim requires inspection; another claim cannot replay it.

User protection/target/emergency orders omit the builder fee so fee-approval revocation does not add a fee-permission dependency to risk reduction. Preview round-trip fees remain conservative hypothetical upper bounds. API-agent revocation itself still needs real exchange recovery acceptance.

The gateway writer is **unconditionally locked** independently of `broker.armed`; there is no environment unlock. The offline lifecycle test explicitly substitutes an in-memory exchange and public unfunded key to exercise the user binding, actual fixture partial fills and recovery. This is not real execution. There is no user runner/financial-signature HTTP endpoint, financial wallet RPC or distributed leadership. Per-user journal files also need an explicit complete backup/restore inventory before a real multi-user service; the default backup CLI captures only the configured owner testnet ledger.

Account-scope query and builder eligibility checks follow the [official info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [account modes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes) and [builder rules](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/builder-codes), checked 2026-10-16. The adapter conservatively accepts only explicit `disabled` abstraction (standard scope); `default` and all shared-collateral modes are refused. Current protocol behavior still requires funded acceptance.

The owner-only project testnet runner remains separate. Stage 5.2d.5 remains partial until real wallet/transport/leadership/recovery integration is reviewed and accepted; 5.2d.6 remains unaccepted. See `USER-ACCEPTANCE.md` for required evidence. Do not remove the writer lock to obtain an acceptance label.

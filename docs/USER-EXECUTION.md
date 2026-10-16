# User execution boundary

This is local preparation, not verified user trading. Funded acceptance is postponed. The web service has no financial-signature submission or order dispatch route. All user transport/signing flags remain false; an environment flag cannot turn them on.

## Implemented contracts

An operator can register an immutable public profile using `POST /api/v1/operator/user-testnet-profile`. It binds one user main address, a separate API wallet unique across profiles, the configured builder and its exact fee in tenths of a basis point. No private key is accepted. Profile replacement needs an explicit reconciliation/migration design; overwriting a live profile is refused.

A wallet-authenticated user can prepare SDK-compatible, **unsigned** agent/builder permissions at `POST /api/v1/users/testnet/permission-plans`. Nonces are serialized in the database. Other applications signing for the same main wallet are outside this local sequence: exchange acceptance must establish operational nonce ownership. Generated plans are not approvals, and their local display deadline cannot revoke an exchange permission.

`POST /api/v1/users/testnet/intents` takes only a private saved `plan_id`. `GET /api/v1/users/testnet/intents/{id}` requires the same authenticated owner. The EIP-712 local-intent domain is deliberately different from Hyperliquid's transaction domain. The message binds the exact immutable preview hash, owner, API wallet, builder, fee, nonce and expiry (at most 30 seconds). A sign-in signature cannot satisfy this contract.

Core-only offline verification and handoff methods test canonical EOA signatures, expiry, owner/profile/plan binding and a one-time atomic claim. A crash after claim does not permit replay. No HTTP endpoint accepts these financial proofs. Offline signatures use public unfunded test vectors only. Stored intent data is private and excluded from the public decision feed.

The existing restricted testnet broker now supports an asynchronous entry guard before staging, before leverage and again after leverage. A guard failure prevents entry. Reconciliation/protection/reduce-only recovery does not depend on that entry-only guard. Its signer can bind one configured builder/rate to order actions. Fill receipts preserve an observed `builderFee` component separately: it is already included in `fee`, so it is never added again. A missing component remains unknown. A user fill fee is **not** proof of revenue received by the project's builder wallet.

## Intentionally unfinished integration

The user journal is not connected to a live signer, multi-user execution service or financial wallet RPC. The owner-only testnet runner remains a separate tool. Connecting them requires fresh per-user cash-flow references on every entry, unique API-wallet nonce ownership, exact private-plan limits (refresh may only tighten), verified account abstraction/margin scope, current builder eligibility and approval, per-user runner leadership, actual fee receipts and independent review. Do not reuse the project trading account's capital ledger for user accounts.

The existing broker's offline partial-fill/protection tests do not prove that this missing user orchestration exists. Stage 5.2d.5 remains partial; 5.2d.6 remains unaccepted. See `USER-ACCEPTANCE.md` for the evidence required before implementing/activating that connection.

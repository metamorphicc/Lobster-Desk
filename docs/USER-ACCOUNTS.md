# User-owned testnet accounts

The user account boundary is separate from the tank's paper account and its owner-operated testnet signer. Inspecting a public address grants no execution or authentication authority.

`GET /api/v1/users/testnet/config` exposes public builder configuration and disabled execution/collection flags. `GET /api/v1/users/testnet/accounts/{address}` reads only the fixed Hyperliquid testnet `/info` endpoint. Addresses must be nonzero 20-byte hexadecimal addresses. Each response binds to its requested address; the observation service holds no shared user balance or user signing key. Optional scoped local authentication is implemented separately below.

Responses include observed perps equity, withdrawable balance, positions, open orders, reported account taker rate and optional builder approval. Upstream errors produce an explicit service error rather than fabricated zero balances. Values retain Decimal strings. These observations do not prove that the person viewing the account owns it.

Configure `USER_TESTNET_BUILDER_ADDRESS` with a public address to inspect approvals. `USER_TESTNET_BUILDER_FEE_TENTHS_BPS=20` means 0.02% of executed notional, additional to exchange trading costs. The initial perps cap is 100 units (0.1%). The current approved maximum comes from `maxBuilderFee`; insufficient or absent approval is never treated as permission.

Approval inspection alone does not establish builder eligibility or activate collection. Builder perps capital, standard abstraction mode, explicit owner consent, per-order fee disclosure, revocation and actual fee receipts remain acceptance gates. Project trading cannot create external revenue by paying itself. Paper PnL and hypothetical fees remain separate from any eventual collected revenue.

## Wallet and watch interface

In **Testnet → Your testnet account**, choose an injected wallet and click **Connect wallet**, or enter an address in **Watch a public address**. EIP-6963 discovery never requests access automatically. The connection helper requests only `eth_requestAccounts` and `eth_chainId`, never a signature, chain change or transaction. Wallet metadata is untrusted; wallet-supplied image/SVG URLs are not rendered.

The wallet's selected EVM chain is shown separately from the data source, which is always Hyperliquid testnet. No wallet network change is needed for this public inspection. Account changes, network changes or disconnect events invalidate the session immediately and require explicit reconnection. Late provider responses cannot restore an old account. Account lookup results are bound to the requested address and session revision; switching the view clears the previous account's values.

Public watch mode does not authenticate ownership. **Disconnect view** removes listeners and local account data; site permissions in the wallet are managed separately. Views and wallet permissions are not persisted in browser storage. The interface discloses observation time and marks observations older than 15 seconds for refresh. Reported taker rates are observations rather than guaranteed final fee quotes.

Automated wallet tests use an in-memory EIP-1193 provider, including rejected requests, changes during pending requests and old responses arriving after a newer provider connected. Browser verification covered missing-wallet feedback, address validation, live public testnet account inspection and mobile layout. Actual wallet-extension authorization remains unverified in this environment; no wallet permission was granted during development.

## Cost and consent previews

After selecting an account, enter executed notional and choose **Preview costs**. `POST /api/v1/users/testnet/fee-quote` rereads the requested account, rejects stale or wrong-network observations and calculates Decimal amounts for a single taker fill. The configured builder fee is hypothetical while collection is disabled. Funding, slippage, rebates and variable final exchange fees are not promised by this illustration.

With a configured public builder recipient, **Approval plan** and **Revocation plan** call `POST /api/v1/users/testnet/consent-preview`. These are preview operations despite using POST. They do not sign anything or send an exchange request. The client cannot supply an alternative builder, fee rate, network or signing domain. Self-paid builder fees are refused.

Approval uses the configured fee cap; revocation previews `approveBuilderFee` with a zero-percent cap. Both use `hyperliquidChain=Testnet` and the official SDK's user-signed EIP-712 layout. The current preview domain is chain ID 421614, matching the SDK signing default. Future wallet signing must explicitly verify the domain, actual signer and current intent rather than trusting a downloaded JSON file. Offline tests compare both payloads with the installed official SDK, recover the expected public test key and reject changed recipient/rate/nonce/environment.

**Download unsigned plan** exports the complete plan and its hash. It is never an exchange receipt or evidence of permission. Plans have a 30-second local preview deadline to avoid presenting an old nonce as current. This metadata is **not a cryptographic action expiry**, and no durable signer nonce is reserved. A future submission path must generate and validate a fresh plan, recover the actual main-wallet signer, journal consent, serialize nonce ownership and confirm the resulting approval/revocation from the exchange. There is currently no endpoint that accepts a signed plan for submission.

The API must not infer ownership from `expected_signer`; this is application metadata outside the protocol's signed fields. Approval requires the user's main wallet, and collection additionally requires builder eligibility and per-order fee disclosure. Those external checks and actual user-order execution remain open under stage 5.2d.

## Local wallet authentication

The separate `/api/v1/users/testnet/auth` API establishes a **testnet:preview** session. Public address watching remains unauthenticated. This session proves control of an EOA key for local previews; it grants no exchange signing, transfer, fee approval, operator or account-delegation permission. Smart-contract-wallet verification (ERC-1271) is not implemented.

1. `POST /challenge` accepts only an address and generates a two-minute, single-use server message with a random nonce. Its explicit origin/URI is `http://127.0.0.1:3000`, version 1 and chain ID 421614. The EIP-4361-formatted statement explicitly excludes financial authority. Client-supplied messages, domains, chains and scopes are not accepted.
2. `POST /verify` accepts only the challenge ID and a canonical 65-byte EIP-191 signature. The server reconstructs the exact stored message, recovers the EOA address and atomically consumes the challenge. Changed fields, another signer, expiry, high-s signatures and replay are refused. Signature recovery makes no exchange/network request.
3. `GET /session` requires the returned bearer token. Tokens are random, scoped, expire in 15 minutes and are stored on the server only as SHA-256 hashes. `POST /logout` revokes the supplied session. No session becomes a trading credential.

Authentication tables share the local paper database for transactional serialization, but their payloads never appear in public paper state or journal. They are separate from capital and exchange nonces. Challenge/verify requests have an independent persisted 10-attempt/60-second peer budget, including failed proofs. Active challenge/session capacity is bounded at 256 each. Challenge creation prunes expired rows. Backward clock changes block authentication rather than extending session authority.

Every API process has a fresh authentication boot ID: restart or restoring a snapshot invalidates previous challenges and sessions, even if their rows survive. Multiple API processes cannot share sessions or provide load-balanced authentication. Plain HTTP is allowed only within the current loopback application; public hosting requires separately reviewed origin/TLS/session policy. This is not production identity infrastructure.

Offline tests use public unfunded key vectors and cover exact-message binding, concurrent replay, token storage, logout, clock rollback, restart, expiry, bounded requests and static database-failure responses. No actual wallet permission or exchange signature was requested during implementation. The funded exchange gate remains postponed by the owner.

Protocol references: [ERC-4361](https://eips.ethereum.org/EIPS/eip-4361), [MetaMask message signing](https://docs.metamask.io/wallet/how-to/sign-data/).

## Explicit sign-in interface

Only a connected wallet sees **Verify this wallet for private previews**. Watch mode cannot initiate authentication. On the canonical `http://127.0.0.1:3000` origin, select wallet chain 421614 (Arbitrum Sepolia) manually and reconnect. **Prepare sign-in message** obtains and validates a server challenge without requesting a signature. Read its full text, then choose **Sign this message** to request `personal_sign` for exactly those UTF-8 bytes. No automatic chain switch or financial-signing RPC exists.

The client validates account, origin, chain, exact statement/fields, scope and deadline before signing. It rereads the provider's selected account/chain before and after the prompt. Wallet changes, rejected or late responses and HTTP verification after a session revision change cannot become an authenticated view. Public connection still makes only the original account/chain requests.

Bearer tokens exist only in component memory, never browser storage, URLs, exports or the public account view. Sign out clears local credentials immediately and requests server revocation. Unmount/account/network changes also attempt revocation; a network failure cannot guarantee server revocation, so the server's expiry/restart checks remain authoritative. Cancelling a pending prompt discards its result locally; dismiss the wallet prompt separately.

27 Node tests cover connection, malicious challenge fields, exact signing parameters, prompt-time changes, silent provider changes and session-response scope validation. Browser checks covered missing-wallet/public-watch separation and responsive public mode; this browser has no injected wallet. Real extension prompts and the signed-in screen remain unverified outside mocked provider tests.

Sources: [builder codes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/builder-codes), [approval queries](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#check-builder-fee-approval), [official builder example](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/master/examples/basic_builder_fee.py).

## Private user order illustrations

A verified local session exposes **Preview an agent-reviewed user order**. Select an unexpired setup approved against testnet data; demo/mainnet-market reviews cannot be used. `POST /api/v1/users/testnet/order-preview` accepts only `episode_id`, a bearer session and an `Idempotency-Key`. The user address is derived from the verified session, never a request field. Public watching and an operator token do not authorize this endpoint.

The server validates the proposal/reviewer/policy binding, rereads that user's account and the fixed testnet BTC market, and checks freshness, empty positions/orders, trigger/deviation, exchange precision, stop distance, reward/risk and leverage. Decimal sizing uses that user's equity/withdrawable balance, a 0.25% per-trade loss budget, 25% equity notional ceiling, the original reviewed quantity cap and a fixed **$50** notional ceiling. It includes observed taker fees, the configured hypothetical builder rate for both legs and estimated slippage. Negative/unknown/float money observations fail closed.

These are **per-trade calculations**, not full risk approval. Daily-loss/drawdown baselines and external cash flows for user accounts are not established; exchange execution/protection and builder eligibility/receipts are unverified. The output always retains `executable=false`, `signed=false`, `submitted=false`, `nonce_reserved=false`, disabled submission/collection and explicit execution blockers. Protection templates must bind to actual confirmed fills in a future execution path. No capital, execution slot or nonce is reserved, no exchange action/envelope is built, and no order-signing RPC exists.

Private immutable records live in `user_order_plans`, separate from the public decision journal. `GET /api/v1/users/testnet/order-previews/{id}` requires a session for the same address; another address receives 404. Request IDs are scoped by verified address. Concurrent retries return one record, and conflicting inputs are refused. Cached replay makes no new exchange read, preserves the original observation/hash and may return `expired=true`. Request a new preview for fresh data. New preview attempts have their own persisted 10-per-peer/60-second bucket; reading an existing record or retrying its request ID does not refresh it or make an external call.

Plans expire locally after at most 30 seconds or the reviewed setup's expiry. This is metadata, not exchange expiry. Downloads include private balance observations; tokens/signatures are excluded. The hash covers the stored plan excluding `plan_hash`; dynamic response fields `expired` and `observation` are outside that hash. A hash does not authenticate a database against its owner. Backups capture private plans as part of the paper SQLite snapshot; retention remains an operational responsibility.

Tests cover session/owner isolation, concurrent idempotency, expired replay, logout during an upstream read, proposal tampering, stale/wrong-network data, existing exposure, trigger gaps and capital/fee bounds for long and short previews. Browser layout checks render the actual message/report React components against explicitly labelled offline fixtures; they do not prove a real wallet-to-exchange flow. Owner-postponed funded acceptance and user execution remain open.

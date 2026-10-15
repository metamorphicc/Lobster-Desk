# User-owned testnet accounts

The user account boundary is separate from the tank's paper account and its owner-operated testnet signer. Inspecting a public address grants no execution or authentication authority.

`GET /api/v1/users/testnet/config` exposes public builder configuration and disabled execution/collection flags. `GET /api/v1/users/testnet/accounts/{address}` reads only the fixed Hyperliquid testnet `/info` endpoint. Addresses must be nonzero 20-byte hexadecimal addresses. Each response binds to its requested address; no shared user balance, mutable account session or user signing key exists in the service.

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

Sources: [builder codes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/builder-codes), [approval queries](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#check-builder-fee-approval), [official builder example](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/master/examples/basic_builder_fee.py).

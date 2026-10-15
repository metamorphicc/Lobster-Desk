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

Sources: [builder codes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/builder-codes), [approval queries](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#check-builder-fee-approval), [official builder example](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/master/examples/basic_builder_fee.py).

# Explicit execution networks

The execution core now supports explicit testnet and mainnet network identities. A public data source never selects or activates a financial writer. Default FastAPI runtime and `npm run agents` still execute paper trades; the separate project runner is tracked in Stage 9.2.

`HyperliquidMainnet` fixes requests to `https://api.hyperliquid.xyz`; the original testnet class fixes requests to its testnet host. Neither follows redirects or accepts a user-supplied endpoint. Mainnet signatures use the SDK's mainnet domain; testnet signatures retain their original domain. Both signers restrict actions to bounded BTC orders, isolated leverage and owned cancellation, with no transfer/withdrawal action.

Reviewed setup, account observation, signer, gateway and persisted journal must all have the same network. Reopening a journal under another network/account/signer is refused. Order identifiers include the network. The existing lifecycle continues to protect actual partial-fill exposure, reconcile uncertain writes without re-entry and reduce owned risk after a stop failure.

Tests use HTTP interception, an in-memory exchange and public unfunded vectors, including the mainnet domain. No mainnet/testnet order was sent. Actual exchange acceptance remains separate from these software checks.

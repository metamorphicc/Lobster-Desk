# Charity provider, recipients and payment flow

The owner authorized selecting a provider/recipients. The prepared integration uses **The Giving Block** with two curated causes: **Save the Children** (children's health, safety and education; EIN 06-0726487) and **Best Friends Animal Society** (shelters/homeless animals; EIN 23-7147797). These are selected defaults, not claims of endorsement or a partnership. API organization IDs and payment addresses are discovered from the authenticated provider directory; no organization ID or address is guessed. The directory is matched by independently sourced EIN, then rechecked against the organization's live provider details. The default recurring process balances cumulative gross donations equally between these two causes; this subdivision is configurable code policy, separate from the agreed 40% charity fee allocation.

The project's token remains on Solana. This donation adapter supports **USDC (ERC-20) on Ethereum**, only when the selected organization's currency API explicitly returns that network/token standard. Seeing the symbol USDC or SOL elsewhere is not sufficient. Unsupported network/minimum/anonymous-donor rules fail closed. The adapter never declares donor legal affirmations on the owner's behalf. Provider-required donor data/affirmations or account-specific restrictions require the actual account's supported flow.

## Setup and operation

`npm run charity` prints configuration/candidate recipients without HTTP or payments. Copy `.env.charity.example` to ignored `.env.charity`; obtain real partner API credentials from The Giving Block and configure a dedicated funded Ethereum treasury wallet, USDC reserves and gas ceilings. Partner access is an external prerequisite; the code cannot generate credentials. The API login/access token stays in process memory; browser APIs never receive it. An expired token stops the current operation and the next invocation can log in again. There is no blind retry of provider mutations.

Commands run from the root:

```powershell
npm run charity -- --directory
npm run charity -- --prepare 25 --recipient children
npm run charity -- --dispatch PAYMENT_ID --arm
npm run charity -- --reconcile PAYMENT_ID
npm run charity -- --status
```

`--prepare` checks live recipient/EIN/network/minimum, reserves and unspent charity earmarks, claims the local job durably, then creates a provider donation pledge/address. It creates **no transfer**. Ambiguous provider creation persists `pledge_unknown`; restart cannot silently create another pledge. `--cancel PAYMENT_ID` can abandon a demonstrably unsigned job under the process lease. Never abandon/recreate a signed uncertain transfer.

`--dispatch` additionally requires `CHARITY_ENABLED=true`, matching dedicated signer and explicit `--arm`. It constructs only a fixed Ethereum-chain-1 native-USDC `transfer(address,uint256)`; no token approval, arbitrary contract call or native-ETH value transfer is allowed. Fresh provider recipient checks, actual USDC balance, pending/latest nonce agreement and native gas/reserve caps precede signing. Signed raw bytes/hash and the sending claim commit before RPC submission. Unknown transactions are reconciled by hash without signing another nonce or resubmission.

The immutable charity book identity binds wallet, chain, USDC contract and provider host. The finalized receipt must be in a block at/below the observed finalized head with matching canonical block hash; sender, destination contract, input, nonce, gas bounds and exact USDC Transfer log must match the signed pledge payment. The charity debit and finalized payment state commit together. A restart or provider retry cannot debit it twice.

`npm run charity -- --run --arm` is an optional owner process, checking once per minute. It reconciles existing jobs first, alternates causes by cumulative finalized gross amounts and prepares a default 25-USDC batch only when reserves/earmarks/provider minimum permit. This avoids a separate transaction for every trade. It does not guarantee low fees: actual Ethereum gas must fit the configured ceilings. Provider costs are not guessed.

## Gross payment versus nonprofit receipt

Finalized USDC sent to the provider-assigned address is shown separately from the authenticated provider transaction record and any reported net payout amount/currency. Actual net proceeds can be lower after provider fees/conversion. A promise, pledge or local charity earmark is never a completed transfer; gross transfer is not a claim of final nonprofit bank payout. Provider record polling uses authenticated server API pages and compares transaction hash, organization ID, currency and amount. No untrusted webhook can mark a donation complete: the documented AES-CBC payload encryption alone does not provide message authentication. No public webhook settlement endpoint is implemented.

`/api/v1/economics` includes a redacted `charity` directory/payment summary; signed bytes, private keys, donor details and provider credentials are excluded. This does not make the legacy treasury book independently authenticated. Fixed RPC observations still rely on the RPC provider. No actual provider account, pledge, donation or transaction was used during development.

## Funding and remaining external prerequisites

The actual charity wallet needs Ethereum USDC and ETH gas. Hyperliquid proceeds and Solana balances are not automatically bridged here; cross-network principal must be recorded once, not relabeled as new revenue. Public RPC outages, absent partner credentials, an unsupported organization/network, missing reserves or insufficient funds stop payment. Native gas costs need an explicit USDC valuation/expense reconciliation policy before claiming project net profit.

Verified offline: 10 focused scenarios cover authenticated directory discovery, exact pledge/payment, finality/provider acknowledgment, restart, uncertain transaction and pledge recovery, wrong EIN/network/chain, missing authority/earmarks, forged logs and redacted public output. Financial/provider HTTP calls are in-memory fixtures.

Sources checked 2026-10-17: [Save the Children EIN](https://www.savethechildren.org/us/ways-to-help/ways-to-give/donor-advised-funds), [their crypto donation flow](https://support.savethechildren.org/site/SPageNavigator/donation__crypto), [Best Friends EIN](https://bestfriends.org/contact-us), [Best Friends provider page](https://thegivingblock.com/donate/best-friends-animal-society/), [provider onboarding](https://docs.thegivingblock.com/docs/getting-started), [crypto flow/network disclosure](https://docs.thegivingblock.com/docs/crypto-donation-flow), [provider currencies](https://docs.thegivingblock.com/reference/post_v2-currencies-list-1), [pledge creation](https://docs.thegivingblock.com/reference/post_v1-deposit-address-1), [transaction records](https://docs.thegivingblock.com/reference/post_v1-transaction-list-1), [webhook security scheme](https://docs.thegivingblock.com/docs/webhook-notifications), [Circle's USDC addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses), [fixed Ethereum RPC provider](https://ethereum.publicnode.com/).

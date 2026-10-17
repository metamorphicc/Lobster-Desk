# Strategy authorship and profit sharing

The total entry fee remains 0.05%: **0.02% team / 0.03% bot capital**. For project trades following an authenticated user's strategy, **50% of eligible net realized strategy profit accrues to that author and 50% remains with the bot**. Donations are removed.

## Submission and ownership

Sign in under Mainnet or Testnet, then use **Your strategies and profit share**. `POST /api/v1/users/{network}/strategy-pitches` accepts the standard BTC pitch and an `Idempotency-Key`. The server derives ownership from the network-scoped authenticated session; callers cannot supply another wallet or claim old anonymous history. The identity/owner commitment, network and exact pitch hash are bound before review. Actual ownership stays in a private application table; public episodes expose commitments rather than wallet addresses.

The project runner admits approved attributed strategies alongside its own research, through the same deterministic reviews/risk/banker controls. User-owned account execution is a separate product path: this profit share concerns trades funded by the **project**. Mainnet attributed execution requires `PROJECT_TREASURY_PATH` pointing to the same book as API `TREASURY_PATH`. Paper/testnet trading never accrues a real payable balance. Historical anonymous trades are not relabelled as attributed.

## Settlement and reserves

Only flat mainnet project checkpoints with terminal owned trades and complete cash-flow/funding observations can settle. The importer reconciles cumulative account performance to all owned fills. Each attributed closed trade additionally binds confirmed fills/fees and funding to its original strategy owner. Funding that cannot be assigned to exactly one owned trading interval refuses attribution rather than being guessed.

Every execution has a unique allocation identity. Duplicate observations/restarts cannot allocate it twice; changed settled fills/attribution refuse further settlement. Strategy metadata does not credit cash a second time. A zero-value `strategy_checkpoint` records liabilities when an account's gains/losses offset; it is not revenue.

For each strategy, accumulate realized net profit including losses, then round down half of its positive balance to micro-USDC. Sum an author's entitlements and subtract all previously observed payments. Later losses reduce new entitlement; past payments are never silently clawed back or reissued. Direct trading fees and funding are included once; project operating expenses remain separate costs/reserves. These are conservative local accounting rules, not a guarantee of returns.

Outstanding author and team liabilities are removed from available project entry capital and own-agent buyback cash. Prior closed trades settle before another mainnet entry is admitted. Failure of the treasury/reference path blocks new entry; recovery of already owned exposure remains independent. The existing own-agent token policy excludes user-strategy profits and author liabilities.

## Balances and payment receipts

`GET /api/v1/users/{network}/strategy-earnings` returns that wallet's strategy records and earned/paid/outstanding mainnet balance. Treasury publishes aggregates without author wallet identities. Accrued balances are not completed payments.

Payouts support a **separate opt-in owner-run process** or an owner-executed Hyperliquid internal USDC transfer followed by protected receipt verification. There is no public transfer endpoint. An operator calls `POST /api/v1/operator/strategy-payout-receipt` with `journal_id`, `owner`, `transfer_hash`, `timestamp_ms` and exact USDC `amount`. The source must be a registered mainnet project journal. Fixed mainnet account-history reads must show one matching source debit and beneficiary credit, same hash/time, exact amount and supported zero-fee internal-transfer type. Unavailable, ambiguous, mismatched, over-entitlement and duplicate/conflicting receipts fail closed. The API submits no transfer.

The receipt atomically reduces cash and the author's outstanding balance. Its identity prevents recording one transfer twice or applying it to another author. Observations retain the existing `owner_supplied_unverified` provenance; fixed-host reads are not independent cryptographic finality. Financial activation/funded acceptance remains outstanding. Never put a main-wallet key in an API-wallet map or erase historical receipts to change an allocation.

## Automatic payout runner

Copy `.env.author-payouts.example` to ignored `.env.author-payouts`. Configure the dedicated **project main account** and its transfer-capable key, shared treasury book and explicit operating/liability/tax reserves. This must not be a user's wallet/key or a substituted trading API key. The API never reads this settings file. Keep the funded project account bounded and use the configured source key exclusively for this runner's USDC sends while it is enabled.

`npm run authors:payouts` only inspects configuration without HTTP. Explicit `AUTHOR_PAYOUT_ENABLED=true` and `npm run authors:payouts -- --run --arm` enable the separate process. Default batches are at most 25 USDC, with a hard 100 USDC configuration ceiling. Unpaid balances below one cent accumulate. The receiver is selected only from verified earned author balances, never supplied as an arbitrary transfer request.

Each payout requires fresh flat standard-account observations, exact entitlement and recorded cash, protects other authors/team and configured reserves, and checks that account data includes prior recorded payouts. New entries already reserve author liabilities. A durable immutable mainnet/source/action/nonce job and exact signed body commit before HTTP. Only the narrow human-readable [Hyperliquid Core USDC transfer action](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint#core-usdc-transfer) is constructed; there is no withdrawal/bridge/arbitrary-action method.

After an acknowledged send, matching source debit and recipient credit must be observed before the book marks payment recorded. API acknowledgment alone is not a completed payment. A timeout/crash remains uncertain, blocks a new payout, and is never automatically resent or cleared from a matching balance/history alone. Manual receipt import is blocked while an automatic job is unresolved. Queue deadlines cancel only unsigned prepared jobs; they are not on-chain expiry for an already signed transfer. Reconcile external state before any manual recovery, and never reset a nonce journal from an old snapshot.

The operations monitor observes uncertain payout jobs/heartbeats with redacted alerts; encrypted treasury recovery includes all payout jobs/nonces. Private earnings expose only the author's recent payment statuses, not signed envelopes or other authors. Seven offline payment cases verify exact SDK-domain recovery, batch/entitlement/reserve bounds, flat-source checks, expiry, unknown-send restart without replay, observed source/recipient settlement and wrong-key/unarmed refusal. No actual payment or funded exchange acceptance was performed.

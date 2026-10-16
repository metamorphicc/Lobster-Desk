# Economics: accounting before token decisions

Token role, rights, network/contract, jurisdiction and distribution parameters remain **undecided**, as requested by the owner. No token contract, staking entitlement, profit share, issuance, treasury transfer or revenue promise is enabled. A tentative US audience is not a legal/product specification. This document defines local accounting, not legal or tax advice.

## What is revenue

Only builder proceeds actually received by the project belong in `builder_receipt`. A user's fill fee, configured percentage, hypothetical volume estimate or unclaimed/estimated builder balance is not received project cash. The builder component of a fill is already included in its fee; do not subtract/add it a second time.

Project trading settlements are recorded separately as `trading_profit`/`trading_loss`, net of fees and funding **once**, reconciled to closed project trades and actual treasury cash. These rows represent a settled net increment/decrement, not gross returned trading principal. Principal remains `capital_in`/`capital_out`. Do not also book a full withdrawal containing the same profit as new revenue. User equity, unrealized PnL, token sales and external capital injections are never trading earnings in this book.

`expense` covers settled project costs (models, infrastructure and other approved costs). `refund` reverses previously recognized revenue. A booked `buyback_spend` reduces both cash and remaining earned funds, but not operating profit a second time. All amounts are positive USDC strings with at most six decimals; the row kind determines direction. USDC units are not a guarantee of USD market value.

## Local book and provisional waterfall

`TreasuryBook` is an independent SQLite receipt book, with no simulated starting balance. It has immutable append APIs, atomic duplicate/conflict checks and a hash chain. Each receipt reference is unique; a conflicting retry is refused. Negative recorded cash is refused until missing funding/history is reconciled. Backfill in actual settlement order. Offline fixtures and owner-supplied observations require separate books.

The receipt reference and evidence hash are **owner supplied**, not authenticated exchange/on-chain receipts. The book detects accidental alteration; an administrator can rewrite an entire chain. Preserve independent head hashes/backups and reconcile externally. No import endpoint is exposed to public users.

The calculation proceeds in this order:

1. Received builder proceeds plus net realized trading gains, minus trading losses, paid operating expenses and revenue refunds.
2. Carry forward an unrecovered deficit. A later capital injection does not erase it or generate buyback capacity.
3. Subtract buybacks already spent from cumulative earned funds.
4. Reserve operating cash, specified liabilities and a provisional tax reserve on positive net recorded earnings.
5. Bound the remaining allocation by both unspent earnings and cash above reserves; apply the chosen buyback fraction and round down to six decimals.

`release/economic-policy.json` leaves all reserve, tax and allocation parameters unset. Therefore `provisional_buyback_allocation=null` and transfers stay disabled. Configured values are only an offline planning scenario; they are not a tax rate recommendation or authority to spend. No default percentage/holder payout is invented. Before activation, a reviewed policy must also address accounting periods, losses after earlier distributions, refunds, taxes already paid, segregation of capital, treasury authority and independent receipt verification.

```powershell
node scripts/python.mjs scripts/treasury-report.py --output artifacts/economics/empty-book.json
```

Use `--append path/to/private-entry.json` only for an owner-supplied entry matching `TreasuryEntry` (id, receipt_ref, evidence_sha256, kind, amount, currency, occurred_at with timezone, provenance). `--book` selects a separate file. Reports do not publish entry bodies, addresses or evidence files. Keep the underlying receipt book private; reviewing a hash is not reviewing a transaction. If output fails after a successful append, retry the **same** entry identity: it is idempotent. Never delete a receipt to hide a loss; a correction workflow requires explicit design/reconciliation.

## Decisions required before any token implementation

| Decision | Current value | Why it remains open |
| --- | --- | --- |
| Operating entity/jurisdiction and eligible users | Unspecified | Platform access, applicable obligations, disclosures and operating model need review. |
| Token role/rights | Undecided | Utility, governance, staking, revenue rights and absence of rights are different products; none is inferred. |
| Network, standard, supply, allocations and authority | Unspecified | No chain/contract or mint/burn/admin design can be selected responsibly from the current brief. |
| Expense, reserve, tax/liability and allocation policy | Unspecified | Requires actual cash economics and owner/adviser decisions. |
| Buyback approval, execution and custody | Disabled | Needs a reviewed mandate, supported venue, treasury controls and independent reconciliation. |
| Holder payouts/staking/backing | Disabled, no entitlement | No implementation or marketing claim until explicitly designed and reviewed. |

The project can potentially earn a builder fee from eligible user fills only after actual approval, execution and receipt acceptance. Profitability depends on received fees minus operating costs and losses; neither this calculation nor a paper strategy establishes that it will earn money. Token operations remain a separate later decision.

# Agreed fee and profit policy

Builder fee: **0.05% of executed entry notional** (50 tenths of a basis point), additional to exchange costs. Existing immutable consent/profile records are not migrated or silently reapproved. A user with a lower approval must explicitly approve the new rate before a future live implementation could charge it. Exits/protection remain fee-free in the user adapter.

Received builder fees, net of refunds, are earmarked 40% for agent capital, 20% for the team and 40% for charity. USDC rounding dust remains with agent capital. Team revenue is before operating costs. Charity destinations are not selected; an earmark is not a completed donation.

50% of positive **cumulative net realized agent trading profit after expenses and recovery of prior losses** is earmarked for token buybacks, followed by burning. Capital deposits and builder receipts never count as trading profit. All previous buyback spending is subtracted from the cumulative entitlement before calculating a new budget; rereading or restarting cannot repeatedly allocate half the same profit. Later losses can suppress new allocations until recovered.

Unpaid charity/team earmarks and operating/liability/tax reserves are excluded from the cash available to buy back tokens. Unknown reserves produce a null spendable budget. There is no holder dividend, staking entitlement, price floor or guarantee of appreciation.

`scripts/distribution-report.py` reads the independent receipt book. `charity_payout` and `team_payout` are owner-supplied spending observations, not payment commands. Legacy `treasury-report.py` remains a generic historical policy rehearsal; use the distribution report for this agreed policy.

```powershell
node scripts/python.mjs scripts/distribution-report.py --output artifacts/economics/distribution-new.json
```

No fee collection, transfer, donation, purchase or burn is performed. Token network/contract, recipients and actual chain evidence remain external configuration. The existing buyback report links purchases and disposal observations; a sink transfer is distinguished from verified total-supply reduction and owner-supplied claims are never automatically certified.

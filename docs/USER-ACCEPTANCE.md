# User wallet and exchange acceptance

Status: **not performed**. The owner postponed funded testnet acceptance. No real exchange writes or real financial wallet signatures were used in implementation. First finish the user orchestration listed in `USER-EXECUTION.md`; do not run an unimplemented user flow by adapting the project runner ad hoc.

Create a private checklist (no network calls):

```powershell
node scripts/python.mjs scripts/user-acceptance.py template --output artifacts/user-acceptance/record.json
node scripts/python.mjs scripts/user-acceptance.py inventory --record artifacts/user-acceptance/record.json --output artifacts/user-acceptance/inventory.json
```

Paths are relative to the record's directory. Files are bounded, hashed and never overwritten. Supported files include JSON receipts and wallet screenshots. Keep screenshots, addresses and signatures private; inspect file contents yourself. Extension allowlisting does not prove a file contains no secret. Hashes establish neither exchange authenticity nor successful acceptance. Even every case marked `observed` leaves `acceptance_verified=false` and `execution_authorized=false`.

| Case | Required owner-reviewed evidence |
| --- | --- |
| Wallet message review | Actual extension identity, exact origin, chain, local-intent contents and separately labelled Hyperliquid approvals. Reject unknown/blind signing. |
| Rejection/account changes | Reject each prompt; change account/network during pending signing and delayed HTTP. No stale proof/session/order survives. |
| Session replay | Single-use sign-in, logout, expiry and server restart invalidate prior access; no wallet ownership inferred from a public lookup. |
| API agent | A unique API wallet per user, matching approval and expiry. Owner main keys never reach the service. Verify revocation and exclusive nonce/runner ownership. |
| Builder | Current eligibility, correct independent builder address, fee denomination and exact approved rate. Verify approval readback, revocation and refusal of new fee-bearing entries afterward. |
| Private plan to entry | Bind user, plan hash, nonce, current risk/cash-flow references, maximum quantity/price/fee and expiry to the actual order and fill. No renewed or enlarged trade under old consent. |
| Partial fill/native stop | Actual partial IOC fill, confirmed protection of actual size, trigger execution and clean flat reconciliation. A staged TP/SL template or HTTP acknowledgment is insufficient. |
| Restart/timeout | Kill the owner runner around an uncertain write, restart with the same journal and reconcile by identity without replay. Concurrent runners/users cannot share nonce state. |
| Accounting | Deposits, withdrawals, fees, funding, day rollover and drawdown limits reconcile conservatively; unavailable/truncated history blocks entry. |
| Revenue | User fill's builder component is included in total fee. Independently verify actual builder receipts/claimable amount and eventual receipt; do not count hypothetical volume × rate as cash. |
| Revocation and recovery | Entry permission loss must not disable owned protection or reduce-only recovery; review the protocol's actual behavior if the API wallet itself is revoked. |
| Completion | Exact entry/exit attribution, final flat account, no owned leftover orders, no unrelated order/position modified. |

Use exchange-native stop/target evidence over time, not only a final snapshot. Account abstraction/margin mode and the perps account's capital scope must be explicitly supported. Replay tests and malformed-message tests use local fixtures first. Record failed/unavailable cases honestly; do not obtain an acceptance label by checking boxes. Stage 5 remains open until integration, actual exchange observations and owner review are complete. Production has additional gates in `RELEASE.md`.

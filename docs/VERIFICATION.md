# Verification record

Date: 2026-10-16 (Asia/Novosibirsk).

## Automated

- 261 passing Python tests: schema validation, finite monetary input, direction/stop/target checks, leverage, expiry/freshness, sizing, loss thresholds, concurrent reservation, fill idempotency, transaction rollback, gap losses, fee accounting, provider failure, review budgets, feed isolation, HTTP endpoints and restart recovery. Testnet additions cover official SDK signatures/domain/expiry, atomic nonce/command claims, partial fills, uncertain requests without replay, protection failure, fixed-host HTTP, public-only readiness/preflight and operator-controlled local staging/cancellation.
- End-to-end API scenario: pitch -> reviews -> capital reservation -> paper fill -> stop -> restart -> identical cash and journal.
- TypeScript check passes.
- Next.js production build passes.
- Python dependency versions captured in `apps/api/requirements.lock`; npm dependency tree captured in root `package-lock.json`.

The installed Starlette test client emits one upstream deprecation warning about its httpx compatibility path. Tests pass; this does not affect the application's HTTP client or paper broker.

## Browser

Stage 5 updates: 155 Python tests and 11 Node wallet-session tests pass, alongside TypeScript and the production build. User-account tests cover separate balances, address validation, exact fee units, malformed approval data and static upstream errors. Consent tests verify Decimal cost illustrations, official SDK-compatible unsigned approval/revocation payloads, domain/recipient/rate/nonce binding and lack of any submission route.

The wallet/account interface passed public testnet lookup, validation, stale-observation feedback and 320/375/414/768/1280px layout checks. With a temporary public sample builder address supplied only to the development process, browser fee preview for $50 notional returned $0.022500 estimated exchange fee, $0.010000 hypothetical builder fee and $0.032500 total if applied. Approval and zero-rate revocation plans rendered; the downloaded unsigned approval JSON was parsed and its hash verified. No wallet authorization, signature, approval or exchange order was submitted. Real injected-wallet behavior and funded user trading remain unverified.

- Actual local browser interaction: submit a sample pitch, observe review and capital reservation, submit an invalid-stop pitch and observe rejection.
- The sample entry subsequently filled. Restarting the actual local services preserved the open position and cash; the browser displayed its fill price, quantity and fees without creating a duplicate position.
- Form validation produces actionable field messages.
- Treasury calculator: $10 million executed volume at 0.02% -> $2,000 hypothetical gross revenue. Actual collected builder fees remain zero.
- Journal export downloaded and parsed successfully.
- Responsive dimensions checked at 320, 375, 414, 768 and 1280 CSS pixels. Navigation fits; root has no horizontal overflow. Native dialog remains scrollable on small screens.
- Fixed global table styles leaking into the chart's internal tables and chart price-line cleanup after component disposal.
- Computed foreground/background contrast check passed for rendered text on the tank screen; decorative scene lettering is excluded from content semantics.
- Testnet tab: anonymous read-only readiness returned testnet BTC data while missing account/funding/agent approval remained incomplete. Preview correctly refused staging; no private key field or HTTP execution control exists. Responsive checks at 320, 375, 414, 768 and 1280 pixels found no horizontal overflow or out-of-bounds controls. Switching back to the chart produced no browser console errors.

## External integration

The read-only Hyperliquid smoke check succeeded and returned BTC market context plus 90 one-minute candles. No keys or orders were used. Unit tests use mocked exchange responses and do not depend on network availability.

Anonymous testnet CLI inspection succeeded against `api.hyperliquid-testnet.xyz`, returning BTC metadata and a current price. It submitted only an unsigned `/info` request. No owner account or API wallet was configured for this check.

The Anthropic adapter's request/output contract is tested with mocked responses. Actual paid inference has not been verified because no provider credentials were supplied. Signing is verified offline with a public, unfunded test key. No signed request, exchange order, wallet approval, deposit or funded acceptance test was performed. PostgreSQL, multi-host signing and actual exchange protection remain unverified. Stage 5.1d stays open.

## Local recovery

163 Python tests pass after adding SQLite snapshot/restore coverage. A real stopped-service paper snapshot was created at `artifacts/backups/20261015T225041-fbde6e34/manifest.json`, verified and restored to `artifacts/restore-drills/20261015-local-paper/`. Account, episode, position and event rows matched the original database exactly. Tests also preserved an uncertain testnet entry command and its durable nonce across an isolated restore without replaying entry. These are local/offline results; no restored signer was activated against the exchange.

## Local API security

At the boundary-review substage, 172 Python tests and 11 Node wallet tests passed. Nine boundary tests cover Host/Origin, declared and chunked bodies, slow reads, duplicate/oversized Content-Length, malformed bearer bytes, credential-error redaction and valid CORS/POST behavior. Live Next proxy and browser cost-preview checks passed after the middleware changes. The production build passes. Subsequent strict advisory checks covered all 56 Python lock entries without skips and the npm production tree, reporting zero known vulnerabilities; installed Python versions matched and pip check passed. Independent review remains incomplete. See [SECURITY-REVIEW.md](SECURITY-REVIEW.md) and [DEPENDENCY-AUDIT.md](DEPENDENCY-AUDIT.md) for findings, input hashes and remaining launch gates.

## Local operations

195 Python tests and 11 wallet tests pass. Readiness tests cover actual local worker ticks, failed tasks, stale/future/wrong-source data, database failure, review budgets, non-mutating diagnostics and unresolved testnet state. The CLI rejects malformed/inconsistent reports; a critical testnet alert returns exit 1 even when the independent paper runtime is ready.

Actual local checks returned exit 0 for the healthy service through both API and Next proxy, exit 1 with WORKER_ENABLED=false, and exit 2 with services stopped. The browser showed READY and all seven checks passing with workers enabled; disabling them showed NEEDS ATTENTION and the critical stale-protection alert for the existing paper position. The panel passed 320/375/414/768/1280px layout checks without horizontal overflow or console errors. No external alerts were sent or scheduled.

## Durable pitch admission

207 Python tests pass. Concurrent requests through four independent Store instances admitted exactly ten attempts for one peer; concurrent submissions admitted twenty pending episodes without duplicate submission events. Tests cover persisted limits after API restart, accurate sliding expiry/Retry-After, backward-clock behavior, bounded peer state, ignored forwarded headers, static 503 on database failure, corrupt-state refusal and snapshot restoration of active windows. A concurrent UTC review-budget test permits exactly one call across four stores when the daily budget is one. PostgreSQL and distributed service identity remain unverified.

## Local worker ownership

215 Python tests pass. An independent child process acquired the worker lock, a competing process was refused, and terminating the actual owning interpreter released the OS lock without deleting its file. The test targets the reported interpreter PID because a Windows virtual-environment launcher can be a separate process. Tests also cover canonical path aliases, separate databases, observer APIs, clean task cancellation, startup/lifespan exceptions and refusal of unimplemented database leadership modes.

A real default local API returned ready while a second Uvicorn process on another port refused startup for the same paper database. Stopping the original API released ownership; the lock could be acquired again. No signer or exchange execution was activated. This establishes same-machine Windows behavior; POSIX locking uses flock but was not exercised on this host.

## Local wallet authentication

230 Python tests pass. Public unfunded EOA vectors verify exact domain/chain/nonce/statement binding, canonical signature recovery, single-use challenges, concurrent replay, hashed bearer storage, logout, restart, expiry and backward-clock refusal. Authentication makes no exchange call and exposes no order submission route. Tests confirm static failure responses and that tokens/signatures never appear in public paper state. Actual wallet-extension signing and financial permissions remain unverified.

## Explicit wallet sign-in interface

27 Node wallet tests pass; TypeScript and production build pass. The client checks the complete sign-in message before any personal_sign call, verifies provider account/network before and after the prompt, discards changed sessions and validates returned session scope. Browser verification at 320/375/414/768/1280px confirmed public watching never exposes a sign-in action or private session, with no horizontal overflow or console errors. No injected wallet is available in this browser; actual wallet prompts and signed-in UI remain unverified outside the mocked-provider contract.

## Private user order illustrations

249 Python tests and 27 Node tests pass; production build/typecheck pass. Private-preview coverage includes owner/session isolation, concurrent idempotency across stores, original-hash retention after expired replay, session revocation during an upstream read, tampered reviews, stale/wrong-network data, occupied accounts, trigger gaps, finite exact money and independent user capital. Long/short calculations enforce risk, notional, cash and fee bounds, including a 27-combination short-account/fee sweep. No actual order, reservation, nonce or native stop is created.

An actual local Next proxy/API smoke check with a public unfunded signing vector confirmed challenge -> scoped session -> replay refusal -> logout, no-store headers and denial of unauthenticated private-preview access. It made no exchange call and used no injected wallet. Actual SignInMessage and UserOrderReport React components were server-rendered into an explicitly labelled offline fixture; normal/expired reports and message layouts passed 320/375/414/768/1280px overflow/button checks and visual inspection. This is layout evidence, not live wallet/exchange acceptance. Temporary services were stopped after verification.

## User capital references

261 Python tests pass after private observation-based capital tracking. The suite verifies deposit-neutral performance, no duplicate funding, cash-flow bounds, daily-window rollover, latched drawdown, receipt deduplication, account isolation, restart, rollback on late/conflicting history, bounded inclusive pagination and authenticated routes. Gateway JSON parses decimal numbers directly into Decimal. References start at an observed point and preserve unknown earlier history; ambiguous receipt fee semantics require review. Production build and 27 wallet tests pass. See USER-CAPITAL.md for supported schemas and limits.

## Financial interpretation

These checks establish local software behavior, not a trading edge or sustainable business economics. Paper fills assume full execution, modeled adverse slippage and taker fees; they do not model funding, order-book queue priority, partial fills or exchange outages faithfully. Performance figures must retain the paper label.

## Remaining-stage local delivery — 2026-10-16

The final suite covers local consent/profile permissions, serialized nonces, exact-plan typed signatures, expiry/changed-owner/fee/agent refusal, concurrent single-use handoff and global main/API/builder role separation. User orchestration uses canonical separate journals and atomically binds the private plan/proof to the staged trade. Its writer remains locked even if the broker is accidentally armed. An explicitly substituted in-memory exchange exercises partial fills, actual-size stop protection, entry-only builder fees and recovery independently of an unavailable entry guard. Revocation after the leverage roundtrip prevents entry. This is offline fixture evidence, not funded acceptance or real extension signing.

Evidence-inventory tests check complete case sets, path containment, file bounds and hashes; all observations remain unverified. Release tests check clean committed-source packaging, forbidden runtime/key paths and permanently local-only configuration. Pilot tests cover unset budgets, complete/fresh references, cash-flow-neutral daily/drawdown limits and recovery blockers. Economics tests cover exact USDC, atomic duplicate/conflict handling, capital/revenue separation, loss carry-forward, reserve/tax/allocation bounds, hash-chain corruption, purchase/spend linkage, asset/network isolation and excess-disposal refusal. Treasury-only isolated restore preserves receipt links and duplicate protection. Sink transfers never count as supply reductions, and no report certifies a burn or grants transfer authority.

A real local snapshot of the paper database and empty treasury book was verified and restored into a new directory without replacing live files. Acceptance templates/inventories and unconfigured pilot/treasury/buyback reports were generated under ignored `artifacts/`, retaining null/disabled/unverified fields. A local source package was generated from a clean committed tree; the final handoff revision is packaged separately after documentation. No external backup, deployment, notification, real order, transfer or token operation occurred.

During repeated full-suite runs, Windows once refused a fresh asyncio socketpair with WinError 10055 (356 tests passed, one fixture setup error). The shared execution fixture now reviews its four steps in one asyncio lifecycle and disposes its database engines, reducing TCP socket churn and open resources. The final successful run is reported below; the failed run was not treated as a pass. The upstream Starlette/httpx test-client deprecation warning remains unrelated to financial behavior.

Final checks: **357 Python tests passed**, **27 Node wallet tests passed**, TypeScript passed and the web production build passed. Git whitespace checks passed. These counts supersede earlier historical checkpoint counts in this document. No dependency lock changed after the recorded advisory audit.


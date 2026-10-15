# Verification record

Date: 2026-10-16 (Asia/Novosibirsk).

## Automated

- 60 passing Python tests: schema validation, finite monetary input, direction/stop/target checks, leverage, expiry/freshness, sizing, loss thresholds, concurrent reservation, fill idempotency, transaction rollback, gap losses, fee accounting, provider failure, review budgets, feed isolation, HTTP endpoints and restart recovery.
- End-to-end API scenario: pitch -> reviews -> capital reservation -> paper fill -> stop -> restart -> identical cash and journal.
- TypeScript check passes.
- Next.js production build passes.
- Python dependency versions captured in `apps/api/requirements.lock`; npm dependency tree captured in root `package-lock.json`.

The installed Starlette test client emits one upstream deprecation warning about its httpx compatibility path. Tests pass; this does not affect the application's HTTP client or paper broker.

## Browser

- Actual local browser interaction: submit a sample pitch, observe review and capital reservation, submit an invalid-stop pitch and observe rejection.
- The sample entry subsequently filled. Restarting the actual local services preserved the open position and cash; the browser displayed its fill price, quantity and fees without creating a duplicate position.
- Form validation produces actionable field messages.
- Treasury calculator: $10 million executed volume at 0.02% -> $2,000 hypothetical gross revenue. Actual collected builder fees remain zero.
- Journal export downloaded and parsed successfully.
- Responsive dimensions checked at 320, 375, 414, 768 and 1280 CSS pixels. Navigation fits; root has no horizontal overflow. Native dialog remains scrollable on small screens.
- Fixed global table styles leaking into the chart's internal tables and chart price-line cleanup after component disposal.
- Computed foreground/background contrast check passed for rendered text on the tank screen; decorative scene lettering is excluded from content semantics.

## External integration

The read-only Hyperliquid smoke check succeeded and returned BTC market context plus 90 one-minute candles. No keys or orders were used. Unit tests use mocked exchange responses and do not depend on network availability.

The Anthropic adapter's request/output contract is tested with mocked responses. Actual paid inference has not been verified because no provider credentials were supplied. PostgreSQL and exchange trading/signing are not verified here.

## Financial interpretation

These checks establish local software behavior, not a trading edge or sustainable business economics. Paper fills assume full execution, modeled adverse slippage and taker fees; they do not model funding, order-book queue priority, partial fills or exchange outages faithfully. Performance figures must retain the paper label.


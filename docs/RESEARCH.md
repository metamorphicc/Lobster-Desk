# Autonomous strategy laboratory

Research can propose only BTC hourly trend, breakout or mean-reversion rules. The grammar bounds lookback, fast window, threshold, stop, reward/risk and holding time. No generated Python, shell commands, URLs, model tools or arbitrary indicators are executed.

Historical input consists of complete, ordered, closed hourly OHLCV candles and one observed funding rate per settlement hour. Synthetic history is labelled `demo`. Public Hyperliquid history uses fixed `/info` hosts, bounded inclusive pagination and duplicate/conflict checks. Missing/truncated history blocks research instead of replacing funding with zero or extrapolating current values. Historical OI, liquidations and news are not supplied or invented. The standard initial window is 1,440 hours (60 days); it is not a multi-year market study.

Signals see only closed bars before the entry bar; entries use the next open with adverse slippage and a maximum entry gap. The deterministic simulator uses Decimal, current coded sizing/loss limits, fees on both fills, signed historical funding and a time exit. Ambiguous OHLC bars stop first; gaps can fill worse than the stop. Historical funding uses hourly close as a notional proxy and does not credit uncertain favorable funding on an intrabar exit. Hourly prices cannot reproduce order-book liquidity, exact intrabar risk-trigger paths or all exchange behavior.

The first 60% is development data. Candidate generation must not receive the later 40%. The next 20% selects among at most three candidates, with doubled fee/slippage stress. Each development/validation/stress gate requires at least eight trades, positive net PnL, no latched loss halt and at most 3% close-marked drawdown. These are engineering admission thresholds, not statistical proof of an edge. Only the validation winner sees the final 20%, once per cohort; failure has no runner-up fallback. The final window must pass the same base gate before paper admission.

The complete dataset/rules and report hashes make a result reproducible. Failed candidates remain in the journal. Repeated rolling campaigns overlap history, so their tests are not independent discoveries and do not prove statistical significance. New forward paper observations remain essential. Real exchange execution is not granted by any research result.

Public history adapter smoke check on 2026-10-17: 1,440 real BTC hourly candles and 1,440 funding observations validated. Public reads only; no keys or exchange writes. The initial check exposed millisecond funding settlement timestamps and the adapter was corrected and covered by inclusive-pagination tests.

Primary references: [Hyperliquid candles and pagination](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [historical funding](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals). These document data transport, not the performance of any Claw Desk strategy.

## Durable autonomous paper loop

`RESEARCH_ENABLED=true` starts a separate worker alongside market protection and setup reviews. It fetches current hourly history, runs one cohort per `RESEARCH_INTERVAL_SECONDS` (default one day), and proposes signals only for the latest closed hour. No signal is chased beyond 0.2% from that close. At most one pitch per executable strategy/hour/source is committed atomically with its provenance; repeated ticks/process restarts cannot duplicate it.

The optional Anthropic researcher receives only development-window statistics and its latest 96 closed bars, never the later 40% or current price. It creates up to three bounded candidates. Code tests them; a separate critic call can veto the selected candidate. The same configured model can perform distinct roles; these are not statistically independent models. Each emitted pitch still goes through the existing analyst, risk reviewer and deterministic banker. Research has no wallet or exchange writer.

Research calls are durably reserved before HTTP, capped separately (default four/day, at most two/cohort) from the existing setup-review budget (default 100/day). Token counts are recorded, but these are call/output-token limits, not a guaranteed dollar spending cap. Timeouts, malformed output and exhausted budgets fail the cohort with sanitized messages. Startup marks interrupted cohorts as interrupted; unknown paid calls are never replayed. Scheduling refuses clock rollback. A failed cohort can be revisited only as a new scheduled dataset/cohort, not an HTTP retry of its old call.

Passing candidates are eligible for **forward paper observation**, not live deployment. They expire after seven days or retire when at least eight completed forward paper trades have nonpositive aggregate net PnL. Account-wide coded halts remain independent. Time exits are enforced by the market/protection worker using the originating strategy's holding limit, even if a later cohort becomes active. Existing paper fills still exclude funding; historical laboratory tests include it. This difference is disclosed, not treated as live acceptance.

Campaigns, full immutable input history, hashes, model metadata, all candidate outcomes and signal links share the paper database and its backups. `GET /api/v1/research` returns compact recent results, `GET /api/v1/research/{id}` returns the reproducible cohort. These read routes neither trigger paid calls nor activate exchange execution. `/api/v1/economics` reports the independent receipt book under the agreed distribution policy; it never treats simulated paper PnL as treasury income.

For an isolated no-key rehearsal (synthetic history and scripted hypotheses, no network):

```powershell
node scripts/python.mjs scripts/research-once.py --output artifacts/research/new-offline-run
```

Use a new output directory. `--source hyperliquid` opts into public data; `--provider anthropic` explicitly opts into paid model calls with configured credentials. Neither option can enable financial execution.

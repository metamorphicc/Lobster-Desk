# Autonomous strategy laboratory

Research can propose only BTC hourly trend, breakout or mean-reversion rules. The grammar bounds lookback, fast window, threshold, stop, reward/risk and holding time. No generated Python, shell commands, URLs, model tools or arbitrary indicators are executed.

Historical input consists of complete, ordered, closed hourly OHLCV candles and one observed funding rate per settlement hour. Synthetic history is labelled `demo`. Public Hyperliquid history uses fixed `/info` hosts, bounded inclusive pagination and duplicate/conflict checks. Missing/truncated history blocks research instead of replacing funding with zero or extrapolating current values. Historical OI, liquidations and news are not supplied or invented. The standard initial window is 1,440 hours (60 days); it is not a multi-year market study.

Signals see only closed bars before the entry bar; entries use the next open with adverse slippage and a maximum entry gap. The deterministic simulator uses Decimal, current coded sizing/loss limits, fees on both fills, signed historical funding and a time exit. Ambiguous OHLC bars stop first; gaps can fill worse than the stop. Historical funding uses hourly close as a notional proxy and does not credit uncertain favorable funding on an intrabar exit. Hourly prices cannot reproduce order-book liquidity, exact intrabar risk-trigger paths or all exchange behavior.

The first 60% is development data. Candidate generation must not receive the later 40%. The next 20% selects among at most three candidates, with doubled fee/slippage stress. Each development/validation/stress gate requires at least eight trades, positive net PnL, no latched loss halt and at most 3% close-marked drawdown. These are engineering admission thresholds, not statistical proof of an edge. Only the validation winner sees the final 20%, once per cohort; failure has no runner-up fallback. The final window must pass the same base gate before paper admission.

The complete dataset/rules and report hashes make a result reproducible. Failed candidates remain in the journal. Repeated rolling campaigns overlap history, so their tests are not independent discoveries and do not prove statistical significance. New forward paper observations remain essential. Real exchange execution is not granted by any research result.

Public history adapter smoke check on 2026-10-17: 1,440 real BTC hourly candles and 1,440 funding observations validated. Public reads only; no keys or exchange writes. The initial check exposed millisecond funding settlement timestamps and the adapter was corrected and covered by inclusive-pagination tests.

Primary references: [Hyperliquid candles and pagination](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [historical funding](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals). These document data transport, not the performance of any Lobster Desk strategy.

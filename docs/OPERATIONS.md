# Local readiness and operational observations

The diagnostics API reports the local paper runtime, not production or exchange readiness. Requests are read-only: no database updates, exchange calls, model calls or signer activation occur.

## Probes

- `GET /api/health` is a liveness response. A running API can return HTTP 200 even while its worker is disabled, market data is stale or paper trading is paused.
- `GET /api/ready` returns HTTP 200 only when the local paper database is readable, both enabled worker tasks are running with recent completed ticks, the market observation is fresh and matches configuration, and the feed/decision loop reports no worker error. Otherwise it returns HTTP 503 with the diagnostic report.
- `GET /api/v1/ops/status` returns that same report with HTTP 200 so the dashboard can display an unhealthy runtime without treating its diagnostic response as an unavailable endpoint.

The report always retains `production_verified=false`, `exchange_execution_verified=false` and `diagnostic_only=true`. A green local readiness check never authorizes a trade or proves a strategy is profitable.

## What is observed

Market freshness uses the existing coded age limit (15 seconds, with at most two seconds of future-clock tolerance). Worker completion deadlines are 30 seconds or three market poll periods, whichever is longer; decision completion allows at least 90 seconds to accommodate a model call and review interval. A task that stopped or has not completed a recent tick blocks readiness. If the entire event loop is unresponsive, an external probe must detect the timeout; a stalled process cannot reliably alert on itself.

Read-only SQL aggregates expose pending reviews, reserved entries, open paper positions and the current UTC review-call budget. Unknown database state is reported as unavailable, never as fabricated zero counts. The financial journal remains the authoritative explanation for account risk halts.

Paper pause, a latched risk halt, occupied execution slot and exhausted review budget are separate from process readiness. A healthy service can correctly be paused or protecting an existing position. Reported entry blockers are diagnostic observations; each actual entry still rechecks its specific approval, risk, capital and expiry. Reading or acknowledging diagnostics does not pause, resume or close anything.

Alerts distinguish service, paper and testnet scopes. An open paper position without fresh market observations produces a critical paper alert. Testnet uncertainty is derived only from the local execution ledger: reconciliation/cleanup/protection states and latched halts are surfaced without claiming current exchange exposure. Testnet alerts may coexist with a ready independent paper runtime. Use the separate owner runner and exchange observations for actual reconciliation.

## Operational limits

These are current local observations, not durable alert delivery or a hosted monitoring system. They do not elect a worker, supervise a signer, configure external notification services, replace off-machine backups or complete funded acceptance. Production identity, distributed controls, external alerts and an independent security review remain under stage 6.1c.

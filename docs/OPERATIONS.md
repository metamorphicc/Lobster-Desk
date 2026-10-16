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

## Local dashboard and command

The dashboard's **Local paper runtime** panel refreshes every ten seconds and on demand. It exposes scoped alerts, entry blockers, market age, queued reviews and the UTC review-call budget. Expand **Inspect runtime checks** for individual results. Failed requests clear the previous ready report and show unknown status. A ready paper service may still have a critical testnet alert; the separate alert count includes all scopes.

With local services running, use:

```powershell
node scripts/python.mjs scripts/check-health.py
node scripts/python.mjs scripts/check-health.py --web
```

The first command probes the fixed loopback API; `--web` also exercises Next's loopback proxy. Exit codes are **0** for a ready paper service without critical alerts, **1** for a blocked service or any critical alert, and **2** for timeout, unavailable service or malformed/inconsistent diagnostics. Redirects and environment HTTP proxies are disabled. Neither command loads signer settings or changes execution state. These are single checks, not scheduled monitors or external notifications.

## Pitch admission

Validated pitch requests have a persisted sliding limit of **10 attempts per transport peer per 60 seconds**, including idempotent retries and conflicting/full-queue submissions. HTTP 429 includes the remaining `Retry-After` seconds. Invalid schemas/keys are rejected before admission. The limiter commits before submission, so failed submissions do not refund attempts. A database/admission-state failure returns a static HTTP 503 and admits no pitch.

One bounded row in `pitch_admission` stores hashed peer keys, active timestamps and a clock floor. It retains at most 128 active peers; additional peers wait until a slot expires. Expired timestamps/peers are pruned on requests. Backward wall-clock changes cannot reset windows, including across restarts; a forward jump followed by rollback can make waiting longer. Peer hashes are guessable fingerprints, not anonymization or authentication. Forwarded client headers are ignored. Through the local Next proxy, users share its transport-peer budget.

Transactions serialize admission across instances sharing this local SQLite file. The existing global queue limit remains **20** pending reviews and counts them in SQL inside the submission transaction; idempotent replay still returns the original episode when the queue is full. Approved reservations and open positions remain governed by the financial controls. The durable UTC model-call budget also uses an atomic SQL count. Snapshot/restore preserves admission state captured in the snapshot; restoring older data cannot recover attempts made after capture.

This adds no public identity, tenant isolation, distributed rate service or worker election. Separate databases have separate limits. Production controls remain a separate gate.

## Operational limits

These are current local observations, not durable alert delivery or a hosted monitoring system. They do not elect a worker, supervise a signer, configure external notification services, replace off-machine backups or complete funded acceptance. Production identity, distributed controls, external alerts and an independent security review remain under stage 6.1c.

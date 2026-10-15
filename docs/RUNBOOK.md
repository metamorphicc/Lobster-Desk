# Local operations

## Start and stop

Run `npm run dev` from the repository root. It starts the API and Next.js on loopback. Ctrl+C shuts down both owned process trees. The API deliberately runs without a reload watcher: restart after Python changes. Next.js hot-reloads frontend changes.

Run one API process/worker per database. No multi-worker or multi-replica operation is supported yet. SQLite is the tested local backend; PostgreSQL is supported by the SQLAlchemy adapter but has not been exercised in this environment.

## Pause, resume, close

Configure an `OPERATOR_TOKEN` in the root `.env` and restart. Open the sliders control at the top right; enter the token in the dialog. It stays in page memory only.

- Pause blocks new entries; the next protection tick rejects outstanding approved entries and releases their reservation. Open-position monitoring continues.
- Resume only clears an operator pause. It cannot clear a daily-loss/drawdown halt.
- Close uses a fresh market observation with adverse slippage and fees. It does not cancel unfilled proposals; pause first when stopping the tank.
- A risk halt is intentionally latched for investigation. There is no public reset or deposit endpoint that bypasses it.

## Feed failure and downtime

The UI marks market data unavailable/stale. New entries are blocked and model calls wait for fresh data. The application never silently switches a Hyperliquid session to synthetic prices.

Paper positions cannot close while there is no fresh price or while the service is stopped. On recovery, protection evaluates the current market price, allowing a gap loss beyond the planned stop risk. Funding and price movements that occurred entirely between observations are not reconstructed. The live execution stage must install exchange-native protection and reconcile actual fills.

## Recovery and backup

Stop the service before backing up the local SQLite database. Copy `data/lobster.db` to an owner-controlled backup location. Keep `.env` separate and private. Restore to the same database path while the service is stopped.

On restart, the account, active approvals, positions and event IDs are loaded from the database. Repeated fills for one proposal return the existing position. An interrupted model review is rejected instead of spending on an automatic repeat.

To start a separate experiment, set a new database file in `DATABASE_URL`. Do not delete a database to hide losses. Preserve and export its journal first. There is no automatic cleanup of historical records.

## Testnet workbench and signer

The **Testnet** tab performs read-only readiness/preflight and operator-protected local staging/cancellation. These controls do not activate exchange submission. The separate owner runner, isolated environment file, recovery commands and funded acceptance limits are documented in [TESTNET.md](TESTNET.md).

Paper operator pause/close controls apply only to the simulated tank account. They do not pause the separate signer or close exchange positions. Stopping `npm run dev` also does not stop an independently launched signer runner. Inspect the exchange account and protective orders when stopping either process.

## Public deployment gate

Before exposing this app publicly: add user identity, durable distributed rate limits, request body limits, proper database migrations, worker leadership, TLS, secret storage, backups, alerting and independent review. Test signer permissions, partial fills, exchange stops, fee approval and revocation on testnet before mainnet activation. These gates are tracked in stages 5–6.


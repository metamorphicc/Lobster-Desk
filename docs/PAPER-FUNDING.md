# Forward paper funding

The paper runtime now defaults `PAPER_FUNDING_ENABLED=true`. New paper positions carry an explicit funding cursor, signed net funding and an accounting scope. Legacy positions created without the model are not retroactively relabelled as complete; the account exposes that legacy scope. Existing closed historical results are preserved.

A separate funding worker retrieves complete closed hourly candles and historical funding for every owed hourly boundary, using the configured source. It cannot substitute today's rate for missing history. Each settlement records position/hour/source/rate/notional proxy and is applied atomically with the cash/position cursor. Repeated ticks, concurrent readers and restart cannot charge it twice. Funding received by shorts has the opposite sign from longs; rates themselves can also be negative.

The hourly candle close is a notional-price proxy, matching the historical laboratory's approximation, not an exact exchange funding receipt. Paper settlement uses exposure at the hourly boundary: an entry after the boundary is not charged for that boundary. Closed positions can receive delayed accounting updates for boundaries before closure. Their displayed net PnL and cash are reconciled together without rewriting the original close event.

Missing/out-of-range history rolls back settlement and blocks new entries. Pending owed funding also blocks admission before its worker completes. Market stop/target/time/risk protection remains independently callable, and no funding data failure prevents an existing position from closing. Settlements feed the existing daily-loss/drawdown checks on the next market tick. Funding differences never become real treasury revenue.

The API/UI expose funding amounts and legacy scope; runtime diagnostics report pending/failed reconciliation. Seven focused invariant cases cover signed costs/credits, closed-position recovery, restart/concurrency, rollback and legacy scope. No exchange write is part of paper funding.

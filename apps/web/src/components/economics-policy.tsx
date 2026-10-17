"use client";

/* Hallmark · component: distribution ledger · Midnight · P4 H4 E4 S5 R5 V4 */
import { useLocalReport } from "@/lib/use-local-report";
import { money, signed } from "@/lib/types";

export type EconomicsReport = { record_count: number; recorded_cash: string;
  revenue_observer?: { network: "mainnet"; status: "not_configured" | "stopped" | "running" | "unavailable"; last_success_at: string | null };
  fee_allocation: { agents: string; team: string };
  user_strategy_profit: { net_realized: string; author_entitlement: string; author_paid: string; author_outstanding: string; bot_retained: string };
  net_realized_trading_profit_after_expenses: string; loss_carryforward: string;
  lifetime_buyback_entitlement: string; recorded_buyback_spend: string; reserve_bounded_buyback_budget: string | null;
  recorded_team_paid: string; blockers: string[];
  solana?: { configured: boolean; mint?: string; operations: { id: string; kind: string; status: string; signature: string | null; cost_usdc: string | null; quantity_atomic: string | null }[];
    lots: { id: string; quantity: string; burned: string; decimals: number; burn_signature?: string }[] };
};

export function EconomicsPolicy() {
  const report = useLocalReport<EconomicsReport>("/api/v1/economics");
  return <EconomicsView {...report} />;
}

export function EconomicsView({ data, error, loading, refresh }: { data: EconomicsReport | null; error: string; loading: boolean; refresh: () => void }) {
  return <section className="treasury-panel economics-policy"><div className="panel-heading"><h2>Where the proceeds go</h2><span className="tag">AGREED POLICY</span></div>
    <div className="economics-body"><p>0.05% builder fee on executed entries, additional to exchange costs. Collection requires approved user fills; paper fills generate no fees.</p>
      <dl className="economics-split"><div><dt>Bot capital</dt><dd>60%<small>0.03% of entry volume</small></dd></div><div><dt>Team</dt><dd>40%<small>0.02% of entry volume</small></dd></div></dl>
      <p><strong>User-strategy net profit: 50% to its verified author, 50% back to bot capital.</strong> Only closed project trades count, after trading fees, funding and strategy loss recovery. Accrued shares are separate from completed payments.</p>
      {loading && !data && <p role="status">Loading the independent receipt book…</p>}
      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {data && <><p className="small-note">{data.record_count} local receipts · Owner-supplied observations remain unverified. Paper capital and paper profits are not included.</p>
        {data.revenue_observer && <p className="small-note">Received-fee observer · {data.revenue_observer.status.replaceAll("_", " ")}. Last successful mainnet reconciliation: {data.revenue_observer.last_success_at ? new Date(data.revenue_observer.last_success_at).toLocaleString("en-GB") : "Not observed"}. Unclaimed rewards are excluded.</p>}
        <dl className="levels"><div><dt>Recorded treasury cash</dt><dd>{money(data.recorded_cash)}</dd></div>
          <div><dt>Agent fee allocation</dt><dd>{money(data.fee_allocation.agents)}</dd></div><div><dt>Team fee allocation</dt><dd>{money(data.fee_allocation.team)}</dd></div>
          <div><dt>Net realized trading profit / costs</dt><dd>{signed(data.net_realized_trading_profit_after_expenses)}</dd></div><div><dt>Unrecovered loss</dt><dd>{money(data.loss_carryforward)}</dd></div>
          <div><dt>User-strategy net realized profit</dt><dd>{signed(data.user_strategy_profit.net_realized)}</dd></div>
          <div><dt>Strategy authors · earned</dt><dd>{money(data.user_strategy_profit.author_entitlement)}</dd></div><div><dt>Strategy authors · paid</dt><dd>{money(data.user_strategy_profit.author_paid)}</dd></div>
          <div><dt>Strategy authors · outstanding</dt><dd>{money(data.user_strategy_profit.author_outstanding)}</dd></div><div><dt>User-strategy profit retained by bot</dt><dd>{signed(data.user_strategy_profit.bot_retained)}</dd></div><div><dt>Recorded buyback spending</dt><dd>{money(data.recorded_buyback_spend)}</dd></div>
          <div><dt>Reserve-bounded buyback budget</dt><dd>{data.reserve_bounded_buyback_budget == null ? "Not configured" : money(data.reserve_bounded_buyback_budget)}</dd></div></dl>
        {!!data.blockers.length && <ul className="economics-blockers">{data.blockers.map(line => <li key={line}>{line}</li>)}</ul>}
        {data.solana && <div className="financial-jobs"><h3>Own-agent strategy buybacks</h3><p className="small-note">The existing token policy applies only to eligible profits from the agents&apos; own strategies. User-strategy profits and author liabilities are excluded.</p>
          {!data.solana.configured && <p className="small-note">The project token uses Solana. Its mint and funded treasury wallet are not configured.</p>}
          {data.solana.configured && !data.solana.operations.length && <p className="small-note">No purchase or burn transactions recorded.</p>}
          {!!data.solana.operations.length && <ul className="user-position-list">{data.solana.operations.slice(0, 6).map(operation => <li key={operation.id}>
            <strong>{operation.kind} · {operation.status}</strong><span>{operation.cost_usdc ? money(operation.cost_usdc) : `${operation.quantity_atomic} atomic tokens`}</span>
            {operation.signature && <a className="text-link" href={`https://solscan.io/tx/${encodeURIComponent(operation.signature)}`} target="_blank" rel="noreferrer">View transaction</a>}</li>)}</ul>}
          {!!data.solana.lots.length && <p className="small-note">Purchased lots are tracked through their full actual received quantity. Only finalized BurnChecked transactions mark a lot as burned.</p>}
        </div>}
      </>}
      <p className="small-note">Separate owner-enabled runners execute financial operations; this page reads receipts. Received-fee allocation, accrued author shares and observed payments are shown separately. No holder payouts or guaranteed price support.</p>
      <button className="text-button" disabled={loading} onClick={refresh}>{loading ? "Refreshing…" : "Refresh receipts"}</button>
    </div></section>;
}

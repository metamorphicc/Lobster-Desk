"use client";

/* Hallmark · component: distribution ledger · Midnight · P4 H4 E4 S5 R5 V4 */
import { useLocalReport } from "@/lib/use-local-report";
import { money, signed } from "@/lib/types";

export type EconomicsReport = { record_count: number; recorded_cash: string;
  fee_allocation: { agents: string; team: string; charity: string };
  net_realized_trading_profit_after_expenses: string; loss_carryforward: string;
  lifetime_buyback_entitlement: string; recorded_buyback_spend: string; reserve_bounded_buyback_budget: string | null;
  recorded_charity_paid: string; recorded_team_paid: string; blockers: string[] };

export function EconomicsPolicy() {
  const report = useLocalReport<EconomicsReport>("/api/v1/economics");
  return <EconomicsView {...report} />;
}

export function EconomicsView({ data, error, loading, refresh }: { data: EconomicsReport | null; error: string; loading: boolean; refresh: () => void }) {
  return <section className="treasury-panel economics-policy"><div className="panel-heading"><h2>Where the proceeds go</h2><span className="tag">AGREED POLICY</span></div>
    <div className="economics-body"><p>0.05% builder fee on executed entries, additional to exchange costs. Collection is currently disabled.</p>
      <dl className="economics-split"><div><dt>Agents</dt><dd>40%<small>0.02% of entry volume</small></dd></div><div><dt>Team</dt><dd>20%<small>0.01% of entry volume</small></dd></div><div><dt>Charity</dt><dd>40%<small>0.02% of entry volume</small></dd></div></dl>
      <p><strong>50% of available net trading profit → buyback → burn.</strong> The other half stays with the agents. Prior losses and costs are recovered first. Charity and team earmarks are excluded from the buyback budget.</p>
      {loading && !data && <p role="status">Loading the independent receipt book…</p>}
      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {data && <><p className="small-note">{data.record_count} local receipts · Owner-supplied observations remain unverified. Paper capital and paper profits are not included.</p>
        <dl className="levels"><div><dt>Recorded treasury cash</dt><dd>{money(data.recorded_cash)}</dd></div>
          <div><dt>Agent fee allocation</dt><dd>{money(data.fee_allocation.agents)}</dd></div><div><dt>Team fee allocation</dt><dd>{money(data.fee_allocation.team)}</dd></div><div><dt>Charity fee allocation</dt><dd>{money(data.fee_allocation.charity)}</dd></div>
          <div><dt>Net realized trading profit / costs</dt><dd>{signed(data.net_realized_trading_profit_after_expenses)}</dd></div><div><dt>Unrecovered loss</dt><dd>{money(data.loss_carryforward)}</dd></div>
          <div><dt>Recorded charity paid</dt><dd>{money(data.recorded_charity_paid)}</dd></div><div><dt>Recorded buyback spending</dt><dd>{money(data.recorded_buyback_spend)}</dd></div>
          <div><dt>Reserve-bounded buyback budget</dt><dd>{data.reserve_bounded_buyback_budget == null ? "Not configured" : money(data.reserve_bounded_buyback_budget)}</dd></div></dl>
        {!!data.blockers.length && <ul className="economics-blockers">{data.blockers.map(line => <li key={line}>{line}</li>)}</ul>}
      </>}
      <p className="small-note">Token network/contract and charity recipients are pending. No donations, purchases or burns are executed here. No holder payouts or guaranteed price support.</p>
      <button className="text-button" disabled={loading} onClick={refresh}>{loading ? "Refreshing…" : "Refresh receipts"}</button>
    </div></section>;
}

"use client";

/* Hallmark · component: distribution ledger · Midnight · P4 H4 E4 S5 R5 V4 */
import { useLocalReport } from "@/lib/use-local-report";
import { money, signed } from "@/lib/types";

export type EconomicsReport = { record_count: number; recorded_cash: string;
  fee_allocation: { agents: string; team: string; charity: string };
  net_realized_trading_profit_after_expenses: string; loss_carryforward: string;
  lifetime_buyback_entitlement: string; recorded_buyback_spend: string; reserve_bounded_buyback_budget: string | null;
  recorded_charity_paid: string; recorded_team_paid: string; blockers: string[];
  solana?: { configured: boolean; mint?: string; operations: { id: string; kind: string; status: string; signature: string | null; cost_usdc: string | null; quantity_atomic: string | null }[];
    lots: { id: string; quantity: string; burned: string; decimals: number; burn_signature?: string }[] };
  charity?: { provider: string; network: string; recipients: Record<string, { name: string }>;
    payments: { id: string; recipient: string; status: string; amount: string; signature: string | null; provider_status: string | null;
      provider_net_amount: string | null; provider_net_currency: string | null }[] } };

export function EconomicsPolicy() {
  const report = useLocalReport<EconomicsReport>("/api/v1/economics");
  return <EconomicsView {...report} />;
}

export function EconomicsView({ data, error, loading, refresh }: { data: EconomicsReport | null; error: string; loading: boolean; refresh: () => void }) {
  return <section className="treasury-panel economics-policy"><div className="panel-heading"><h2>Where the proceeds go</h2><span className="tag">AGREED POLICY</span></div>
    <div className="economics-body"><p>0.05% builder fee on executed entries, additional to exchange costs. Collection requires approved user fills; paper fills generate no fees.</p>
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
        {data.solana && <div className="financial-jobs"><h3>Solana purchases and burns</h3>
          {!data.solana.configured && <p className="small-note">The project token uses Solana. Its mint and funded treasury wallet are not configured.</p>}
          {data.solana.configured && !data.solana.operations.length && <p className="small-note">No purchase or burn transactions recorded.</p>}
          {!!data.solana.operations.length && <ul className="user-position-list">{data.solana.operations.slice(0, 6).map(operation => <li key={operation.id}>
            <strong>{operation.kind} · {operation.status}</strong><span>{operation.cost_usdc ? money(operation.cost_usdc) : `${operation.quantity_atomic} atomic tokens`}</span>
            {operation.signature && <a className="text-link" href={`https://solscan.io/tx/${encodeURIComponent(operation.signature)}`} target="_blank" rel="noreferrer">View transaction</a>}</li>)}</ul>}
          {!!data.solana.lots.length && <p className="small-note">Purchased lots are tracked through their full actual received quantity. Only finalized BurnChecked transactions mark a lot as burned.</p>}
        </div>}
        {data.charity && <div className="financial-jobs"><h3>Charity payments</h3>
          <p className="small-note">{data.charity.provider} · USDC (ERC-20), Ethereum. Selected causes: {Object.values(data.charity.recipients).map(r => r.name).join(" and ")}.</p>
          {!data.charity.payments.length && <p className="small-note">No donation transfers recorded. Earmarked funds remain separate from completed payments.</p>}
          {!!data.charity.payments.length && <ul className="user-position-list">{data.charity.payments.slice(0, 6).map(payment => <li key={payment.id}>
            <strong>{data.charity!.recipients[payment.recipient]?.name || "Selected charity"} · {payment.status}</strong><span>Gross transfer {money(payment.amount)} · {payment.provider_status === "record_observed" ? "Provider record observed" : "Provider acknowledgment pending"}</span>
            {payment.provider_net_amount !== null && <span>Provider-reported net {payment.provider_net_amount} {payment.provider_net_currency}</span>}
            {payment.signature && <a className="text-link" href={`https://etherscan.io/tx/${encodeURIComponent(payment.signature)}`} target="_blank" rel="noreferrer">View transfer</a>}</li>)}</ul>}
        </div>}
      </>}
      <p className="small-note">Separate owner-enabled runners execute financial operations; this page reads receipts. Chain observations and provider records are shown separately. No holder payouts or guaranteed price support.</p>
      <button className="text-button" disabled={loading} onClick={refresh}>{loading ? "Refreshing…" : "Refresh receipts"}</button>
    </div></section>;
}

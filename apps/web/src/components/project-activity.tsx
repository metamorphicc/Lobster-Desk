"use client";

/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4
 * component: project exchange journal · Midnight · existing tokens
 * states: default/hover/focus/active/disabled/loading/error/success */
import { useEffect, useRef, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { money, number } from "@/lib/types";

export type ProjectActivityData = { schema: "lobster-public-project-activity-v1"; observed_at: string; submission_enabled: false;
  scope: "registered-project-journals-only"; limits: string; journals: { id: string; network: "testnet" | "mainnet"; halted: boolean;
    heartbeat: null | { attempt_at: string; last_success_at: string | null; ok: boolean };
    trades: { id: string; network: "testnet" | "mainnet"; status: string; created_at: string; direction: string;
      entry: { side: string; quantity: string; price: string }; stop: string; target: string;
      filled_quantity: string; protected_quantity: string; approval_hash: string;
      reviews: Record<string, { verdict: string; summary: string; evidence: string[] }>;
      recent_fills: { time: number; px: string; sz: string; fee: string; feeToken: string; closedPnl: string; side: string }[] }[] }[] };

export function ProjectActivity() {
  const [data, setData] = useState<ProjectActivityData | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  async function refresh() {
    controller.current?.abort(); const current = new AbortController(); controller.current = current;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/v1/project/activity", { cache: "no-store", signal: AbortSignal.any([current.signal, AbortSignal.timeout(10000)]) });
      if (!response.ok) throw new Error();
      const value = await response.json();
      if (value.schema !== "lobster-public-project-activity-v1" || value.scope !== "registered-project-journals-only"
        || value.submission_enabled !== false || !Array.isArray(value.journals) || value.journals.length > 4) throw new Error();
      if (!current.signal.aborted) setData(value);
    } catch { if (!current.signal.aborted) { setData(null); setError("Project exchange observations are unavailable. Refresh before relying on this journal."); } }
    finally { if (!current.signal.aborted) setBusy(false); }
  }
  useEffect(() => {
    void refresh(); const timer = setInterval(() => { void refresh(); }, 15000);
    return () => { clearInterval(timer); controller.current?.abort(); };
  }, []);
  return <ProjectActivityView data={data} busy={busy} error={error} refresh={() => { void refresh(); }} />;
}

export function ProjectActivityView({ data, busy, error, refresh }: { data: ProjectActivityData | null; busy: boolean; error: string; refresh: () => void }) {
  return <section className="testnet-panel" aria-labelledby="project-activity-title">
    <div className="panel-heading"><h2 id="project-activity-title">Project exchange activity</h2><button className="text-button" disabled={busy} onClick={refresh}>
      {busy ? <LoaderCircle size={14} className="spinner" /> : <RefreshCw size={14} />}{busy ? "Reading…" : "Refresh exchange journal"}</button></div>
    <div className="testnet-body">
      <p className="small-note">Project runner observations, separate from the paper account and private user trades. Testnet fills use test funds; mainnet uses real funds.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      {!data && busy && <p role="status">Reading registered project journals…</p>}
      {data && !data.journals.length && <p className="empty-note">No project execution journal is registered. Paper trades above are simulations; no exchange performance is inferred.</p>}
      {data?.journals.map(journal => <div key={journal.id} className="testnet-preview">
        <strong>{journal.network.toUpperCase()} · {journal.halted ? "Entry halt recorded" : "Project journal"}</strong>
        <p className="small-note">Last runner success: {journal.heartbeat?.last_success_at ? new Date(journal.heartbeat.last_success_at).toLocaleString("en-GB") : "Not observed"}. This is a saved observation; refreshing does not run the signer.</p>
        {!journal.trades.length && <p className="empty-note">No project intents recorded.</p>}
        {journal.trades.map(trade => <article key={trade.id} className="builder-consent">
          <h3>BTC {trade.direction} · {trade.status}</h3><p className="hash-note">Episode <code>{trade.id}</code></p>
          <dl className="testnet-observations"><div><dt>Entry limit</dt><dd>{money(trade.entry.price)}</dd></div><div><dt>Intended quantity</dt><dd>{number(trade.entry.quantity, 6)} BTC</dd></div>
            <div><dt>Confirmed fill</dt><dd>{number(trade.filled_quantity, 6)} BTC</dd></div><div><dt>Confirmed protection</dt><dd>{number(trade.protected_quantity, 6)} BTC</dd></div>
            <div><dt>Stop</dt><dd>{money(trade.stop)}</dd></div><div><dt>Target</dt><dd>{money(trade.target)}</dd></div></dl>
          {Object.entries(trade.reviews).map(([role, review]) => <div key={role}><h4>{role} · {review.verdict}</h4><p className="small-note">{review.summary}</p></div>)}
          <ul className="user-position-list">{trade.recent_fills.map((fill, index) => <li key={index}><strong>{fill.side === "B" ? "Buy" : "Sell"} · {number(fill.sz, 6)} BTC @ {money(fill.px)}</strong>
            <span>Observed fee {money(fill.fee, 6)} {fill.feeToken} · Closed PnL {money(fill.closedPnl, 6)}</span></li>)}</ul>
          <p className="hash-note">Review binding <code>{trade.approval_hash}</code></p>
        </article>)}
      </div>)}
      {data && <p className="small-note">{data.limits} Observed {new Date(data.observed_at).toLocaleString("en-GB")}.</p>}
    </div>
  </section>;
}

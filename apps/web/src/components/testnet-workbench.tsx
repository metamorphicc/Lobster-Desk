"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Check, FlaskConical, LoaderCircle, ShieldCheck } from "lucide-react";
import { money, number, type State } from "@/lib/types";

type Order = { side: string; quantity: string; price: string; cloid: string };
type Ledger = {
  control: { halt_reason: string | null };
  trades: { id: string; status: string; reason: string; filled_quantity: string; protected_quantity: string }[];
  events: { id: number; timestamp: string; kind: string; message: string }[];
  observed_fill_fees: string; observed_closed_pnl: string;
};
type Status = {
  account_address: string | null; api_wallet_address: string | null; max_entry_notional: string;
  operator_staging_available: boolean; ledger: Ledger | null;
};
type Inspection = Status & {
  checks: { key: string; label: string; status: string }[];
  error: string | null; ready_to_stage: boolean;
  market: { price: string } | null; account: { equity: string; withdrawable: string } | null;
};
type Preview = Inspection & { episode_id: string; eligible: boolean; order: Order | null; reason: string | null };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/testnet${path}`, { cache: "no-store", ...init });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `The service returned ${response.status}.`);
  return body;
}

export function TestnetWorkbench({ state }: { state: State | null }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [episodeId, setEpisodeId] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    let alive = true;
    const refresh = () => { void request<Status>("/status").then(value => { if (alive) setStatus(value); })
      .catch(() => { if (alive) setError("The testnet service is unavailable. Start the local API and retry."); }); };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  async function run(action: "inspect" | "preview" | "stage") {
    setBusy(action); setError(""); setMessage("");
    try {
      if (action === "inspect") {
        setPreview(null);
        const report = await request<Inspection>("/inspect");
        setInspection(report); setStatus(report);
      } else if (action === "preview") {
        setPreview(null);
        const report = await request<Preview>(`/preflight/${encodeURIComponent(episodeId)}`);
        setPreview(report); setInspection(report); setStatus(report);
      } else {
        const trade = await request<{ id: string }>("/stage", { method: "POST", headers: {
          "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ episode_id: episodeId }) });
        setToken(""); setPreview(null);
        setMessage(`Intent ${trade.id.slice(0, 8)} saved locally. The owner signer must be run separately to submit it.`);
        setStatus(await request<Status>("/status"));
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The check could not complete. Try again.");
    } finally { setBusy(""); }
  }

  async function cancel(id: string) {
    setBusy(id); setError(""); setMessage("");
    try {
      await request("/cancel", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ episode_id: id }) });
      setToken(""); setPreview(null); setMessage("Unsent intent cancelled locally. No exchange action was sent.");
      setStatus(await request<Status>("/status"));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "The local intent could not be cancelled."); }
    finally { setBusy(""); }
  }

  const episodes = state?.episodes.filter(ep => ["approved", "filled"].includes(ep.status)) || [];
  const ledger = status?.ledger;
  return <div className="testnet-workbench">
    <div className="testnet-boundary"><FlaskConical size={22} /><div><strong>Testnet only. Exchange submission runs separately.</strong>
      <p>This page checks public account data and saves local intents. The API never loads a trading key. Funded exchange acceptance is still unverified.</p></div></div>
    {error && <div className="notice notice--error" role="alert">{error}<button disabled={!!busy} onClick={() => { void run("inspect"); }}>Retry</button></div>}
    {message && <div className="notice" role="status">{message}</div>}
    {ledger?.control.halt_reason && <div className="notice notice--error" role="alert">New testnet entries halted: {ledger.control.halt_reason}</div>}
    <div className="testnet-layout">
      <section className="testnet-panel" aria-labelledby="readiness-title">
        <div className="panel-heading"><h2 id="readiness-title">01 / Account readiness</h2><ShieldCheck size={17} /></div>
        <div className="testnet-body">
          <dl className="testnet-addresses"><div><dt>Account owner</dt><dd>{status?.account_address || "Not configured"}</dd></div>
            <div><dt>API wallet · public address</dt><dd>{status?.api_wallet_address || "Not configured"}</dd></div></dl>
          <p className="small-note">Set public addresses in the local .env file, then restart the API. Keep the API wallet private key in the separate owner signer environment.</p>
          <button className="button button--secondary" disabled={!!busy || !status} onClick={() => { void run("inspect"); }}>
            {busy === "inspect" ? <LoaderCircle size={16} className="spinner" /> : <ShieldCheck size={16} />}Check readiness</button>
          <div aria-live="polite">{inspection ? <>
            {inspection.error && <p className="form-error">{inspection.error}</p>}
            <ul className="testnet-checks">{inspection.checks.map(check => <li key={check.key}><span>{check.label}</span><strong className={check.status === "ok" ? "positive" : check.status === "blocked" ? "negative" : ""}>{check.status === "ok" ? <Check size={14} /> : null}{check.status}</strong></li>)}</ul>
            <dl className="testnet-observations"><div><dt>BTC · testnet</dt><dd>{money(inspection.market?.price)}</dd></div><div><dt>Account equity</dt><dd>{money(inspection.account?.equity)}</dd></div><div><dt>Withdrawable</dt><dd>{money(inspection.account?.withdrawable)}</dd></div></dl>
            <p className="small-note">Observation only. Every staging and submission rechecks fresh data.</p>
          </> : <p className="empty-note">Run a read-only check to see connectivity, funding and API wallet approval.</p>}</div>
        </div>
      </section>
      <section className="testnet-panel" aria-labelledby="intent-title">
        <div className="panel-heading"><h2 id="intent-title">02 / Review a local intent</h2><span className="tag">{money(status?.max_entry_notional, 0)} CAP</span></div>
        <div className="testnet-body">
          <p>Both agents must approve a BTC setup using testnet data. Coded risk checks resize it against the actual testnet balance.</p>
          {state?.service.market_source !== "hyperliquid-testnet" && <div className="notice">The tank uses {state?.service.market_source || "an unknown"} data. Switch MARKET_SOURCE to hyperliquid-testnet with a new paper database to create eligible reviews.</div>}
          <label>Reviewed setup<select value={episodeId} onChange={event => { setEpisodeId(event.target.value); setPreview(null); setMessage(""); }} disabled={!!busy}>
            <option value="">Select an approved setup</option>{episodes.map(ep => <option key={ep.id} value={ep.id}>BTC {ep.pitch.direction} · {ep.pitch.author} · {ep.id.slice(0, 8)}</option>)}</select></label>
          {!episodes.length && <p className="small-note">No approved setups available. Pitch a setup in the tank and wait for both verdicts.</p>}
          <button className="button button--secondary" disabled={!!busy || !episodeId} onClick={() => { void run("preview"); }}>{busy === "preview" ? <LoaderCircle size={16} className="spinner" /> : <ArrowRight size={16} />}Preview order size</button>
          {preview && <div className="testnet-preview" aria-live="polite"><p className={preview.eligible ? "positive" : "negative"}>{preview.reason}</p>
            {preview.order && <dl className="testnet-observations"><div><dt>Side / quantity</dt><dd>{preview.order.side} {number(preview.order.quantity, 6)} BTC</dd></div><div><dt>IOC price limit</dt><dd>{money(preview.order.price)}</dd></div><div><dt>Maximum notional</dt><dd>{money(Number(preview.order.quantity) * Number(preview.order.price))}</dd></div></dl>}</div>}
          <label>Operator token<input type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} placeholder="Local operator token" disabled={!!busy} /></label>
          <p className="small-note">Held in this tab only. Never enter a wallet private key here.</p>
          <button className="button button--primary" disabled={!!busy || !token || !preview?.eligible || preview.episode_id !== episodeId || !status?.operator_staging_available || !state?.service.operator_enabled} onClick={() => { void run("stage"); }}>
            {busy === "stage" ? <LoaderCircle size={16} className="spinner" /> : <ArrowRight size={16} />}Stage intent locally</button>
          <p className="small-note">Staging sends no exchange order. The owner controls submission through the separate testnet runner.</p>
        </div>
      </section>
    </div>
    <section className="testnet-panel" aria-labelledby="testnet-journal-title"><div className="panel-heading"><h2 id="testnet-journal-title">03 / Testnet execution journal</h2><span className="micro-label">SEPARATE LEDGER</span></div>
      <div className="testnet-body">
        <dl className="testnet-observations"><div><dt>Observed fill fees</dt><dd>{money(ledger?.observed_fill_fees)}</dd></div><div><dt>Observed closed PnL</dt><dd>{money(ledger?.observed_closed_pnl)}</dd></div><div><dt>Funding accounting</dt><dd>Not included</dd></div></dl>
        {ledger?.trades.length ? ledger.trades.map(trade => <article className="testnet-trade" key={trade.id}><div><strong>{trade.id.slice(0, 8)}</strong><span className="tag">{trade.status}</span></div><p>{trade.reason}</p><small>Filled {number(trade.filled_quantity, 6)} BTC · Protected {number(trade.protected_quantity, 6)} BTC</small>{trade.status === "staged" && <><button className="button button--secondary" disabled={!!busy || !token || !state?.service.operator_enabled} onClick={() => { void cancel(trade.id); }}>Cancel local intent</button><p className="small-note">Use the operator token above. Cancellation is allowed only before the runner prepares any exchange command.</p></>}</article>) : <p className="empty-note">No testnet intents recorded. Paper trades stay in the paper journal.</p>}
        {!!ledger?.events.length && <div className="event-list">{ledger.events.slice(-12).reverse().map(event => <div className="event-row" key={event.id}><time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString("en-GB", { hour12: false })}</time><span className="event-actor">{event.kind}</span><p>{event.message}</p></div>)}</div>}
      </div>
    </section>
  </div>;
}

"use client";

import { useEffect, useRef, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { money } from "@/lib/types";

type Reference = { address: string; equity: string; cashflows: string; funding_observed: string; initial_equity: string;
  net_equity_change_excluding_cashflows: string; observed_at: string; baseline_ms: number; day_reference_ms: number;
  halt_reason: string | null; stale: boolean; entry_permission: false; receipt_count: number; limits: string };

export function UserCapital({ address, token, now, onSessionInvalid }: {
  address: string; token: string; now: number; onSessionInvalid: () => void;
}) {
  const [data, setData] = useState<Reference | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  const stale = data && (data.stale || now - Date.parse(data.observed_at) > 15000);
  async function refresh() {
    const revision = ++generation.current;
    controller.current?.abort(); const current = new AbortController(); controller.current = current;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/v1/users/testnet/capital/refresh", { method: "POST", cache: "no-store",
        headers: { Authorization: "Bearer " + token }, signal: AbortSignal.any([current.signal, AbortSignal.timeout(30000)]) });
      if (response.status === 401) { onSessionInvalid(); return; }
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Capital observation is unavailable.");
      if (value.entry_permission !== false || value.reference?.address !== address || value.reference?.entry_permission !== false) throw new Error("Capital observations did not match this account.");
      if (!current.signal.aborted && revision === generation.current) setData(value.reference);
    } catch (failure) {
      if (!current.signal.aborted && revision === generation.current) { setData(null); setError(failure instanceof Error ? failure.message : "Capital observation failed."); }
    } finally { if (!current.signal.aborted && revision === generation.current) setBusy(false); }
  }
  return <section className="builder-consent" aria-labelledby="user-capital-title"><h3 id="user-capital-title">Observed loss references</h3>
    <p className="small-note">Start with a flat positive account. References begin at the first observation; earlier history is unknown. This monitor grants no entry permission.</p>
    <button className="button button--secondary" disabled={busy} onClick={() => { void refresh(); }}>{busy ? <LoaderCircle className="spinner" size={16} /> : <RefreshCw size={16} />}{busy ? "Reconciling…" : data ? "Refresh observations" : "Start observations"}</button>
    {error && <p className="form-error" role="alert">{error}</p>}
    {data && <div className="testnet-preview" aria-live="polite">
      <strong>{data.halt_reason ? "User risk halt · Owner review required" : "Observations recorded · Execution disabled"}</strong>
      {stale && <p className="notice">This observation is stale. Refresh before reviewing a new plan.</p>}
      {data.halt_reason && <p className="notice notice--error">{data.halt_reason}</p>}
      <dl className="testnet-observations"><div><dt>Observed equity</dt><dd>{money(data.equity)}</dd></div><div><dt>Net external cash flows</dt><dd>{money(data.cashflows)}</dd></div>
        <div><dt>Net equity change · flows excluded</dt><dd>{money(data.net_equity_change_excluding_cashflows, 4)}</dd></div><div><dt>Funding observed · already in equity</dt><dd>{money(data.funding_observed, 6)}</dd></div></dl>
      <p className="small-note">{data.receipt_count} deduplicated receipts since {new Date(data.baseline_ms).toLocaleString("en-GB")}. Daily reference observed {new Date(data.day_reference_ms).toLocaleString("en-GB")}.</p>
      <p className="small-note">{data.limits}</p>
    </div>}
  </section>;
}

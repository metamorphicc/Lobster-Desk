"use client";

import { useEffect, useState } from "react";
import { Activity, ChevronDown, CircleHelp, LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { number } from "@/lib/types";

type Operations = {
  schema: "lobster-local-readiness-v1"; scope: "local-paper-runtime"; observed_at: string; service_ready: boolean;
  market_age_seconds: number | null; checks: { key: string; label: string; status: "ok" | "blocked" }[];
  alerts: { code: string; severity: "critical" | "warning"; scope: string; message: string }[];
  paper: { pending_reviews: number; open_positions: number; reserved_entries: number } | null;
  review_budget: { day: string; used: number; limit: number; remaining: number } | null;
  entry_blockers: string[];
};

export function OpsStatus() {
  const [report, setReport] = useState<Operations | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true, busy = false;
    let controller: AbortController | undefined;
    async function load() {
      if (busy) return;
      busy = true; setLoading(true); controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 5000);
      try {
        const response = await fetch("/api/v1/ops/status", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error();
        const value = await response.json();
        if (value.schema !== "lobster-local-readiness-v1" || value.scope !== "local-paper-runtime" ||
            typeof value.service_ready !== "boolean" || !Array.isArray(value.checks) || !Array.isArray(value.alerts)) throw new Error();
        if (active) { setReport(value); setError(""); }
      } catch { if (active) { setReport(null); setError("Diagnostics are unavailable. Check or restart the local API, then retry."); } }
      finally { clearTimeout(timeout); busy = false; if (active) setLoading(false); }
    }
    void load();
    const timer = setInterval(() => { void load(); }, 10000);
    return () => { active = false; controller?.abort(); clearInterval(timer); };
  }, [refresh]);
  const critical = report?.alerts.filter(alert => alert.severity === "critical").length || 0;
  return <section className="ops-panel" aria-labelledby="ops-title">
    <div className="panel-heading"><h2 id="ops-title"><Activity size={16} /> Local paper runtime</h2><div className="ops-actions">
      <span role="status" className={`tag ${report ? report.service_ready ? "positive" : "negative" : ""}`}>{report ? report.service_ready ? "READY" : "NEEDS ATTENTION" : "UNKNOWN"}</span>
      <button className="text-button" disabled={loading} onClick={() => setRefresh(value => value + 1)}>{loading ? <LoaderCircle size={14} className="spinner" /> : <RefreshCw size={14} />}{loading ? "Checking…" : "Refresh checks"}</button></div></div>
    <div className="ops-body">
      {error && <div className="notice notice--error" role="alert">{error}</div>}
      <dl className="ops-metrics"><div><dt>Market age</dt><dd>{report?.market_age_seconds != null ? `${number(report.market_age_seconds, 1)} s` : "—"}</dd></div>
        <div><dt>Queued reviews</dt><dd>{report?.paper ? number(report.paper.pending_reviews, 0) : "—"}</dd></div>
        <div><dt>Review calls · UTC day</dt><dd>{report?.review_budget ? `${report.review_budget.used} / ${report.review_budget.limit}` : "—"}</dd></div>
        <div><dt>Critical alerts · all scopes</dt><dd className={critical ? "negative" : ""}>{report ? critical : "—"}</dd></div></dl>
      {report && <>
        <div aria-live="polite">{!!report.alerts.length && <ul className="ops-alerts">{report.alerts.map(alert => <li key={alert.code} className={alert.severity === "critical" ? "negative" : ""}>
          {alert.severity === "critical" ? <TriangleAlert size={17} /> : <CircleHelp size={17} />}<div><span className="micro-label">{alert.scope} / {alert.severity}</span><p>{alert.message}</p></div></li>)}</ul>}</div>
        <p className="small-note">{report.entry_blockers.length ? `Entry blockers observed: ${report.entry_blockers.join(" · ")}.` : report.service_ready ? "No global paper entry blockers observed. Each setup still needs its own coded approval." : "Service checks require attention before the local runtime can report ready."}</p>
        <details className="ops-details"><summary>Inspect runtime checks <ChevronDown size={15} /></summary><ul>{report.checks.map(check => <li key={check.key}><span>{check.label}</span><strong className={check.status === "ok" ? "positive" : "negative"}>{check.status}</strong></li>)}</ul></details>
        <p className="small-note">Observed {new Date(report.observed_at).toLocaleTimeString("en-GB", { hour12: false })}. Read-only local diagnostics; production and exchange execution remain unverified. Testnet alerts reflect its separate local journal.</p>
      </>}
    </div>
  </section>;
}

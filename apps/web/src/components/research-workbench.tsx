"use client";

/* Hallmark · component: research workbench · Midnight · P4 H4 E4 S5 R5 V4 */
import { useState } from "react";
import { Download, FlaskConical, LoaderCircle, RefreshCw } from "lucide-react";
import { useLocalReport } from "@/lib/use-local-report";
import { money, signed } from "@/lib/types";

type Metrics = { net_pnl: string; trade_count: number; max_drawdown_fraction: string; halted: boolean };
type Candidate = { strategy_hash: string; strategy: { name: string; family: string; hypothesis: string;
  lookback: number; fast: number; threshold_bps: number; stop_fraction: string; reward_risk: string; max_holding_bars: number };
  development: Metrics; validation: Metrics; stress: Metrics; holdout: Metrics | null; paper_candidate: boolean };
type Campaign = { id: string; created_at: string; source: string; status: string; reason: string;
  hypotheses: { regime: string } | null; critic: { verdict: string; summary: string; evidence: string[] } | null;
  selected_hash: string | null; evaluation: { candidates: Candidate[] } | null };
export type ResearchReport = { enabled: boolean; provider: string; active_id: string | null; interval_seconds: number;
  history_bars: number; calls_today: number; daily_call_limit: number; error: string | null;
  campaigns: Campaign[]; signals: { episode_id: string | null; signal_bar: number; strategy_hash: string; status: string; reason?: string }[] };

export function ResearchWorkbench({ onSelect }: { onSelect: (id: string) => void }) {
  const report = useLocalReport<ResearchReport>("/api/v1/research");
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState("");
  const [exported, setExported] = useState(false);
  async function download(id: string) {
    setExporting(id); setExportError(""); setExported(false);
    try {
      const response = await fetch(`/api/v1/research/${id}`, { cache: "no-store", signal: AbortSignal.timeout(15000) });
      if (!response.ok) throw new Error();
      const data = await response.json();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `research-${id.slice(0, 12)}.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setExported(true);
    } catch { setExportError("The evidence could not be exported. Retry after the local API is available."); }
    finally { setExporting(null); }
  }
  return <ResearchView {...report} exporting={exporting} exportError={exportError} exported={exported}
    onDownload={id => { void download(id); }} onSelect={onSelect} />;
}

export function ResearchView({ data, error, loading, refresh, exporting, exportError, exported, onDownload, onSelect }: {
  data: ResearchReport | null; error: string; loading: boolean; refresh: () => void;
  exporting: string | null; exportError: string; exported: boolean; onDownload: (id: string) => void; onSelect: (id: string) => void;
}) {
  return <div className="research-workbench">
    <section className="testnet-panel"><div className="panel-heading"><h2><FlaskConical size={16} /> Strategy laboratory</h2>
      <button className="text-button" disabled={loading} onClick={refresh}>{loading ? <LoaderCircle size={14} className="spinner" /> : <RefreshCw size={14} />}Refresh</button></div>
      <div className="testnet-body research-body">
        <p>Hypothesis → historical tests → independent veto → forward paper observation. Every candidate keeps its record.</p>
        {error && <p className="notice notice--error" role="alert">{error}</p>}
        {loading && !data && <p role="status">Loading research observations…</p>}
        {data && <><dl className="research-statistics"><div><dt>Research mode</dt><dd>{data.enabled ? "Autonomous paper" : "Disabled"}</dd></div>
          <div><dt>Hypothesis provider</dt><dd>{data.provider === "demo" ? "Scripted demo" : "Anthropic AI"}</dd></div>
          <div><dt>Research calls today</dt><dd>{data.calls_today} / {data.daily_call_limit}</dd></div>
          <div><dt>History / cadence</dt><dd>{data.history_bars} hours / {data.interval_seconds / 3600}h</dd></div></dl>
          {!data.enabled && <p className="notice">Autonomous research is off. The prepared agent preset starts it after a model API key is configured.</p>}
          {data.error && <p className="notice notice--error" role="alert">{data.error}</p>}
          <p className="small-note">60% development · 20% validation · 20% final holdout. Historical tests include funding and stressed fees/slippage. Forward paper fills currently exclude funding. Passing a test does not establish profitability.</p>
        </>}
      </div></section>
    {exportError && <p className="notice notice--error" role="alert">{exportError}</p>}
    {exported && <p className="research-success" role="status">Evidence exported. Source and simulation limitations are included.</p>}
    {data && !data.campaigns.length && <section className="testnet-panel"><div className="testnet-body"><h3>No research cohort yet.</h3>
      <p>{data.enabled ? "The worker is waiting for complete fresh history. The first cohort will appear here." : "You can still pitch setups manually or run the isolated no-key rehearsal."}</p></div></section>}
    {data?.campaigns.map((campaign, index) => <section className="testnet-panel research-campaign" key={campaign.id}>
      <div className="panel-heading"><h2>{campaign.id === data.active_id && campaign.status === "paper" ? "Current paper candidate" : "Research cohort"}</h2>
        <span className="tag">{campaign.status === "paper" ? "PAPER CANDIDATE" : campaign.status.replaceAll("_", " ").toUpperCase()}</span></div>
      <div className="testnet-body research-body"><p className="small-note"><time dateTime={campaign.created_at}>{new Date(campaign.created_at).toLocaleString("en-GB")}</time> · {campaign.source === "demo" ? "Synthetic history" : `${campaign.source} public history`} · {campaign.id.slice(0, 12)}</p>
        {campaign.hypotheses && <p>{campaign.hypotheses.regime}</p>}
        <p>{campaign.reason}</p>
        {campaign.critic && <div className="research-verdict"><strong>Critic / {campaign.critic.verdict.toUpperCase()}</strong><p>{campaign.critic.summary}</p>
          <ul>{campaign.critic.evidence.map((line, i) => <li key={i}>{line}</li>)}</ul></div>}
        <details open={index === 0}><summary>Inspect candidates</summary><div className="research-candidates">
          {campaign.evaluation?.candidates.map(candidate => <article className="research-candidate" key={candidate.strategy_hash}>
            <div className="research-candidate-title"><h3>{candidate.strategy.name}</h3><span className="tag">{candidate.strategy.family.replaceAll("_", " ")}</span></div>
            <p>{candidate.strategy.hypothesis}</p><p className="small-note">Lookback {candidate.strategy.lookback}h · Fast {candidate.strategy.fast}h · Threshold {candidate.strategy.threshold_bps} bps · Stop {Number(candidate.strategy.stop_fraction) * 100}% · R/R {candidate.strategy.reward_risk} · Time limit {candidate.strategy.max_holding_bars}h</p>
            <div className="research-results">{(["development", "validation", "stress", "holdout"] as const).map(window => <div key={window}>
              <span>{window === "stress" ? "Validation ×2 costs" : window}</span><strong className={Number(candidate[window]?.net_pnl || 0) < 0 ? "negative" : ""}>{candidate[window] ? signed(candidate[window]!.net_pnl) : "Not opened"}</strong>
              <small>{candidate[window] ? `${candidate[window]!.trade_count} trades · ${(Number(candidate[window]!.max_drawdown_fraction) * 100).toFixed(2)}% DD${candidate[window]!.halted ? " · Halted" : ""}` : "Reserved for the validation winner"}</small>
            </div>)}</div><p className="small-note">Each window starts with {money(1000)} simulated capital. {candidate.paper_candidate ? "Passed historical admission; critic and forward observation remain separate." : "Not admitted by the historical gates."}</p>
          </article>)}
          {!campaign.evaluation && <p>Candidate results are not available for this cohort.</p>}
        </div></details>
        <button className="button button--secondary" disabled={exporting !== null} onClick={() => onDownload(campaign.id)}>
          {exporting === campaign.id ? <LoaderCircle size={15} className="spinner" /> : <Download size={15} />}{exporting === campaign.id ? "Exporting…" : "Export evidence"}</button>
      </div></section>)}
    {!!data?.signals.length && <section className="testnet-panel"><div className="panel-heading"><h2>Recent strategy signals</h2></div><div className="testnet-body">
      {data.signals.map(signal => <div className="research-signal" key={`${signal.strategy_hash}-${signal.signal_bar}`}><div><strong>{signal.status === "pitched" ? "Entered review" : "Skipped"}</strong><p>{new Date(signal.signal_bar * 1000).toLocaleString("en-GB")} · {signal.strategy_hash.slice(0, 10)}</p>{signal.reason && <p>{signal.reason}</p>}</div>
        {signal.episode_id && <button className="text-link" onClick={() => onSelect(signal.episode_id!)}>Open setup</button>}</div>)}
    </div></section>}
  </div>;
}

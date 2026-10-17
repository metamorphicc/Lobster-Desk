"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowDownLeft, ArrowRight, ArrowUpRight, BookOpen, ChevronRight, CircleHelp, Download,
  FileClock, FlaskConical, Gauge, Landmark, LoaderCircle, Radio, ShieldCheck, SlidersHorizontal,
  Terminal, Waves, X } from "lucide-react";
import { Creature } from "./creature";
import { PriceChart } from "./price-chart";
import { UserAccount } from "./user-account";
import { ProjectActivity } from "./project-activity";
import { TestnetWorkbench } from "./testnet-workbench";
import { OpsStatus } from "./ops-status";
import { ResearchWorkbench } from "./research-workbench";
import { EconomicsPolicy } from "./economics-policy";
import { money, number, signed, statusLabel, type Episode, type Pitch, type Position, type State } from "@/lib/types";

type Tab = "tank" | "journal" | "research" | "treasury" | "testnet" | "mainnet";
const active = new Set(["queued", "analyzing", "risk_check", "capital_check", "approved", "filled"]);
const roles = [
  { name: "Clawdius", role: "Analyst", key: "analyst", kind: "lobster", line: "Find the setup. Defend the thesis." },
  { name: "Pinch", role: "Risk manager", key: "risk", kind: "crab", line: "First, tell me what we can lose." },
  { name: "Ledger", role: "Banker & executor", key: "banker", kind: "crayfish", line: "A good idea still needs a budget." },
] as const;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    let message = `The service returned ${response.status}. Try again.`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
    } catch { /* Keep the actionable HTTP error. */ }
    throw new Error(message);
  }
  return response.json();
}

function useDesk() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const next = await api<State>("/v1/state");
      if (alive.current) { setState(next); setError(null); }
      return next;
    } catch {
      if (alive.current) setError("The local API is unavailable. Start the project with npm run dev, then retry. Displayed data may be outdated.");
    } finally { busy.current = false; }
  }, []);
  useEffect(() => {
    alive.current = true;
    let events: EventSource | undefined;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    void refresh().then(initial => {
      if (!alive.current) return;
      events = new EventSource(`/api/v1/events?after=${initial?.last_event_id || 0}`);
      events.addEventListener("decision", () => {
        clearTimeout(timeout);
        timeout = setTimeout(() => { void refresh(); }, 120);
      });
    });
    const timer = setInterval(() => { void refresh(); }, 5000);
    return () => { alive.current = false; events?.close(); clearTimeout(timeout); clearInterval(timer); };
  }, [refresh]);
  return { state, error, refresh };
}

export function Desk() {
  const { state, error, refresh } = useDesk();
  const [tab, setTab] = useState<Tab>("tank");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const pitchDialog = useRef<HTMLDialogElement>(null);
  const helpDialog = useRef<HTMLDialogElement>(null);
  const operatorDialog = useRef<HTMLDialogElement>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const selected = state?.episodes.find(ep => ep.id === selectedId);
  const current = selected || state?.episodes.find(ep => active.has(ep.status)) || state?.episodes[0];
  const openPosition = state?.positions.find(p => p.status === "open");
  const pending = state?.episodes.filter(ep => active.has(ep.status) && ep.status !== "filled") || [];
  const pnl = openPosition && state?.market ?
    (Number(state.market.price) - Number(openPosition.entry_price)) * Number(openPosition.quantity) * (openPosition.direction === "long" ? 1 : -1) : 0;

  async function exportJournal() {
    setExporting(true); setExportError("");
    try {
      let cursor = 0;
      const all: unknown[] = [];
      while (true) {
        const batch = await api<{ events: { id: number }[] }>(`/v1/journal?after=${cursor}&limit=1000`);
        all.push(...batch.events);
        if (batch.events.length < 1000) break;
        cursor = batch.events.at(-1)!.id;
      }
      const url = URL.createObjectURL(new Blob([JSON.stringify({ exported_at: new Date().toISOString(), execution_mode: "paper", events: all }, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = "lobster-desk-journal.json"; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setExportError((e as Error).message); }
    finally { setExporting(false); }
  }

  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to tank</a>
    <aside className="sidebar">
      <a className="wordmark" href="/" aria-label="Lobster Desk home"><span className="brand-symbol"><Waves size={25} /></span><span>LOBSTER<span className="wordmark-bottom">DESK<span className="brand-period">.</span></span></span></a>
      <div className="sidebar-caption">A LITTLE COLLECTIVE INTELLIGENCE.</div>
      <nav aria-label="Main navigation">
        {([{ id: "tank", label: "The tank", icon: Radio }, { id: "journal", label: "Journal", icon: FileClock }, { id: "research", label: "Research", icon: BookOpen }, { id: "treasury", label: "Treasury", icon: Landmark }, { id: "testnet", label: "Testnet", icon: FlaskConical }, { id: "mainnet", label: "Mainnet", icon: Landmark }] as const).map(item =>
          <button key={item.id} className={`nav-item ${tab === item.id ? "is-current" : ""}`} aria-current={tab === item.id ? "page" : undefined} onClick={() => { setTab(item.id); if (item.id === "tank") setSelectedId(null); }}><item.icon size={18} /><span>{item.label}</span>{item.id === "tank" && <span className="nav-dot" />}</button>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="network-note"><span className="status-dot" /><span>Hyperliquid ecosystem</span><ArrowUpRight size={13} /></div>
        <p>Small positions.<br />Every decision on record.</p>
        <button className="text-button" onClick={() => helpDialog.current?.showModal()}><CircleHelp size={16} /> How it works</button>
        <div className="version-label">LOCAL PREVIEW · V0.1</div>
      </div>
    </aside>

    <div className="workspace">
      <header className="topbar">
        <div className="breadcrumb"><span>Lobster Desk</span><ChevronRight size={13} /><strong>{tab === "tank" ? "The tank" : tab === "journal" ? "Trade journal" : tab === "research" ? "Research" : tab === "testnet" ? "Testnet workbench" : tab === "mainnet" ? "Mainnet account" : "Treasury"}</strong></div>
        <div className="topbar-right"><span className="mode-badge"><FlaskConical size={13} /> {tab === "testnet" ? "TESTNET LAB" : tab === "mainnet" ? "MAINNET · REAL FUNDS" : "PAPER MODE"}</span><button className="icon-button" aria-label="Open operator controls" onClick={() => operatorDialog.current?.showModal()}><SlidersHorizontal size={17} /></button></div>
      </header>

      <main id="main">
        {error && <div className="notice notice--error" role="alert"><span>{error}</span><button onClick={() => { void refresh(); }}>Retry</button></div>}
        {state?.service.data_stale && <div className="notice" role="status">Market data is unavailable or stale. New entries are blocked. {state.service.market_error}</div>}
        {state?.service.worker_error && <div className="notice notice--error" role="alert">{state.service.worker_error}</div>}
        {(state?.account.paused || state?.account.halt_reason) && <div className="notice" role="status">New entries paused. {state.account.halt_reason || "The operator paused the tank. Existing position protection remains active."}</div>}

        <div className="page-heading">
          <div><h1>{tab === "tank" ? "The tank is in session." : tab === "journal" ? "Every call. On record." : tab === "research" ? "Let the hypotheses compete." : tab === "testnet" ? "Check before the first fill." : tab === "mainnet" ? "Your account. Your consent." : "Follow the money."}</h1><p>{tab === "tank" ? "The agents can research their next idea. Your pitches are welcome too." : tab === "journal" ? "Accepted, rejected, expired. The whole story stays here." : tab === "research" ? "Bounded rules. Reproducible tests. Forward paper observation." : tab === "testnet" ? "Inspect the account. Review the size. Stage a local intent." : tab === "mainnet" ? "Read your balance. Review exchange permissions and each exact trade." : "Capital, trading costs and revenue, accounted for separately."}</p></div>
          <button className="button button--primary" onClick={() => pitchDialog.current?.showModal()}><span>Pitch a setup</span><ArrowUpRight size={17} /></button>
        </div>

        {tab !== "testnet" && tab !== "mainnet" && <section className="account-strip" aria-label="Paper account performance">
          <Metric label="Tank equity" value={money(state?.account.equity)} note="Simulated USDC" />
          <Metric label="Net realized PnL" value={state ? signed(state.account.net_realized_pnl) : "—"} note="After modeled trading fees" tone={Number(state?.account.net_realized_pnl || 0) < 0 ? "negative" : ""} />
          <Metric label="Open PnL" value={state?.market ? signed(pnl) : "—"} note={openPosition ? "1 paper position" : "No open position"} />
          <Metric label="Risk per setup" value={state ? `${Number(state.policy.risk_fraction) * 100}%` : "—"} note="Maximum planned loss" />
        </section>}

        {tab === "tank" && <>
          <div className="tank-layout">
            <div className="main-column">
              <section className="tank-panel" aria-labelledby="tank-title">
                <div className="panel-heading"><h2 id="tank-title"><span className="status-dot" /> Inside the tank</h2><span className="micro-label">{state?.service.agent_provider === "anthropic" ? "AI REVIEWS" : "SCRIPTED DEMO"}</span></div>
                <div className="tank-scene">
                  <div className="scene-caption"><span className="scene-coordinate">BTC / USDC</span><span>EST. 2026</span></div>
                  <div className="porthole porthole--one" aria-hidden="true" /><div className="porthole porthole--two" aria-hidden="true" />
                  <div className="scene-waterline" aria-hidden="true" /><span className="scene-word" aria-hidden="true">THE TANK</span>
                  <div className="agents">
                    {roles.map(agent => {
                      const speaking = (agent.key === "analyst" && current?.status === "analyzing") || (agent.key === "risk" && current?.status === "risk_check") || (agent.key === "banker" && current?.status === "capital_check");
                      return <div className={`agent ${speaking ? "agent--speaking" : ""}`} key={agent.key}>
                        <span className={`agent-state ${speaking ? "is-speaking" : ""}`}>{speaking ? "Reviewing…" : current?.reviews[agent.key as "analyst" | "risk"] ? "Verdict recorded" : "At the desk"}</span>
                        <Creature kind={agent.kind} />
                        <div className="agent-nameplate"><strong>{agent.name}</strong><span>{agent.role}</span></div>
                      </div>;
                    })}
                  </div>
                  <div className="scene-caption scene-caption--bottom"><span><ShieldCheck size={12} /> Risk enforced in code</span><span>ONE MARKET. THREE PERSPECTIVES.</span></div>
                </div>
                <div className="agent-commentary">
                  {roles.map(agent => {
                    const review = current?.reviews[agent.key as "analyst" | "risk"];
                    const message = review?.summary || (agent.key === "banker" && current?.risk ? current.reason : agent.line);
                    return <div key={agent.key}><span className="commentary-name">{agent.name}<span>{review ? review.verdict === "approve" ? " / IN" : " / OUT" : ""}</span></span><p>{message}</p></div>;
                  })}
                </div>
                <div className="episode-bar"><span className="micro-label">{current ? `EP ${current.id.slice(0, 6).toUpperCase()}` : "AWAITING FIRST PITCH"}</span><span className={`verdict verdict--${current?.status || "idle"}`}>{current ? statusLabel(current.status) : "The floor is yours"}</span></div>
              </section>

              <section className="market-panel" aria-labelledby="market-title">
                <div className="market-header"><div><h2 id="market-title">BTC <span>/ USDC</span></h2><div className="market-price">{money(state?.market?.price)} <span className={Number(state?.market?.change_24h || 0) < 0 ? "negative" : "positive"}>{state?.market ? `${Number(state.market.change_24h) >= 0 ? "+" : ""}${number(state.market.change_24h)}%` : "—"}</span></div></div><div className="market-source"><span className="tag">1 MIN</span><span>{state?.market?.source === "hyperliquid" ? "Hyperliquid · live data" : state?.market?.source === "hyperliquid-testnet" ? "Hyperliquid · testnet data" : "Synthetic demo data"}</span></div></div>
                {state?.market ? <PriceChart market={state.market} episode={current} /> : <div className="chart-empty"><Waves size={30} /><p>Waiting for a market snapshot</p><span>The chart appears when the local data worker is ready.</span></div>}
                <div className="market-footer"><span>Funding / hour <strong>{state?.market ? `${number(Number(state.market.funding) * 100, 4)}%` : "—"}</strong></span><span>Open interest <strong>{state?.market ? `${number(state.market.open_interest, 0)} BTC` : "—"}</strong></span><span className="data-disclosure">{state?.market?.source === "demo" ? "All market figures are synthetic." : "Read-only market feed. Execution is simulated."}</span></div>
              </section>
            </div>

            <aside className="right-column">
              <section className="setup-panel"><div className="panel-heading"><h2>On the table</h2><BookOpen size={16} /></div>
                {current ? <Setup episode={current} position={state?.positions.find(p => p.episode_id === current.id)} /> : <div className="empty-setup"><span className="empty-icon"><ArrowUpRight size={24} /></span><h3>Got a thesis?</h3><p>Pitch a BTC setup. The tank checks the idea, the risk and the budget.</p><button className="button button--secondary" onClick={() => pitchDialog.current?.showModal()}>Take the floor <ArrowRight size={15} /></button><span className="small-note">Free to pitch. No trade guaranteed.</span></div>}
              </section>
              <section className="queue-panel"><div className="panel-heading"><h2>In the queue</h2><span className="count-label">{pending.length}</span></div>
                {pending.length ? pending.map(ep => <button className="queue-item" key={ep.id} onClick={() => setSelectedId(ep.id)}><span className={`direction-icon ${ep.pitch.direction}`}>{ep.pitch.direction === "long" ? <ArrowUpRight size={16} /> : <ArrowDownLeft size={16} />}</span><span><strong>BTC {ep.pitch.direction}</strong><small>{ep.pitch.author} · {statusLabel(ep.status)}</small></span><ChevronRight size={15} /></button>) : <p className="empty-note">No setups waiting.<br />Your idea could be next.</p>}
              </section>
              <div className="rules-note"><ShieldCheck size={21} /><div><strong>The house rules</strong><p>BTC only. One position. Up to 2× leverage. Every entry passes coded risk and capital checks.</p><button className="text-link" onClick={() => helpDialog.current?.showModal()}>Read the mechanics <ArrowRight size={13} /></button></div></div>
            </aside>
          </div>
          <Journal state={state} compact onSelect={id => { setSelectedId(id); setTab("journal"); }} />
        </>}

        {tab === "journal" && <>
          <ProjectActivity />
          <Journal state={state} onSelect={setSelectedId} />
          {current && <section className="detail-panel"><div className="panel-heading"><h2>Decision details</h2><span className="micro-label">{current.id.slice(0, 8)}</span></div><div className="detail-layout"><Setup episode={current} position={state?.positions.find(p => p.episode_id === current.id)} /><div className="review-details">{Object.entries(current.reviews).map(([role, review]) => review && <div key={role}><h3>{role === "analyst" ? "Clawdius · Analyst" : "Pinch · Risk manager"}</h3><p>{review.summary}</p><ul>{review.evidence.map(item => <li key={item}>{item}</li>)}</ul><small>{review.metadata.provider} / {review.metadata.model} · {review.metadata.input_tokens + review.metadata.output_tokens} tokens</small></div>)}{!Object.keys(current.reviews).length && <p className="empty-note">No reviews recorded yet. The worker will review this pitch when fresh market data is available.</p>}{current.approval_hash && <p className="hash-note">Approval binding <code>{current.approval_hash}</code></p>}</div></div></section>}
        </>}

        {tab === "treasury" && <Treasury state={state} />}
        {tab === "research" && <ResearchWorkbench onSelect={id => { setSelectedId(id); setTab("journal"); }} />}
        {tab === "testnet" && <TestnetWorkbench state={state} />}
        {tab === "mainnet" && <UserAccount key="mainnet" network="mainnet" episodes={state?.episodes || []} />}

        {tab !== "testnet" && tab !== "mainnet" && <section className="event-panel" aria-labelledby="event-title"><div className="panel-heading"><h2 id="event-title"><Terminal size={16} /> Decision feed</h2><button className="text-button" onClick={() => { void exportJournal(); }} disabled={exporting || !state}>{exporting ? <LoaderCircle size={14} className="spinner" /> : <Download size={14} />}{exporting ? "Exporting…" : "Export journal"}</button></div>
          {exportError && <p role="alert" className="form-error">{exportError}</p>}
          <div className="event-list">{state?.events.length ? state.events.slice(-12).reverse().map(event => <div className="event-row" key={event.id}><time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString("en-GB", { hour12: false })}</time><span className={`event-actor event-actor--${event.actor}`}>{event.actor}</span><p>{event.message}</p></div>) : <p className="empty-note">The journal starts when the local API is ready. Every decision and paper fill will appear here.</p>}</div>
        </section>}
        <OpsStatus />
        <footer className="footer"><span><Waves size={15} /> Lobster Desk</span><span>{tab === "testnet" ? "Testnet inspection & local staging · Separate owner signer" : `Paper execution · ${state?.service.agent_provider === "anthropic" ? "AI reviews" : "Scripted demo reviews"} · ${state?.account.funding_included ? "Hourly funding for tracked positions" : "Funding excluded"}`}</span><a href="https://hyperliquid.gitbook.io/hyperliquid-docs" target="_blank" rel="noreferrer">Hyperliquid docs <ArrowUpRight size={12} /></a></footer>
      </main>
    </div>

    <dialog ref={pitchDialog} className="modal" onClick={e => { if (e.target === e.currentTarget) pitchDialog.current?.close(); }}>
      <div className="modal-heading"><div><span className="micro-label">TAKE THE FLOOR</span><h2>Pitch your setup.</h2></div><button className="icon-button" aria-label="Close pitch form" onClick={() => pitchDialog.current?.close()}><X size={20} /></button></div>
      <PitchForm state={state} onSent={id => { setSelectedId(id); setTab("tank"); pitchDialog.current?.close(); void refresh(); }} />
    </dialog>
    <dialog ref={helpDialog} className="modal" onClick={e => { if (e.target === e.currentTarget) helpDialog.current?.close(); }}>
      <div className="modal-heading"><h2>How the tank works.</h2><button className="icon-button" aria-label="Close mechanics" onClick={() => helpDialog.current?.close()}><X size={20} /></button></div>
      <div className="help-content"><p>You can pitch a BTC setup, or enable autonomous research to let the agents propose and test bounded strategies. Every signal still needs independent reviews and coded risk approval.</p><ol><li><strong>Clawdius reviews the idea.</strong> The analyst evaluates the supplied market snapshot.</li><li><strong>Pinch challenges the risk.</strong> The reviewer can veto the setup.</li><li><strong>Ledger checks the budget.</strong> Code sizes the position and reserves capital.</li><li><strong>The executor waits for entry.</strong> Long entries trigger at or above the level; short entries at or below it. Gaps beyond 0.2% are not chased.</li></ol><p>Planned loss is capped at 0.25% of equity, with a 1% daily loss threshold and 5% maximum drawdown halt. Stops can slip. Protection in this local version runs while the service has fresh data; it is not an exchange-native stop.</p><p><strong>Current release:</strong> all trades use simulated project capital. Scripted demo reviews are labelled; real AI reviews require configured credentials. Anonymous pitches have no author entitlement. Sign in under Mainnet or Testnet to submit a wallet-attributed strategy. Eligible closed mainnet project trades split net profit 50% to the verified author and 50% to bot capital; paper results are not payable.</p><p><strong>Fees:</strong> paper results model 0.045% taker fees per fill and 0.02% adverse slippage. Hourly funding is reconciled for new tracked paper positions when enabled. Legacy positions retain their original accounting scope. The disclosed 0.05% entry builder fee allocates 0.02% to the team and 0.03% to bot capital. Real collection requires explicit exchange approval and execution.</p></div>
    </dialog>
    <dialog ref={operatorDialog} className="modal modal--small" onClick={e => { if (e.target === e.currentTarget) operatorDialog.current?.close(); }}>
      <div className="modal-heading"><h2>Operator controls</h2><button className="icon-button" aria-label="Close operator controls" onClick={() => operatorDialog.current?.close()}><X size={20} /></button></div>
      <Operator state={state} onDone={() => { void refresh(); }} />
    </dialog>
  </div>;
}

function Metric({ label, value, note, tone = "" }: { label: string; value: string; note: string; tone?: string }) {
  return <div className="metric"><span>{label}</span><strong className={tone}>{value}</strong><small>{note}</small></div>;
}

function Setup({ episode, position }: { episode: Episode; position?: Position }) {
  return <div className="setup-content"><div className="setup-title"><span className={`direction-icon ${episode.pitch.direction}`}>{episode.pitch.direction === "long" ? <ArrowUpRight size={20} /> : <ArrowDownLeft size={20} />}</span><h3>BTC <span>{episode.pitch.direction.toUpperCase()}</span></h3><span className="tag">{episode.pitch.leverage}×</span></div><p className="pitch-author">Pitched by <strong>{episode.pitch.author}</strong></p><p className="setup-thesis">{episode.pitch.thesis}</p><dl className="levels"><div><dt>Entry trigger</dt><dd>{money(episode.pitch.entry)}</dd></div><div><dt><span className="level-dot level-dot--stop" /> Stop loss</dt><dd>{money(episode.pitch.stop)}</dd></div><div><dt><span className="level-dot level-dot--target" /> Take profit</dt><dd>{money(episode.pitch.target)}</dd></div>{episode.risk?.approved && <><div><dt>Allocated notional</dt><dd>{money(episode.risk.notional)}</dd></div><div><dt>Planned loss</dt><dd>{money(episode.risk.planned_loss)}</dd></div></>}</dl><div className={`setup-verdict verdict--${episode.status}`}><span>{statusLabel(episode.status)}</span><p>{episode.reason}</p></div>{position && <><dl className="levels"><div><dt>Paper fill price</dt><dd>{money(position.entry_price)}</dd></div><div><dt>Filled quantity</dt><dd>{number(position.quantity, 5)} BTC</dd></div><div><dt>Total fill fees</dt><dd>{money(Number(position.entry_fee) + Number(position.exit_fee), 4)}</dd></div>{position.exit_price && <div><dt>Exit price</dt><dd>{money(position.exit_price)}</dd></div>}{position.net_pnl != null && <div><dt>Trade net PnL</dt><dd>{signed(position.net_pnl)}</dd></div>}</dl><p className="small-note">Fill {position.entry_fill_id.slice(0, 8)} · {position.market_source} prices{position.close_reason ? ` · Closed: ${position.close_reason}` : ""}</p></>}<span className="small-note">Paper trade · Project capital{episode.research ? ` · Strategy ${episode.research.strategy_hash.slice(0, 12)} · ${episode.research.max_holding_seconds / 3600}h time limit` : ""}</span></div>;
}

function Journal({ state, compact = false, onSelect }: { state: State | null; compact?: boolean; onSelect: (id: string) => void }) {
  const episodes = compact ? state?.episodes.slice(0, 5) : state?.episodes;
  return <section className="journal-panel"><div className="panel-heading"><h2>{compact ? "Recent calls" : "All setups"}</h2><span className="micro-label">{state?.episodes.length || 0} RECORDED</span></div>{episodes?.length ? <div className="table-wrap"><table><thead><tr><th>Setup / pitcher</th><th>Entry</th><th>Verdict</th><th>Net PnL</th><th><span className="sr-only">Details</span></th></tr></thead><tbody>{episodes.map(ep => { const position = state?.positions.find(p => p.episode_id === ep.id); return <tr key={ep.id}><td><strong className={ep.pitch.direction === "long" ? "positive" : "negative"}>{ep.pitch.direction === "long" ? "↗" : "↙"} BTC {ep.pitch.direction}</strong><small>{ep.pitch.author}</small></td><td>{money(ep.pitch.entry)}</td><td><span className={`verdict verdict--${ep.status}`}>{statusLabel(ep.status)}</span></td><td className={Number(position?.net_pnl || 0) < 0 ? "negative" : ""}>{position?.net_pnl != null ? signed(position.net_pnl) : "—"}</td><td><button className="icon-button" onClick={() => onSelect(ep.id)} aria-label={`View ${ep.pitch.author}'s ${ep.pitch.direction} setup`}><ArrowUpRight size={17} /></button></td></tr>; })}</tbody></table></div> : <div className="journal-empty"><FileClock size={22} /><div><strong>No calls on record yet.</strong><p>The first pitch starts the story. Rejections will be recorded too.</p></div></div>}</section>;
}

function PitchForm({ state, onSent }: { state: State | null; onSent: (id: string) => void }) {
  const [direction, setDirection] = useState<"long" | "short">("long");
  const [values, setValues] = useState({ author: "", entry: "", stop: "", target: "", thesis: "", leverage: "1" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const attempt = useRef<{ body: string; key: string } | null>(null);
  function validate(name: string, value: string) {
    if (name === "author") return /^[\p{L}\p{N}_ .-]{2,32}$/u.test(value.trim()) ? "" : "Use 2–32 letters, numbers, spaces, dots or hyphens.";
    if (["entry", "stop", "target"].includes(name)) return /^\d+(\.\d{1,2})?$/.test(value) && Number(value) > 0 && Number(value) <= 10000000 ? "" : "Use a positive price with up to 2 decimal places.";
    if (name === "thesis") return value.trim().length >= 20 ? "" : "Explain the setup in at least 20 characters.";
    return "";
  }
  function sample() {
    if (!state?.market) return;
    const price = Number(state.market.price);
    setValues(v => ({ ...v, author: v.author || "Tank guest", entry: (price * (direction === "long" ? 0.9997 : 1.0003)).toFixed(2),
      stop: (price * (direction === "long" ? 0.994 : 1.006)).toFixed(2), target: (price * (direction === "long" ? 1.012 : 0.988)).toFixed(2),
      thesis: "Example breakout setup for testing the review flow. These sample levels are not evidence of a trading edge." }));
    setFieldErrors({}); setError("");
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    const errors = Object.fromEntries(Object.entries(values).map(([name, value]) => [name, validate(name, value)]));
    setFieldErrors(errors);
    if (Object.values(errors).some(Boolean)) return;
    const pitch: Pitch = { ...values, author: values.author.trim(), thesis: values.thesis.trim(), symbol: "BTC", direction, leverage: Number(values.leverage) };
    const body = JSON.stringify(pitch);
    if (attempt.current?.body !== body) attempt.current = { body, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const result = await api<Episode>("/v1/pitches", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": attempt.current!.key }, body });
      attempt.current = null;
      onSent(result.id);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <form className="pitch-form" onSubmit={submit} noValidate>
    <p>The tank can accept, reject or let a setup expire. All execution uses simulated project funds.</p>
    <div className="direction-toggle" role="group" aria-label="Trade direction"><button type="button" className={direction === "long" ? "is-selected" : ""} aria-pressed={direction === "long"} onClick={() => setDirection("long")}><ArrowUpRight size={16} /> Long BTC</button><button type="button" className={direction === "short" ? "is-selected" : ""} aria-pressed={direction === "short"} onClick={() => setDirection("short")}><ArrowDownLeft size={16} /> Short BTC</button></div>
    <div className="form-grid">{([{ name: "author", label: "Your name", placeholder: "Tank guest" }, { name: "entry", label: "Entry trigger (USD)", placeholder: "68000.00" }, { name: "stop", label: "Stop loss (USD)", placeholder: "67600.00" }, { name: "target", label: "Take profit (USD)", placeholder: "68800.00" }] as const).map(field => <label key={field.name}>{field.label}<input name={field.name} autoComplete={field.name === "author" ? "nickname" : "off"} inputMode={field.name === "author" ? "text" : "decimal"} value={values[field.name]} placeholder={field.placeholder} maxLength={field.name === "author" ? 32 : 12} required aria-invalid={Boolean(fieldErrors[field.name])} aria-describedby={`error-${field.name}`} onBlur={() => setFieldErrors(e => ({ ...e, [field.name]: validate(field.name, values[field.name]) }))} onChange={e => { const value = e.target.value; setValues(v => ({ ...v, [field.name]: value })); if (fieldErrors[field.name]) setFieldErrors(f => ({ ...f, [field.name]: validate(field.name, value) })); }} /><span className="field-helper" id={`error-${field.name}`}>{fieldErrors[field.name]}</span></label>)}</div>
    <label>Leverage<select value={values.leverage} onChange={e => setValues(v => ({ ...v, leverage: e.target.value }))}><option value="1">1×</option><option value="2">2×</option></select></label>
    <label>Your thesis<textarea value={values.thesis} required minLength={20} maxLength={1200} placeholder="What makes this setup worth taking? What would invalidate it?" aria-invalid={Boolean(fieldErrors.thesis)} aria-describedby="error-thesis" onBlur={() => setFieldErrors(e => ({ ...e, thesis: validate("thesis", values.thesis) }))} onChange={e => setValues(v => ({ ...v, thesis: e.target.value }))} /><span className="field-helper" id="error-thesis">{fieldErrors.thesis || `${values.thesis.length}/1200 characters`}</span></label>
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="form-actions"><button type="button" className="text-button" disabled={!state?.market || busy} onClick={sample}>Use sample levels</button><button className="button button--primary" type="submit" disabled={busy || !state} aria-busy={busy}>{busy ? <><LoaderCircle size={16} className="spinner" /> Sending…</> : <>Send to the tank <ArrowUpRight size={16} /></>}</button></div>
    <span className="small-note">Sample levels test the interface. They are not a market recommendation.</span>
  </form>;
}

function Treasury({ state }: { state: State | null }) {
  const [volume, setVolume] = useState("1000000");
  const [fee, setFee] = useState("0.05");
  return <div className="treasury-grid"><EconomicsPolicy /><section className="treasury-panel"><div className="panel-heading"><h2>Paper capital ledger</h2><Landmark size={17} /></div><dl className="levels"><div><dt>Initial simulated deposit</dt><dd>{money(state?.account.initial_capital)}</dd></div><div><dt>Current cash</dt><dd>{money(state?.account.cash)}</dd></div><div><dt>Modeled trading fees paid</dt><dd>{money(state?.account.fees_paid, 4)}</dd></div><div><dt>Net realized PnL</dt><dd>{state ? signed(state.account.net_realized_pnl) : "—"}</dd></div><div><dt>Collected builder fees</dt><dd>{money(state?.account.builder_revenue)}</dd></div><div><dt>Buybacks / distributions</dt><dd>Not enabled</dd></div></dl><p className="empty-note">Deposits are separate from earnings. {state?.account.funding_included ? `Hourly funding: ${money(state.account.funding_net, 4)}. ${state.account.funding_scope || ""}` : "Funding accounting is disabled."} Fees on open trades are expensed when filled.</p></section><section className="treasury-panel"><div className="panel-heading"><h2>Fee revenue calculator</h2><Gauge size={17} /></div><p className="empty-note">Illustration only. Revenue is recorded only after actual received-fee reconciliation.</p><div className="calculator"><label>Executed entry volume (USD)<input type="number" min="0" max="1000000000000" value={volume} onChange={e => setVolume(e.target.value)} /></label><label>Builder fee (%)<input type="number" min="0" max="0.1" step="0.001" value={fee} onChange={e => setFee(e.target.value)} /></label><div className="calculator-result"><span>Hypothetical gross revenue</span><strong>{Number(volume) >= 0 && Number(fee) >= 0 && Number(fee) <= 0.1 ? money(Number(volume) * Number(fee) / 100) : "—"}</strong><small>Before models, infrastructure, support and other costs.</small></div></div></section><section className="treasury-roadmap"><h2>User-owned trading</h2><p>Connect a wallet in Testnet or Mainnet to review permissions and exact order consent. A separate armed runner is required. User funds and positions remain separate from the tank; mainnet signing and the separate runner are opt-in and default off.</p><span className="tag">OPT-IN · DEFAULT OFF</span></section></div>;
}

function Operator({ state, onDone }: { state: State | null; onDone: () => void }) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function act(action: string) {
    setBusy(true); setMessage("");
    try { await api("/v1/operator", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ action }) }); setMessage(`Operator action recorded: ${action}.`); onDone(); }
    catch (e) { setMessage((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="operator-content"><p>Controls affect paper trading only. Risk halts cannot be cleared with Resume.</p>{!state?.service.operator_enabled ? <p className="notice">Controls are disabled. Set a local OPERATOR_TOKEN of at least 24 characters and restart the API.</p> : <><label>Operator token<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label><div className="operator-actions">{["pause", "resume", "close"].map(action => <button key={action} className="button button--secondary" disabled={busy || !token} onClick={() => { void act(action); }}>{action === "close" ? "Close position" : action === "pause" ? "Pause entries" : "Resume entries"}</button>)}</div><p className="small-note">The token stays in this tab’s memory and is never saved to browser storage.</p></>}{message && <p role="status">{message}</p>}</div>;
}


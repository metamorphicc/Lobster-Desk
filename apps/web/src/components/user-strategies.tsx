"use client";

/* Hallmark · component: strategy submission and earnings · Midnight
 * pre-emit critique: P4 H4 E4 S5 R5 V4 · existing layout/tokens
 * states: default/hover/focus/active/disabled/loading/error/success */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { money, signed } from "@/lib/types";

export type Earnings = { network: "testnet" | "mainnet"; payout_submission_enabled: false;
  payout_jobs?: { id: string; status: string; amount: string }[];
  strategies: { attribution: { strategy_id: string }; episode_id: string }[];
  balance: null | { net_realized_profit: string; entitlement: string; paid: string; outstanding: string }; note: string };
const initial = { author: "", entry: "", stop: "", target: "", thesis: "" };

export function UserStrategies({ network, token, onSessionInvalid }: { network: "testnet" | "mainnet"; token: string; onSessionInvalid: () => void }) {
  const [values, setValues] = useState(initial), [direction, setDirection] = useState("long");
  const [data, setData] = useState<Earnings | null>(null), [busy, setBusy] = useState("");
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const pending = useRef<{ body: string; key: string } | null>(null);
  const invalid = useRef(onSessionInvalid); invalid.current = onSessionInvalid;
  const identity = network + ":" + token, active = useRef(identity); active.current = identity;
  const prefix = `/api/v1/users/${network}`;

  async function refresh(signal?: AbortSignal) {
    const response = await fetch(prefix + "/strategy-earnings", { cache: "no-store", headers: { Authorization: "Bearer " + token },
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000) });
    if (active.current !== identity) return;
    if (response.status === 401) { invalid.current(); return; }
    if (!response.ok) throw new Error("Strategy earnings are unavailable.");
    const value = await response.json();
    if (value.network !== network || value.payout_submission_enabled !== false || !Array.isArray(value.strategies)) throw new Error("Unexpected strategy earnings response.");
    if (!signal?.aborted && active.current === identity) setData(value);
  }
  useEffect(() => {
    const current = new AbortController();
    setData(null); setError(""); setNotice("");
    void refresh(current.signal).catch(() => { if (!current.signal.aborted) setError("Strategy earnings are unavailable. Refresh to retry."); });
    return () => { current.abort(); request.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = JSON.stringify({ ...values, direction, symbol: "BTC", leverage: 1 });
    if (pending.current?.body !== body) pending.current = { body, key: crypto.randomUUID() };
    request.current?.abort(); const current = new AbortController(); request.current = current;
    setBusy("submit"); setError(""); setNotice("");
    try {
      const response = await fetch(prefix + "/strategy-pitches", { method: "POST", cache: "no-store",
        headers: { Authorization: "Bearer " + token, "Content-Type": "application/json", "Idempotency-Key": pending.current.key },
        body, signal: AbortSignal.any([current.signal, AbortSignal.timeout(15000)]) });
      if (current.signal.aborted || active.current !== identity) return;
      if (response.status === 401) { invalid.current(); return; }
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Check the setup fields and retry.");
      if (!value.strategy_attribution || value.strategy_attribution.network !== network) throw new Error("Strategy ownership was not confirmed.");
      pending.current = null; setNotice("Strategy submitted with verified wallet attribution. Reviews and risk checks still decide whether the bot trades it.");
      setValues(initial); await refresh(current.signal);
    } catch (failure) { if (!current.signal.aborted && active.current === identity) setError(failure instanceof Error ? failure.message : "Strategy submission unavailable."); }
    finally { if (!current.signal.aborted && active.current === identity) setBusy(""); }
  }
  async function reload() {
    request.current?.abort(); const current = new AbortController(); request.current = current;
    setBusy("refresh"); setError("");
    try { await refresh(current.signal); } catch { if (!current.signal.aborted && active.current === identity) { setData(null); setError("Strategy earnings are unavailable."); } }
    finally { if (!current.signal.aborted) setBusy(""); }
  }
  return <UserStrategiesView network={network} data={data} values={values} direction={direction} busy={busy} error={error} notice={notice}
    setValues={setValues} setDirection={setDirection} submit={submit} reload={reload} />;
}

export function UserStrategiesView({ network, data, values, direction, busy, error, notice, setValues, setDirection, submit, reload }: {
  network: "testnet" | "mainnet"; data: Earnings | null; values: typeof initial; direction: string; busy: string; error: string; notice: string;
  setValues: (value: typeof initial) => void; setDirection: (value: string) => void;
  submit: (event: FormEvent) => void | Promise<void>; reload: () => void | Promise<void>;
}) {
  return <section className="builder-consent"><h3>Your strategies and profit share</h3>
    <p className="small-note">Submit a BTC setup attributed to this verified wallet. Closed project trades allocate 50% of net strategy profit to you and 50% to bot capital, after trading fees, funding and strategy loss recovery. Anonymous pitches cannot be claimed later.</p>
    {network === "testnet" && <p className="notice">Testnet strategy results use test funds and create no payable balance.</p>}
    <StrategyEarningsView data={data} />
    <form className="pitch-form" onSubmit={event => { void submit(event); }}>
      <label>Display name<input required minLength={2} maxLength={32} value={values.author} onChange={event => setValues({ ...values, author: event.target.value })} /></label>
      <label>Direction<select value={direction} onChange={event => setDirection(event.target.value)}><option value="long">Long BTC</option><option value="short">Short BTC</option></select></label>
      <div className="form-grid">{([['entry', 'Entry trigger (USD)'], ['stop', 'Stop loss (USD)'], ['target', 'Take profit (USD)']] as const).map(([key, label]) => <label key={key}>{label}
        <input required inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,2})?" value={values[key]} onChange={event => setValues({ ...values, [key]: event.target.value })} /></label>)}</div>
      <label>Strategy thesis<textarea required minLength={20} maxLength={1200} value={values.thesis} onChange={event => setValues({ ...values, thesis: event.target.value })} /></label>
      <p className="small-note">BTC only · 1× leverage · Every setup still needs agent approval and coded risk/capital checks.</p>
      <button className="button button--secondary" type="submit" disabled={!!busy}>{busy === "submit" && <LoaderCircle size={15} className="spinner" />}{busy === "submit" ? "Submitting…" : "Submit attributed strategy"}</button>
    </form>
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="positive" role="status">{notice}</p>}
    <button className="text-button" disabled={!!busy} onClick={() => { void reload(); }}><RefreshCw size={14} />Refresh earnings</button>
  </section>;
}

export function StrategyEarningsView({ data }: { data: Earnings | null }) {
  return data ? <div className="testnet-preview"><p className="small-note">{data.strategies.length} wallet-attributed strategies.</p>
    <dl className="testnet-observations"><div><dt>Net realized strategy profit</dt><dd>{signed(data.balance?.net_realized_profit || "0")}</dd></div>
      <div><dt>Your earned share</dt><dd>{money(data.balance?.entitlement || "0")}</dd></div><div><dt>Observed payments</dt><dd>{money(data.balance?.paid || "0")}</dd></div>
      <div><dt>Outstanding share</dt><dd>{money(data.balance?.outstanding || "0")}</dd></div></dl><p className="small-note">{data.note}</p>
    {!!data.payout_jobs?.length && <ul className="user-position-list">{data.payout_jobs.map(job => <li key={job.id}><strong>Author payment · {job.status}</strong><span>{money(job.amount)} USDC</span></li>)}</ul>}
  </div> : <p className="small-note">Your private strategy earnings appear after the account check.</p>;
}

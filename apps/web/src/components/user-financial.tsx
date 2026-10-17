"use client";

/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4
 * component: financial consent · genre: atmospheric · theme: Midnight
 * states: default · hover · focus · active · disabled · loading · error · success */
import { useEffect, useId, useRef, useState } from "react";
import { FileCheck2, LoaderCircle, RefreshCw, ShieldCheck } from "lucide-react";
import type { WalletSession } from "@/lib/wallet";
import { validateFinancialContext, validateFinancialJob, type FinancialContext, type FinancialJob, type FinancialKind, type BoundPlan } from "@/lib/user-financial";

const prefix = "/api/v1/users/testnet/financial";
const labels = { agent: "API wallet delegation", builder: "Builder fee approval", revoke_builder: "Builder fee revocation", trade: "Exact trade consent" };

export function UserFinancial({ address, token, session, now, plan, onSessionInvalid }: {
  address: string; token: string; session: WalletSession; now: number; plan?: BoundPlan; onSessionInvalid: () => void;
}) {
  const [context, setContext] = useState<FinancialContext | null>(null);
  const [review, setReview] = useState<FinancialJob | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null);
  const heading = useId();
  const callbacks = useRef(onSessionInvalid); callbacks.current = onSessionInvalid;
  const identity = address + ":" + token;
  const activeIdentity = useRef(identity); activeIdentity.current = identity;
  async function read(signal?: AbortSignal) {
    const response = await fetch(prefix, { headers: { Authorization: "Bearer " + token }, cache: "no-store",
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000) });
    if (response.status === 401) { if (activeIdentity.current === identity) callbacks.current(); throw new Error("Private session expired."); }
    if (!response.ok) throw new Error("Financial context is unavailable.");
    const value = await response.json();
    if (activeIdentity.current !== identity) throw new Error("Private financial identity changed.");
    return validateFinancialContext(value, address);
  }
  useEffect(() => {
    const request = new AbortController();
    const load = () => { void read(request.signal).then(setContext).catch(() => { if (!request.signal.aborted) setError("Financial context is unavailable. Refresh to inspect the queue."); }); };
    load(); const timer = setInterval(load, 5000);
    return () => { request.abort(); clearInterval(timer); controller.current?.abort(); };
    // The identity/token define this private view; callbacks are read through a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address, token]);

  async function prepare(kind: FinancialKind) {
    if (!context?.enabled || !context.profile || busy) return;
    controller.current?.abort(); const request = new AbortController(); controller.current = request;
    setBusy("prepare"); setError(""); setNotice(""); setReview(null);
    try {
      const response = await fetch(prefix + "/jobs", { method: "POST", cache: "no-store", headers: { Authorization: "Bearer " + token,
        "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ kind, ...(kind === "trade" ? { plan_id: plan?.id } : {}) }),
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(10000)]) });
      if (response.status === 401) { callbacks.current(); return; }
      if (!response.ok) throw new Error("A fresh financial review could not be prepared.");
      const value = validateFinancialJob(await response.json(), context.profile, kind, window.location.origin, session.snapshot().chainId || "", plan);
      if (!request.signal.aborted) setReview(value);
    } catch (failure) { if (!request.signal.aborted) setError(failure instanceof Error ? failure.message : "Financial review unavailable."); }
    finally { if (!request.signal.aborted) setBusy(""); }
  }

  async function sign() {
    if (!review || !context?.profile || !context.enabled || busy) return;
    controller.current?.abort(); const request = new AbortController(); controller.current = request;
    setBusy("sign"); setError(""); setNotice("");
    try {
      const signature = await session.signFinancial(review, context.profile, review.kind, window.location.origin, plan);
      if (request.signal.aborted) return;
      const response = await fetch(`${prefix}/jobs/${review.id}/proof`, { method: "POST", cache: "no-store",
        headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" }, body: JSON.stringify({ signature }),
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(10000)]) });
      if (response.status === 401) { callbacks.current(); return; }
      if (!response.ok) throw new Error("Financial proof was not confirmed. Refresh the queue before preparing another.");
      const result = await response.json();
      if (result.id !== review.id || result.owner !== address || result.proof !== null || result.submission_from_api !== false) throw new Error("Unexpected proof response. Inspect the queue.");
      if (!request.signal.aborted) { setReview(null); setNotice("Financial consent queued. The separate runner must still confirm exchange execution."); setContext(await read(request.signal)); }
    } catch (failure) {
      if (!request.signal.aborted) {
        const code = failure && typeof failure === "object" ? (failure as { code?: number }).code : null;
        setError(code === 4001 ? "Wallet signing declined. Refresh before another attempt." : failure instanceof Error ? failure.message : "Financial proof outcome is uncertain. Inspect the queue.");
      }
    } finally { if (!request.signal.aborted) setBusy(""); }
  }

  async function refresh() {
    controller.current?.abort(); const request = new AbortController(); controller.current = request;
    setBusy("refresh"); setError("");
    try { const data = await read(request.signal); if (!request.signal.aborted) setContext(data); }
    catch { if (!request.signal.aborted) setError("Private financial status could not be refreshed."); }
    finally { if (!request.signal.aborted) setBusy(""); }
  }
  return <section className="builder-consent financial-workbench" aria-labelledby={heading}>
    <h3 id={heading}>{plan ? "Execute this reviewed order" : "Exchange permissions"}</h3>
    <p className="small-note">Explicit testnet financial signatures. Delegation permits the dedicated API wallet to trade; builder approval permits the displayed fee. A disconnected browser does not revoke either permission.</p>
    {!context && !error && <p role="status"><LoaderCircle size={14} className="spinner" />Loading private financial context…</p>}
    {context && !context.enabled && <p className="notice">Financial signing is disabled in this workspace. The operator must enable the separate testnet path.</p>}
    {context && !context.profile && <p className="notice">A dedicated API-wallet profile must be registered before preparing financial consent.</p>}
    {context?.profile && <><dl className="testnet-observations financial-identities"><div><dt>Dedicated API wallet</dt><dd><code>{context.profile.agent}</code></dd></div>
      <div><dt>Builder · entry fee</dt><dd><code>{context.profile.builder}</code><span>{context.profile.fee_tenths_bps / 1000}%</span></dd></div></dl>
      <div className="financial-actions">{plan ? <button className="button button--secondary" disabled={!!busy || !context.enabled || now >= Date.parse(plan.expires_at)} onClick={() => { void prepare("trade"); }}><FileCheck2 size={15} />Review trade consent</button> :
        <>{(["agent", "builder", "revoke_builder"] as const).map(kind => <button key={kind} className="button button--secondary" disabled={!!busy || !context.enabled}
          onClick={() => { void prepare(kind); }}>{kind === "agent" ? "Review API wallet" : kind === "builder" ? "Review builder fee" : "Review fee revocation"}</button>)}</>}
      </div></>}
    {busy && <p role="status"><LoaderCircle size={14} className="spinner" />{busy === "sign" ? "Waiting for wallet and proof confirmation…" : "Checking financial context…"}</p>}
    {review && <FinancialReview job={review} expired={now >= review.expires_ms} busy={!!busy || !context?.enabled} sign={() => { void sign(); }} />}
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="positive" role="status"><ShieldCheck size={15} />{notice}</p>}
    {!!context?.jobs.length && <div className="financial-jobs"><h4>Permission and consent queue</h4><ul className="user-position-list">{context.jobs.slice(-6).reverse().map(job =>
      <li key={job.id}><strong>{labels[job.kind]} · {job.status}</strong><code>{job.id.slice(0, 12)}</code>{job.status === "unknown" && <span>Uncertain command; fresh entries are blocked pending review.</span>}</li>)}</ul></div>}
    {!!context?.execution?.trades.length && <div className="financial-jobs"><h4>Exchange journal</h4><ul className="user-position-list">{context.execution.trades.slice(0, 4).map(trade =>
      <li key={trade.id}><strong>BTC · {trade.status}</strong><span>Filled {trade.filled_quantity} · Protected {trade.protected_quantity}</span><span>{trade.reason}</span></li>)}</ul></div>}
    <button className="text-button" disabled={!!busy} onClick={() => { void refresh(); }}><RefreshCw size={14} />Refresh financial status</button>
  </section>;
}

export function FinancialReview({ job, expired, busy, sign }: { job: FinancialJob; expired: boolean; busy: boolean; sign: () => void }) {
  return <div className="testnet-preview financial-review"><strong>{labels[job.kind]} · TESTNET</strong>
    <p className="small-note">Review the exact payload below. Local queue deadline {new Date(job.expires_ms).toLocaleTimeString("en-GB", { hour12: false })}. SDK permissions persist until revoked.</p>
    {job.kind === "trade" && <p className="hash-note">Binds the quantity, limit, leverage, stops and fee shown in preview <code>{job.plan_hash}</code>.</p>}
    <pre className="auth-message">{JSON.stringify(job.typed_data, null, 2)}</pre>
    {expired && <p className="notice">Review expired. Prepare a fresh plan before signing.</p>}
    <button className="button button--secondary" disabled={busy || expired} onClick={sign}>{busy ? <LoaderCircle size={15} className="spinner" /> : <ShieldCheck size={15} />}{job.kind === "trade" ? "Sign trade consent" : "Sign permission"}</button>
  </div>;
}

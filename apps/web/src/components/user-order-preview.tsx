"use client";

import { useEffect, useRef, useState } from "react";
import { Download, FileCheck2, LoaderCircle } from "lucide-react";
import { money, number, type Episode } from "@/lib/types";
import { UserConsent } from "./user-consent";
import { UserFinancial } from "./user-financial";
import type { WalletSession } from "@/lib/wallet";

type Preview = {
  id: string; schema: string; address: string; episode_id: string; expires_at: string; expired: boolean; plan_hash: string;
  executable: false; signed: false; submitted: false; nonce_reserved: false; order_submission_enabled: false; fee_collection_enabled: false;
  entry: { side: string; quantity: string; limit_price: string; leverage: number };
  per_trade: { notional: string; margin: string; planned_loss_including_estimated_costs: string; risk_budget: string };
  fees: { entry_exchange_estimate: string; entry_builder_hypothetical: string; stop_roundtrip_estimate: string };
  protection_templates: { stop_trigger: string; target_trigger: string }; execution_blockers: string[]; assumptions: string;
};

export function UserOrderPreview({ address, token, episodes, now, session, onSessionInvalid }: {
  address: string; token: string; episodes: Episode[]; now: number; session: WalletSession; onSessionInvalid: () => void;
}) {
  const [selected, setSelected] = useState("");
  const [plan, setPlan] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const pendingKey = useRef<string | null>(null);
  const eligible = episodes.filter(ep => ["approved", "filled"].includes(ep.status) && ep.approval_hash && ep.snapshot?.source === "hyperliquid-testnet" && Date.parse(ep.expires_at) > now);
  useEffect(() => () => controller.current?.abort(), []);
  const expired = plan && (plan.expired || now >= Date.parse(plan.expires_at));

  async function preview() {
    const current = new AbortController(); controller.current?.abort(); controller.current = current;
    pendingKey.current ||= crypto.randomUUID();
    setBusy(true); setError(""); setPlan(null);
    try {
      const response = await fetch("/api/v1/users/testnet/order-preview", { method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token, "Idempotency-Key": pendingKey.current },
        body: JSON.stringify({ episode_id: selected }), signal: AbortSignal.any([current.signal, AbortSignal.timeout(20000)]) });
      if (current.signal.aborted) return;
      if (response.status === 401) { onSessionInvalid(); return; }
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "User preview is unavailable. Retry with a fresh session and observations.");
      if (value.schema !== "lobster-user-order-preview-v1" || value.address !== address || value.episode_id !== selected ||
          [value.executable, value.signed, value.submitted, value.nonce_reserved, value.order_submission_enabled, value.fee_collection_enabled].some(flag => flag !== false) ||
          !Number.isFinite(Date.parse(value.expires_at)) || !Array.isArray(value.execution_blockers) || !value.entry || !value.fees || !value.per_trade || !value.protection_templates) throw new Error("The preview did not match this user or disabled execution scope.");
      if (!current.signal.aborted) { setPlan(value); pendingKey.current = null; }
    } catch (failure) { if (!current.signal.aborted) setError(failure instanceof Error ? failure.message : "Preview unavailable."); }
    finally { if (!current.signal.aborted) setBusy(false); }
  }
  function download() {
    if (!plan || plan.expired || Date.now() >= Date.parse(plan.expires_at)) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `lobster-user-preview-${plan.id}.json`; link.click(); URL.revokeObjectURL(url);
  }

  return <section className="builder-consent" aria-labelledby="user-order-title"><h3 id="user-order-title">Preview an agent-reviewed user order</h3>
    <p className="small-note">Private illustration using this user&apos;s fresh balance. Maximum $50 notional. No exchange nonce, capital reservation, signature or order is created.</p>
    <label>Approved testnet setup<select value={selected} disabled={busy} onChange={event => { controller.current?.abort(); setSelected(event.target.value); setPlan(null); setError(""); pendingKey.current = null; }}>
      <option value="">Select a reviewed setup</option>{eligible.map(ep => <option key={ep.id} value={ep.id}>BTC {ep.pitch.direction} · {ep.pitch.author} · {ep.id.slice(0, 8)}</option>)}</select></label>
    {!eligible.length && <p className="notice">No unexpired setup reviewed against testnet data is available. The tank must review one first; demo or mainnet-market reviews cannot be used here.</p>}
    <button className="button button--secondary" disabled={busy || !eligible.some(ep => ep.id === selected)} onClick={() => { void preview(); }}>{busy ? <LoaderCircle size={16} className="spinner" /> : <FileCheck2 size={16} />}{busy ? "Checking…" : "Preview user order"}</button>
    {error && <p className="form-error" role="alert">{error}</p>}
    {plan && <><UserOrderReport plan={plan} expired={!!expired} busy={busy} download={download} />
      <UserConsent key={plan.id} address={address} token={token} plan={plan} now={now} onSessionInvalid={onSessionInvalid} /></>}
    {plan && <UserFinancial key={"financial-" + plan.id} address={address} token={token} session={session} now={now} plan={plan} onSessionInvalid={onSessionInvalid} />}
  </section>;
}

export function UserOrderReport({ plan, expired, busy, download }: { plan: Preview; expired: boolean; busy: boolean; download: () => void }) {
  return <div className="testnet-preview" aria-live="polite"><strong>Illustration saved · Execution blocked</strong>
      <dl className="testnet-observations"><div><dt>BTC · {plan.entry.side}</dt><dd>{number(plan.entry.quantity, 6)}</dd></div><div><dt>Entry limit</dt><dd>{money(plan.entry.limit_price)}</dd></div><div><dt>Notional</dt><dd>{money(plan.per_trade.notional)}</dd></div>
        <div><dt>Planned stop loss · costs included</dt><dd>{money(plan.per_trade.planned_loss_including_estimated_costs, 4)}</dd></div><div><dt>Per-trade risk budget</dt><dd>{money(plan.per_trade.risk_budget, 4)}</dd></div><div><dt>Margin · {plan.entry.leverage}× isolated</dt><dd>{money(plan.per_trade.margin)}</dd></div>
        <div><dt>Stop trigger template</dt><dd>{money(plan.protection_templates.stop_trigger)}</dd></div><div><dt>Target trigger template</dt><dd>{money(plan.protection_templates.target_trigger)}</dd></div>
        <div><dt>Entry exchange fee · estimated</dt><dd>{money(plan.fees.entry_exchange_estimate, 6)}</dd></div><div><dt>Entry builder fee · hypothetical</dt><dd>{money(plan.fees.entry_builder_hypothetical, 6)}</dd></div></dl>
      <p className="small-note">Protective size must follow the actual confirmed entry fill. These templates install no exchange protection.</p>
      <ul className="user-position-list">{plan.execution_blockers.map(reason => <li key={reason}>{reason}</li>)}</ul><p className="small-note">{plan.assumptions}</p>
      <p className="hash-note">Preview hash <code>{plan.plan_hash}</code></p>
      {expired && <p className="notice">Stored preview expired. Request a new illustration for fresh observations.</p>}
      <button className="button button--secondary" disabled={!!expired || busy} onClick={download}><Download size={16} />Download preview</button>
    </div>;
}

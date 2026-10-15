"use client";

import { useEffect, useRef, useState } from "react";
import { Download, FileCheck2, LoaderCircle } from "lucide-react";
import { money } from "@/lib/types";

type Quote = { address: string; notional: string; estimated_exchange_fee: string; hypothetical_builder_fee: string;
  estimated_total_if_applied: string; builder_approval_status: string; assumptions: string };
type Plan = { expected_signer: string; intent: "approve" | "revoke"; maximum_fee_percent: string; builder_address: string;
  preview_valid_until: string; typed_data: Record<string, unknown>; action: { nonce: number }; plan_hash: string };

export function BuilderConsent({ address, configured, now }: { address: string; configured: boolean; now: number }) {
  const [notional, setNotional] = useState("50");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const expired = !!plan && now >= Date.parse(plan.preview_valid_until);

  async function preview(intent: "quote" | "approve" | "revoke") {
    setBusy(intent); setError(""); setMessage("");
    if (intent === "quote") setQuote(null); else setPlan(null);
    const current = new AbortController(); controller.current = current;
    try {
      const response = await fetch(`/api/v1/users/testnet/${intent === "quote" ? "fee-quote" : "consent-preview"}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: current.signal,
        body: JSON.stringify(intent === "quote" ? { address, notional } : { address, intent }) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Enter a notional from $0.01 to $1,000,000, with up to eight decimal places.");
      if (intent === "quote" ? result.address !== address : result.expected_signer !== address || result.intent !== intent) throw new Error("The preview did not match this account.");
      if (!current.signal.aborted) { if (intent === "quote") setQuote(result); else setPlan(result); }
    } catch (failure) { if (!current.signal.aborted) setError(failure instanceof Error ? failure.message : "Preview unavailable. Retry with fresh account data."); }
    finally { if (!current.signal.aborted) setBusy(""); }
  }

  function download() {
    if (!plan) return;
    if (Date.now() >= Date.parse(plan.preview_valid_until)) { setError("The local preview expired. Prepare a fresh plan before downloading."); return; }
    const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `lobster-testnet-${plan.intent}-${plan.action.nonce}.json`;
    link.click(); URL.revokeObjectURL(url);
    setMessage("Unsigned plan downloaded. No permission changed and no signature was requested.");
  }

  return <section className="builder-consent" aria-labelledby="builder-consent-title">
    <h3 id="builder-consent-title">Review the cost and consent</h3>
    <p className="small-note">Previews only. Signing and exchange submission are not enabled.</p>
    <label>Executed notional · USDC<input inputMode="decimal" value={notional} onChange={event => { setNotional(event.target.value); setQuote(null); }} disabled={!!busy} autoComplete="off" /></label>
    <button className="button button--secondary" disabled={!!busy || !notional.trim()} onClick={() => { void preview("quote"); }}>{busy === "quote" ? <LoaderCircle size={16} className="spinner" /> : <FileCheck2 size={16} />}Preview costs</button>
    {error && <p className="form-error" role="alert">{error}</p>}
    {quote && <div className="testnet-preview" aria-live="polite"><strong>One taker fill · {money(quote.notional)}</strong>
      <dl className="testnet-observations"><div><dt>Exchange fee · estimated</dt><dd>{money(quote.estimated_exchange_fee, 6)}</dd></div><div><dt>Builder fee · hypothetical</dt><dd>{money(quote.hypothetical_builder_fee, 6)}</dd></div><div><dt>Total if applied</dt><dd>{money(quote.estimated_total_if_applied, 6)}</dd></div></dl><p className="small-note">{quote.assumptions}</p></div>}
    {!configured && <p className="small-note">Configure USER_TESTNET_BUILDER_ADDRESS locally to prepare consent plans. No builder recipient is selected automatically.</p>}
    <div className="user-consent-actions"><button className="button button--secondary" disabled={!!busy || !configured} onClick={() => { void preview("approve"); }}>{busy === "approve" && <LoaderCircle size={16} className="spinner" />}Approval plan</button>
      <button className="button button--secondary" disabled={!!busy || !configured} onClick={() => { void preview("revoke"); }}>{busy === "revoke" && <LoaderCircle size={16} className="spinner" />}Revocation plan</button></div>
    {plan && <div className="testnet-preview user-consent-plan" aria-live="polite"><strong>Unsigned {plan.intent === "approve" ? "approval" : "revocation"} · {plan.maximum_fee_percent}</strong>
      <dl className="testnet-addresses"><div><dt>Expected user main wallet</dt><dd>{plan.expected_signer}</dd></div><div><dt>Builder recipient · testnet</dt><dd>{plan.builder_address}</dd></div></dl>
      <p className="small-note">This changes no permission. The 30-second preview deadline is local metadata; it does not add cryptographic expiry to the action. A future signer must verify the account and obtain explicit consent.</p>
      {expired && <p className="notice">Local preview expired. Prepare a fresh plan.</p>}
      <details><summary>Inspect EIP-712 payload</summary><pre>{JSON.stringify(plan.typed_data, null, 2)}</pre></details>
      <p className="hash-note">Preview hash <code>{plan.plan_hash}</code></p>
      <button className="button button--secondary" disabled={expired || !!busy} onClick={download}><Download size={16} />Download unsigned plan</button>
    </div>}
    {message && <p className="positive" role="status">{message}</p>}
  </section>;
}

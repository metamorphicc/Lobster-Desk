"use client";

/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4
 * component: consent workbench · genre: atmospheric · theme: Midnight
 * states: default · hover · focus · active · disabled · loading · error · success */
import { useEffect, useRef, useState } from "react";
import { Download, FileCheck2, LoaderCircle, RefreshCw } from "lucide-react";
import { validateExecutionContext, validateLocalIntent, validatePermissionPlans,
  type ExecutionContext, type LocalIntent, type PermissionPlans } from "@/lib/user-consent";

type Plan = { id: string; plan_hash: string; episode_id: string; expires_at: string };
type Busy = "" | "context" | "intent" | "permissions";
type Model = { context: ExecutionContext | null; intent: LocalIntent | null; permissions: PermissionPlans | null; busy: Busy; error: string };
type Actions = { refresh: () => void; prepare: (kind: "intent" | "permissions") => void; download: (kind: "intent" | "permissions") => void };

export function UserConsent({ address, token, plan, now, onSessionInvalid }: {
  address: string; token: string; plan: Plan; now: number; onSessionInvalid: () => void;
}) {
  const [model, setModel] = useState<Model>({ context: null, intent: null, permissions: null, busy: "context", error: "" });
  const request = useRef<AbortController | null>(null), generation = useRef(0);
  useEffect(() => { void load("context"); return () => { generation.current++; request.current?.abort(); }; }, [address, token, plan.id]);
  async function load(kind: Exclude<Busy, "">) {
    const revision = ++generation.current, controller = new AbortController(); request.current?.abort(); request.current = controller;
    setModel(previous => ({ ...previous, busy: kind, error: "", ...(kind === "intent" ? { intent: null } : kind === "permissions" ? { permissions: null } : {}) }));
    try {
      const path = kind === "context" ? "execution-context" : kind === "intent" ? "intents" : "permission-plans";
      const response = await fetch("/api/v1/users/testnet/" + path, { method: kind === "context" ? "GET" : "POST", cache: "no-store",
        headers: { Authorization: "Bearer " + token, ...(kind === "intent" ? { "Content-Type": "application/json" } : {}) },
        ...(kind === "intent" ? { body: JSON.stringify({ plan_id: plan.id }) } : {}),
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) });
      if (controller.signal.aborted || revision !== generation.current) return;
      if (response.status === 401) { onSessionInvalid(); return; }
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Unsigned consent preview is unavailable.");
      if (controller.signal.aborted || revision !== generation.current) return;
      if (kind === "context") {
        const context = validateExecutionContext(value, address);
        setModel(previous => ({ ...previous, context }));
      } else {
        const profile = model.context?.profile;
        if (!profile) throw new Error("An operator must configure a separate public API-wallet profile first.");
        if (kind === "intent") {
          const intent = validateLocalIntent(value, profile, plan);
          setModel(previous => ({ ...previous, intent, context: previous.context ? { ...previous.context,
            intents: [intent, ...previous.context.intents.filter(item => item.id !== intent.id)].slice(0, 10) } : null }));
        } else {
          const permissions = validatePermissionPlans(value, profile);
          setModel(previous => ({ ...previous, permissions }));
        }
      }
    } catch (failure) {
      if (!controller.signal.aborted && revision === generation.current) setModel(previous => ({ ...previous,
        ...(kind === "context" ? { context: null, intent: null, permissions: null } : {}),
        error: failure instanceof Error ? failure.message : "Consent preview unavailable." }));
    } finally { if (!controller.signal.aborted && revision === generation.current) setModel(previous => ({ ...previous, busy: "" })); }
  }
  function download(kind: "intent" | "permissions") {
    const value = kind === "intent" ? model.intent : model.permissions;
    if (!value || (kind === "intent" && (!model.intent || Date.now() >= model.intent.expires_ms))) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `lobster-unsigned-${kind}-${plan.id}.json`; link.click(); URL.revokeObjectURL(url);
  }
  return <UserConsentView model={model} plan={plan} now={now} actions={{ refresh: () => { void load("context"); }, prepare: kind => { void load(kind); }, download }} />;
}

export function UserConsentView({ model, plan, now, actions }: { model: Model; plan: Plan; now: number; actions: Actions }) {
  const { context, intent, permissions, busy, error } = model;
  const profile = context?.profile, expired = now >= Date.parse(plan.expires_at), intentExpired = !!intent && (intent.expired || now >= intent.expires_ms);
  return <section className="builder-consent user-consent" aria-label="Unsigned execution consent">
    <h3>Review execution permissions</h3>
    <p className="small-note">Unsigned preparation only. Wallet signing, delegation, fee approval and exchange submission remain disabled.</p>
    {!context && !busy && !error && <p className="notice">Load the private execution context before preparing a permission.</p>}
    {context && !profile && <p className="notice">No execution profile is configured for this wallet. An operator must register the public user, separate API-wallet and builder addresses first. Never paste private keys here.</p>}
    {profile && <><dl className="testnet-observations"><div><dt>Network</dt><dd>Testnet only</dd></div><div><dt>Builder fee · entry only</dt><dd>{profile.fee_tenths_bps / 1000}%</dd></div></dl>
      <p className="hash-note">User <code>{profile.address}</code></p><p className="hash-note">Dedicated API wallet <code>{profile.agent}</code></p><p className="hash-note">Builder <code>{profile.builder}</code></p></>}
    <div className="consent-actions"><button className="button button--secondary" disabled={!!busy || !profile || expired} onClick={() => actions.prepare("intent")}>
      {busy === "intent" ? <LoaderCircle size={16} className="spinner" /> : <FileCheck2 size={16} />}{busy === "intent" ? "Preparing…" : "Prepare local intent"}</button>
      <button className="button button--secondary" disabled={!!busy || !profile} onClick={() => actions.prepare("permissions")}>
        {busy === "permissions" ? <LoaderCircle size={16} className="spinner" /> : <FileCheck2 size={16} />}{busy === "permissions" ? "Preparing…" : "Review permissions"}</button>
      <button className="button button--secondary" disabled={!!busy} onClick={actions.refresh}>{busy === "context" ? <LoaderCircle size={16} className="spinner" /> : <RefreshCw size={16} />}Refresh journal</button></div>
    {expired && <p className="notice">Order preview expired. Prepare a new order preview before creating a local intent.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {intent && <div className="testnet-preview" aria-live="polite"><strong>Local intent prepared · Signing disabled</strong>
      <p className="small-note">Binds this exact preview, user, API wallet, builder, fee, nonce and deadline. This local domain grants no Hyperliquid permission.</p>
      <p className="hash-note">Plan hash <code>{intent.plan_hash}</code></p><p className="small-note">Local nonce {intent.nonce} · Deadline {new Date(intent.expires_ms).toLocaleTimeString("en-GB", { hour12: false })}</p>
      <details><summary>View local payload</summary><pre className="auth-message">{JSON.stringify(intent.typed_data, null, 2)}</pre></details>
      {intentExpired && <p className="notice">Local intent expired. No permission or order was submitted.</p>}
      <button className="button button--secondary" disabled={!!busy || intentExpired} onClick={() => actions.download("intent")}><Download size={16} />Export intent</button></div>}
    {permissions && <div className="testnet-preview" aria-live="polite"><strong>Exchange permissions · Unsigned</strong>
      <p className="notice">Agent delegation and builder approval are broader than one trade. No wallet prompt or approval is submitted here. A local preview deadline cannot revoke a future exchange approval.</p>
      <details><summary>View permissions</summary><pre className="auth-message">{JSON.stringify(permissions, null, 2)}</pre></details>
      <button className="button button--secondary" disabled={!!busy} onClick={() => actions.download("permissions")}><Download size={16} />Export approvals</button></div>}
    {!!context?.intents.length && <><h4>Recent local intents</h4><ul className="user-position-list">{context.intents.map(item => <li key={item.id}>
      <span>{item.status.replaceAll("_", " ")} · {item.expired || now >= item.expires_ms ? "expired" : "local only"}</span><p className="hash-note"><code>{item.id}</code></p></li>)}</ul></>}
    <p className="small-note">Local nonce allocation is serialized. Other apps using the same main wallet are outside this journal. Nothing here reserves capital, installs a stop or confirms exchange execution.</p>
  </section>;
}

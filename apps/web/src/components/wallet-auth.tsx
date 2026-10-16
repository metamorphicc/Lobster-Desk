"use client";

import { useEffect, useRef, useState } from "react";
import { Check, FileCheck2, LoaderCircle, LogOut } from "lucide-react";
import type { WalletSession } from "@/lib/wallet";
import { AUTH_ORIGIN, validateAuthChallenge, validateAuthResult, type AuthChallenge, type AuthResult } from "@/lib/wallet-auth";
import type { Episode } from "@/lib/types";
import { UserOrderPreview } from "./user-order-preview";

const prefix = "/api/v1/users/testnet/auth/";
async function revoke(token: string): Promise<boolean> {
  try {
    const response = await fetch(prefix + "logout", { method: "POST", headers: { Authorization: "Bearer " + token },
      signal: AbortSignal.timeout(5000), cache: "no-store" });
    return response.ok || response.status === 401;
  } catch { return false; }
}

export function WalletAuth({ address, chainId, session, now, episodes }: { address: string; chainId: string; session: WalletSession; now: number; episodes: Episode[] }) {
  const [challenge, setChallenge] = useState<AuthChallenge | null>(null);
  const [result, setResult] = useState<AuthResult | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const credential = useRef<AuthResult | null>(null);
  useEffect(() => () => {
    request.current?.abort();
    const token = credential.current?.access_token;
    credential.current = null;
    if (token) void revoke(token);
  }, []);
  const ready = result && result.address === address && now < Date.parse(result.expires_at);
  const expired = challenge && now >= Date.parse(challenge.expires_at);
  const chainOk = /^0x[0-9a-f]+$/i.test(chainId) && BigInt(chainId) === 421614n;

  async function post(path: string, body: unknown, current: AbortController) {
    const response = await fetch(prefix + path, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: AbortSignal.any([current.signal, AbortSignal.timeout(10000)]), cache: "no-store" });
    const value = await response.json();
    if (!response.ok) throw new Error("Local sign-in request failed.");
    return value;
  }
  async function act(sign: boolean) {
    const walletRevision = session.snapshot().revision;
    request.current?.abort();
    const current = new AbortController(); request.current = current;
    setBusy(sign ? "sign" : "prepare"); setError(""); setNotice("");
    try {
      if (!sign) {
        setChallenge(null);
        if (window.location.origin !== AUTH_ORIGIN || !chainOk) throw new Error();
        const value = await post("challenge", { address }, current);
        const reviewed = validateAuthChallenge(value, address, window.location.origin, chainId);
        if (!current.signal.aborted) setChallenge(reviewed);
      } else {
        if (!challenge) throw new Error();
        const signature = await session.signAuthentication(challenge, window.location.origin);
        if (current.signal.aborted) return;
        const value = await post("verify", { challenge_id: challenge.challenge_id, signature }, current);
        const verified = validateAuthResult(value, address);
        if (current.signal.aborted) { void revoke(verified.access_token); return; }
        // The wallet may change while the HTTP proof is being verified.
        if (session.snapshot().address !== address || session.snapshot().chainId !== chainId || session.snapshot().revision !== walletRevision) {
          void revoke(verified.access_token); throw new Error();
        }
        credential.current = verified; setResult(verified); setChallenge(null);
      }
    } catch (failure) {
      if (!current.signal.aborted) {
        setChallenge(null);
        const code = failure && typeof failure === "object" ? (failure as { code?: number }).code : null;
        setError(code === 4001 ? "Sign-in declined. No permission changed." : "Sign-in could not complete. Check the canonical local URL, wallet account, chain 421614 and message deadline, then prepare again.");
      }
    } finally { if (request.current === current && !current.signal.aborted) setBusy(""); }
  }
  function cancel() { request.current?.abort(); setBusy(""); setChallenge(null); setNotice("Local sign-in cancelled. Dismiss any pending prompt in your wallet."); }
  async function logout() {
    const token = credential.current?.access_token;
    credential.current = null; setResult(null); setChallenge(null); setError("");
    if (token && !await revoke(token)) setNotice("Local credentials cleared. Server revocation could not be confirmed; the token expires within 15 minutes.");
    else setNotice("Local session cleared.");
  }

  return <section className="builder-consent wallet-auth" aria-labelledby="wallet-auth-title">
    <h3 id="wallet-auth-title">Verify this wallet for private previews</h3>
    <p className="small-note">Optional sign-in proves control of this wallet. It grants no trading, transfers or builder-fee permission. The session stays in this page&apos;s memory and expires within 15 minutes.</p>
    {ready ? <><p className="positive user-connected"><Check size={16} />Verified for local previews</p><p className="small-note">Expires {new Date(result.expires_at).toLocaleTimeString("en-GB", { hour12: false })}. Scope: testnet previews only.</p>
      <button className="button button--secondary" onClick={() => { void logout(); }}><LogOut size={16} />Sign out</button>
      <UserOrderPreview address={address} token={result.access_token} episodes={episodes} now={now} onSessionInvalid={() => { credential.current = null; setResult(null); setError("The server session is no longer valid. Sign in again."); }} /></> : <>
      {result && <p className="notice">The local session expired. Sign in again for private previews.</p>}
      {!chainOk && <p className="notice">Sign-in requires wallet chain 421614 (Arbitrum Sepolia). Select it manually, then reconnect. Public account viewing works without signing in.</p>}
      <button className="button button--secondary" disabled={!!busy || !chainOk} onClick={() => { void act(false); }}>{busy === "prepare" ? <LoaderCircle size={16} className="spinner" /> : <FileCheck2 size={16} />}Prepare sign-in message</button>
      {challenge && <SignInMessage challenge={challenge} expired={!!expired} busy={busy === "sign"} sign={() => { void act(true); }} />}
      {busy && <button className="text-button" onClick={cancel}>Cancel sign-in</button>}
    </>}
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="small-note" role="status">{notice}</p>}
  </section>;
}

export function SignInMessage({ challenge, expired, busy, sign }: { challenge: AuthChallenge; expired: boolean; busy: boolean; sign: () => void }) {
  return <div className="testnet-preview"><strong>Review before opening your wallet</strong><pre className="auth-message">{challenge.message}</pre>
        <p className="small-note">EOA wallets only. This is a local authentication message, not an exchange approval. Valid until {new Date(challenge.expires_at).toLocaleTimeString("en-GB", { hour12: false })}.</p>
        {expired && <p className="notice">Message expired. Prepare a fresh one.</p>}
        <button className="button button--secondary" disabled={busy || expired} onClick={() => { sign(); }}>{busy && <LoaderCircle size={16} className="spinner" />}Sign this message</button></div>;
}

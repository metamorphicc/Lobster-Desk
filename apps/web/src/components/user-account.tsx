"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, Eye, LoaderCircle, RefreshCw, Wallet as WalletIcon } from "lucide-react";
import { money, number } from "@/lib/types";
import { discoverWallets, normalizeAddress, WalletSession, type Wallet, type WalletState } from "@/lib/wallet";
import { BuilderConsent } from "./builder-consent";
import { WalletAuth } from "./wallet-auth";

type UserConfig = { builder_address: string | null; builder_fee_percent: string; builder_fee_tenths_bps: number };
type Account = UserConfig & {
  address: string; observed_at: string; stale: boolean; equity: string; withdrawable: string;
  positions: { symbol: string; quantity: string; entry_price: string | null; unrealized_pnl: string }[];
  open_orders: { symbol: string; oid: string; side: string; quantity: string; limit_price: string; reduce_only: boolean; is_trigger: boolean }[];
  reported_taker_rate: string; approved_builder_fee_tenths_bps: number | null; builder_approval_status: string;
};
const initial: WalletState = { status: "idle", address: null, chainId: null, error: null, revision: 0 };

export function UserAccount() {
  const session = useRef<WalletSession | null>(null);
  const [wallet, setWallet] = useState(initial);
  const [wallets, setWallets] = useState<Wallet[]>([]);
  const [selected, setSelected] = useState("");
  const [config, setConfig] = useState<UserConfig | null>(null);
  const [input, setInput] = useState("");
  const [watched, setWatched] = useState<string | null>(null);
  const [result, setResult] = useState<{ key: string; data: Account } | null>(null);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState("");
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [now, setNow] = useState(0);
  const address = wallet.address || watched;
  const key = `${address}:${wallet.revision}:${refresh}`;
  const data = result?.key === key && result.data.address === address ? result.data : null;
  const stale = data && (data.stale || now - Date.parse(data.observed_at) > 15000);
  const availableConfig = data || config;
  useEffect(() => {
    const current = new WalletSession(); session.current = current;
    const unsubscribe = current.subscribe(setWallet);
    const stopDiscovery = discoverWallets(window, setWallets);
    const controller = new AbortController();
    void fetch("/api/v1/users/testnet/config", { signal: controller.signal, cache: "no-store" }).then(async response => {
      if (!response.ok) throw new Error();
      const value = await response.json(); if (!controller.signal.aborted) setConfig(value);
    }).catch(() => { if (!controller.signal.aborted) setError("User account settings are unavailable. Check the local API."); });
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => { unsubscribe(); current.disconnect(); stopDiscovery(); controller.abort(); clearInterval(timer); };
  }, []);
  useEffect(() => {
    setResult(null); setError("");
    if (!address) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    void fetch(`/api/v1/users/testnet/accounts/${address}`, { cache: "no-store", signal: controller.signal }).then(async response => {
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "The testnet account could not be read.");
      if (value.address !== address || !Number.isFinite(Date.parse(value.observed_at))) throw new Error("The account response did not match the requested address.");
      if (!controller.signal.aborted) { setResult({ key, data: value }); setNow(Date.now()); }
    }).catch(failure => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Account observation failed."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [address, key]);

  function watch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = normalizeAddress(input.trim());
    if (!normalized) { setFieldError("Enter a nonzero Ethereum address: 0x followed by 40 hexadecimal characters."); return; }
    setFieldError(""); setWatched(normalized); setRefresh(value => value + 1);
  }

  return <section className="testnet-panel user-account" aria-labelledby="user-account-title">
    <div className="panel-heading"><h2 id="user-account-title"><WalletIcon size={17} /> Your testnet account</h2><span className="tag">READ ONLY</span></div>
    <div className="testnet-body">
      <p>Connect a wallet or watch a public address. Your account stays separate from the tank&apos;s capital. Public viewing requests no signature. Optional sign-in below requires a separate, explicit message signature.</p>
      <div className="user-account-layout"><div className="user-account-controls">
        {wallet.status === "connected" ? <><p className="positive user-connected"><Check size={16} />Wallet connected for public data</p><p className="small-note">Wallet chain {wallet.chainId}. Account observations below always use Hyperliquid testnet.</p>
          <button className="button button--secondary" onClick={() => { session.current?.disconnect(); setWatched(null); }}>Disconnect view</button><p className="small-note">This clears the page view. Site permissions in your wallet are managed separately.</p></> : <>
          {wallets.length ? <><label>Wallet provider<select value={selected || wallets[0].id} onChange={event => setSelected(event.target.value)} disabled={wallet.status === "connecting"}>{wallets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <button className="button button--secondary" disabled={wallet.status === "connecting" || !wallets.some(item => item.id === (selected || wallets[0].id))} onClick={() => {
              const provider = wallets.find(item => item.id === (selected || wallets[0].id))?.provider;
              if (provider) { setWatched(null); setFieldError(""); void session.current?.connect(provider); }
            }}>{wallet.status === "connecting" ? <LoaderCircle size={16} className="spinner" /> : <WalletIcon size={16} />}{wallet.status === "connecting" ? "Waiting for wallet…" : "Connect wallet"}</button></> : <p className="small-note">No injected wallet detected. Open this page in a wallet-enabled browser, or use public-address watch mode.</p>}
          {wallet.status === "connecting" && <button className="text-button" onClick={() => session.current?.disconnect()}>Cancel waiting</button>}
          {wallet.status !== "connecting" && <form className="user-watch-form" onSubmit={watch}><label>Watch a public address<input value={input} onChange={event => { setInput(event.target.value); setFieldError(""); }} autoComplete="off" spellCheck={false} placeholder="0x…" aria-invalid={!!fieldError} aria-describedby="watch-address-help" /></label>
            <p id="watch-address-help" className={fieldError ? "form-error" : "small-note"}>{fieldError || "Public watch mode does not connect or authenticate a wallet."}</p><button className="button button--secondary" type="submit" disabled={loading || !input.trim()}><Eye size={16} />Watch address</button></form>}
        </>}
        {wallet.error && <p className="notice" role="status">{wallet.error}</p>}
        {address && <dl className="testnet-addresses"><div><dt>{wallet.address ? "Connected wallet address" : "Watched public address"}</dt><dd>{address}</dd></div></dl>}
      </div><div className="user-account-data" aria-live="polite">
        {error && <div className="notice notice--error" role="alert">{error}</div>}
        {address ? <>
          <div className="user-observation-heading"><span className="micro-label">HYPERLIQUID TESTNET</span><button className="text-button" disabled={loading} onClick={() => setRefresh(value => value + 1)}>{loading ? <LoaderCircle size={14} className="spinner" /> : <RefreshCw size={14} />}{loading ? "Reading account…" : "Refresh"}</button></div>
          {stale && <div className="notice">This observation is over 15 seconds old. Refresh before making any decision.</div>}
          <dl className="testnet-observations"><div><dt>Account equity</dt><dd>{money(data?.equity)}</dd></div><div><dt>Withdrawable</dt><dd>{money(data?.withdrawable)}</dd></div><div><dt>Open orders</dt><dd>{data ? data.open_orders.length : "—"}</dd></div></dl>
          {data && <>
            <p className="small-note">Observed {new Date(data.observed_at).toLocaleTimeString("en-GB", { hour12: false })}. This public lookup does not authenticate ownership.</p>
            <ul className="user-position-list">{data.positions.length ? data.positions.map(position => <li key={position.symbol}><strong>{position.symbol}</strong><span>{number(position.quantity, 6)} · Open PnL {money(position.unrealized_pnl)}</span></li>) : <li>No open perpetual positions observed.</li>}</ul>
            <ul className="user-position-list">{data.open_orders.slice(0, 20).map(order => <li key={order.oid}><strong>{order.symbol} · {order.side === "B" ? "buy" : "sell"}</strong><span>{number(order.quantity, 6)} @ {money(order.limit_price)}{order.reduce_only ? " · reduce only" : ""}{order.is_trigger ? " · trigger" : ""}</span></li>)}</ul>
            {data.open_orders.length > 20 && <p className="small-note">Showing the first 20 observed open orders.</p>}
          </>}
        </> : <p className="empty-note">Your testnet balances and orders appear after an explicit connection or address lookup. No account is selected automatically.</p>}
      </div></div>
      <div className="user-fee-note"><strong>Builder fee · {availableConfig?.builder_fee_percent || "—"}</strong><p>Additional to exchange trading costs on executed notional. Fee collection and user order submission are disabled.</p>
        <dl className="testnet-addresses"><div><dt>Builder recipient</dt><dd>{availableConfig?.builder_address || "Not configured"}</dd></div></dl>
        {data && <p>Approval: <strong>{data.builder_approval_status.replaceAll("_", " ")}</strong>{data.approved_builder_fee_tenths_bps != null ? ` · Maximum ${(data.approved_builder_fee_tenths_bps / 1000).toLocaleString("en-US", { maximumFractionDigits: 3 })}%` : ""}. Reported account taker rate {(Number(data.reported_taker_rate) * 100).toLocaleString("en-US", { maximumFractionDigits: 5 })}%.</p>}
      </div>
      {wallet.address && wallet.chainId && session.current && <WalletAuth key={`${wallet.address}:${wallet.revision}`} address={wallet.address} chainId={wallet.chainId} session={session.current} now={now} />}
      {!wallet.address && <p className="small-note">Private previews require a connected wallet and a separate sign-in message. Watching an address grants no private session.</p>}
      {address && <BuilderConsent key={key} address={address} configured={!!availableConfig?.builder_address} now={now} />}
    </div>
  </section>;
}
